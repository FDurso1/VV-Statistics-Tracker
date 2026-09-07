
"""
Rebuilds data/mtg_data.db from data/mtg_data.xlsx.

Run locally after editing the spreadsheet:
    python scripts/build_db.py
    python scripts/build_db.py --tournament 2026-08-19-MTGO-Wed
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Callable

import pandas as pd

ROOT: Path = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.moxfield import fetch_full_snapshot, extract_cards_from_snapshot
from app.moxfield import extract_name_from_snapshot, extract_deck_id, InvalidMoxfieldURLError, CardInfo

from app.scoring import parse_wld
from app.formatting import clean_deck_name
from app.keyword_matching import parse_keyword_groups, generate_all_search_aliases
from app.db_archive import ensure_db_extracted

# Type aliases
FetchFn = Callable[[str], dict[str, Any]]
ConfirmFn = Callable[[list[str]], bool]
ArchetypeCache = dict[str, int]
DeckCache = dict[str, tuple[int, str]]
PlayerCache = dict[str, int]
AliasMap = dict[str, int]

DB_PATH: Path = ROOT / "data" / "mtg_data.db"
SCHEMA_PATH: Path = ROOT / "schema.sql"
SNAPSHOT_DIR: Path = ROOT / "data" / "deck_snapshots"

PLAYERS_SHEET_COLUMNS: list[str] = [
    "name", "moxfield_username", "discord_username", "twitch_username",
    "bio", "is_public", "aliases",
]
ARCHETYPES_SHEET_COLUMNS: list[str] = [
    "Primary Colors", "Primary Archetype", "Variant Of", "Style",
]

SheetTuple = tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]

def _find_xlsx_path(data_dir: Path, base_name: str = "mtg_data") -> Path:

    pattern: re.Pattern[str] = re.compile(
        rf"{re.escape(base_name)}(?: ?\((\d+)\))?\.xlsx"
    )

    def _suffix_number(p: Path) -> int:
        m: re.Match[str] | None = pattern.fullmatch(p.name)
        return int(m.group(1)) if m and m.group(1) else 0

    candidates: list[Path] = sorted(
        (p for p in data_dir.glob(f"{base_name}*.xlsx") if pattern.fullmatch(p.name)),
        key=_suffix_number,
    )

    if not candidates:
        return data_dir / f"{base_name}.xlsx"

    chosen: Path = candidates[-1]
    if len(candidates) > 1:
        print(f"WARNING: multiple '{base_name}*.xlsx' files found in {data_dir}:")
        for c in candidates:
            print(f"  - {c.name}" + ("  <- using this one" if c == chosen else ""))
        print("Delete the older copies!")

    return chosen

XLSX_PATH: Path = _find_xlsx_path(ROOT / "data")

def load_sheets(xlsx_path: Path) -> SheetTuple:

    with pd.ExcelFile(xlsx_path) as xls:
        tournaments: pd.DataFrame = pd.read_excel(xls, sheet_name="Tournaments").fillna("") # pyright: ignore[reportUnknownMemberType]
        games: pd.DataFrame = pd.read_excel(xls, sheet_name="Games").fillna("") # pyright: ignore[reportUnknownMemberType]
        standings: pd.DataFrame = pd.read_excel(xls, sheet_name="Standings").fillna("") # pyright: ignore[reportUnknownMemberType]
        try:
            players: pd.DataFrame = pd.read_excel(xls, sheet_name="Players").fillna("") # pyright: ignore[reportUnknownMemberType]
        except ValueError:
            players = pd.DataFrame(columns=PLAYERS_SHEET_COLUMNS)
        try:
            archetypes: pd.DataFrame = pd.read_excel(xls, sheet_name="Archetypes").fillna("") # pyright: ignore[reportUnknownMemberType]
        except ValueError:
            archetypes = pd.DataFrame(columns=ARCHETYPES_SHEET_COLUMNS)
        try:
            keyword_maps: pd.DataFrame = pd.read_excel(xls, sheet_name="KeywordMaps").fillna("") # pyright: ignore[reportUnknownMemberType]
        except ValueError:
            keyword_maps = pd.DataFrame()
    return tournaments, games, standings, players, archetypes, keyword_maps

def rebuild_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text())


def _is_truthy(value: Any) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y")

def find_unknown_players( games_df: pd.DataFrame, standings_df: pd.DataFrame, players_df: pd.DataFrame,) -> list[str]:

    known: set[str] = {str(n).strip() for n in players_df["name"] if str(n).strip()}
    if "aliases" in players_df.columns:
        for aliases_cell in players_df["aliases"]:
            for alias in str(aliases_cell).split(";"):
                alias = alias.strip()
                if alias:
                    known.add(alias)

    referenced: set[str] = set()
    for col in ("player_1", "player_2"):
        if col in games_df.columns:
            referenced |= {str(n).strip() for n in games_df[col] if str(n).strip()}
    if "player" in standings_df.columns:
        referenced |= {str(n).strip() for n in standings_df["player"] if str(n).strip()}

    return sorted(referenced - known)

def find_unknown_archetypes(standings_df: pd.DataFrame, archetypes_df: pd.DataFrame,) -> list[str]:

    known: set[str] = {str(n).strip() for n in archetypes_df["Primary Archetype"] if str(n).strip()}
    referenced: set[str] = set()
    if "archetype" in standings_df.columns:
        referenced |= {str(n).strip() for n in standings_df["archetype"] if str(n).strip()}
    return sorted(referenced - known)


def find_unknown_tournaments(
    games_df: pd.DataFrame, standings_df: pd.DataFrame, tournaments_df: pd.DataFrame,
) -> list[str]:

    known: set[str] = {str(t).strip() for t in tournaments_df["tournament_id"] if str(t).strip()}
    referenced: set[str] = set()
    if "tournament_id" in games_df.columns:
        referenced |= {str(t).strip() for t in games_df["tournament_id"] if str(t).strip()}
    if "tournament_id" in standings_df.columns:
        referenced |= {str(t).strip() for t in standings_df["tournament_id"] if str(t).strip()}
    return sorted(referenced - known)


def find_alias_conflicts(
    games_df: pd.DataFrame, standings_df: pd.DataFrame, players_df: pd.DataFrame,
) -> list[str]:

    conflicts: list[str] = []
    if "aliases" not in players_df.columns:
        return conflicts

    for _, row in players_df.iterrows():
        canonical: str = str(row["name"]).strip()
        if not canonical:
            continue
        aliases: set[str] = {a.strip() for a in str(row.get("aliases", "")).split(";") if a.strip()}
        identity_names: set[str] = {canonical} | aliases
        if len(identity_names) < 2:
            continue

        names_seen_by_tournament: dict[str, set[str]] = {}
        for _, grow in games_df.iterrows():
            tid: str = str(grow["tournament_id"]).strip()
            for col in ("player_1", "player_2"):
                name: str = str(grow[col]).strip()
                if name in identity_names:
                    names_seen_by_tournament.setdefault(tid, set()).add(name)
        for _, srow in standings_df.iterrows():
            tid = str(srow["tournament_id"]).strip()
            name = str(srow["player"]).strip()
            if name in identity_names:
                names_seen_by_tournament.setdefault(tid, set()).add(name)

        for tid, names_seen in names_seen_by_tournament.items():
            if len(names_seen) > 1:
                conflicts.append(
                    f"Tournament '{tid}' has both '{canonical}' and alias(es) "
                    f"{sorted(names_seen - {canonical})} appearing as separate "
                    f"entrants. Fix the Players sheet aliases or check for a "
                    f"data entry error."
                )
    return conflicts

def default_confirm(unknown_names: list[str]) -> bool:

    print("\nThe following players are not in the Players sheet (or anyone's alias):")
    for name in unknown_names:
        print(f"  - {name}")
    answer: str = input("Continue and create default (private) profiles for these? [y/N] ").strip().lower()
    return answer in ("y", "yes")

def get_or_create_named(conn: sqlite3.Connection, table: str, name: str, cache: PlayerCache,) -> int:

    name = str(name).strip()
    if name in cache:
        return cache[name]
    conn.execute(f"INSERT OR IGNORE INTO {table} (name) VALUES (?)", (name,))
    row: sqlite3.Row = conn.execute(f"SELECT id FROM {table} WHERE name = ?", (name,)).fetchone()
    cache[name] = row[0]
    return int(row[0])

def resolve_player_id(
    conn: sqlite3.Connection, raw_name: Any, alias_to_player_id: AliasMap,
    player_cache: PlayerCache,
) -> int:

    name: str = str(raw_name).strip()
    if name in alias_to_player_id:
        return alias_to_player_id[name]
    return get_or_create_named(conn, "players", name, player_cache)

def insert_players_sheet(
    conn: sqlite3.Connection, players_df: pd.DataFrame,
) -> tuple[PlayerCache, AliasMap]:

    player_cache: PlayerCache = {}
    alias_to_player_id: AliasMap = {}

    for _, row in players_df.iterrows():
        name: str = str(row["name"]).strip()
        if not name:
            continue
        moxfield_username: str | None = str(row.get("moxfield_username", "")).strip() or None
        discord_username: str | None = str(row.get("discord_username", "")).strip() or None
        twitch_username: str | None = str(row.get("twitch_username", "")).strip() or None
        bio: str | None = str(row.get("bio", "")).strip() or None
        is_public: int = 1 if _is_truthy(row.get("is_public", "")) else 0

        cur: sqlite3.Cursor = conn.execute(
            "INSERT INTO players (name, moxfield_username, discord_username, "
            "twitch_username, bio, is_public) VALUES (?, ?, ?, ?, ?, ?)",
            (name, moxfield_username, discord_username, twitch_username, bio, is_public),
        )
        player_id: int = cur.lastrowid  # type: ignore[assignment]
        player_cache[name] = player_id
        alias_to_player_id[name] = player_id

        aliases_raw: str = str(row.get("aliases", "")).strip()
        for alias in aliases_raw.split(";"):
            alias = alias.strip()
            if alias:
                conn.execute(
                    "INSERT INTO player_aliases (alias_name, player_id) VALUES (?, ?)",
                    (alias, player_id),
                )
                alias_to_player_id[alias] = player_id

    return player_cache, alias_to_player_id

def insert_archetypes_sheet(
    conn: sqlite3.Connection, archetypes_df: pd.DataFrame,
) -> ArchetypeCache:

    archetype_cache: ArchetypeCache = {}
    for _, row in archetypes_df.iterrows():
        name: str = str(row["Primary Archetype"]).strip()
        if not name:
            continue
        unclaimable: int = 1 if _is_truthy(row.get("Unclaimable", "")) else 0
        cur: sqlite3.Cursor = conn.execute(
            "INSERT INTO archetypes (name, primary_colors, variant_of, style, unclaimable) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                name,
                str(row.get("Primary Colors", "")).strip() or None,
                str(row.get("Variant Of", "")).strip() or None,
                str(row.get("Style", "")).strip() or None,
                unclaimable,
            ),
        )
        archetype_cache[name] = cur.lastrowid  # type: ignore[assignment]
    return archetype_cache

def insert_archetype_search_aliases(
    conn: sqlite3.Connection, archetype_cache: ArchetypeCache,
    keyword_maps_df: pd.DataFrame, warnings: list[str],
) -> None:

    groups: list[list[str]] = parse_keyword_groups(keyword_maps_df)
    if not groups:
        return
    all_names: set[str] = set(archetype_cache.keys())
    aliases_by_name: dict[str, set[str]] = generate_all_search_aliases(
        list(archetype_cache.keys()), groups,
    )
    for name, aliases in aliases_by_name.items():
        archetype_id: int = archetype_cache[name]
        for alias in aliases:
            conn.execute(
                "INSERT OR IGNORE INTO archetype_search_aliases "
                "(archetype_id, alias_text) VALUES (?, ?)",
                (archetype_id, alias),
            )
            if alias in all_names and alias != name:
                warnings.append(
                    f"Archetype '{name}' generates the search alias '{alias}' via "
                    f"KeywordMaps, which is also the name of a different existing "
                    f"archetype -- these may need to be merged into one."
                )

def get_or_create_deck(
    conn: sqlite3.Connection, url: Any, archetype_name: Any,
    player_id: int, date_added: str,
    archetype_cache: ArchetypeCache, deck_cache: DeckCache,
    warnings: list[str], is_mtgo: bool = False,
    fetch_fn: FetchFn = fetch_full_snapshot,
    snapshot_dir: Path = SNAPSHOT_DIR,
    context_label: str | None = None,
) -> int:
    """Look up or create a deck. Store the full Moxfield snapshot."""
    
    url_str: str = str(url).strip()
    arch_str: str = str(archetype_name).strip()

    def _resolve_archetype_id() -> int:
        if not arch_str:
            raise ValueError(
                f"Deck{f' ({context_label})' if context_label else ''} has no "
                f"archetype -- an archetype is always required."
            )
        if arch_str not in archetype_cache:
            raise ValueError(
                f"Deck{f' ({context_label})' if context_label else ''} references "
                f"archetype '{arch_str}', which isn't in the Archetypes sheet."
            )
        return archetype_cache[arch_str]

    def _create_deck_without_cards(archetype_id: int, warn_reason: str) -> int:
        cur: sqlite3.Cursor = conn.execute(
            "INSERT INTO decks (player_id, archetype_id, moxfield_url, name, date_added) "
            "VALUES (?, ?, NULL, NULL, ?)",
            (player_id, archetype_id, date_added),
        )
        warnings.append(
            f"Deck{f' ({context_label})' if context_label else ''}: {warn_reason} - "
            f"counted everywhere except card-level stats."
        )
        return cur.lastrowid  # type: ignore[return-value]

    if not url_str:
        return _create_deck_without_cards(_resolve_archetype_id(), "no Moxfield URL")

    if url_str in deck_cache:
        deck_id: int
        existing_archetype: str
        deck_id, existing_archetype = deck_cache[url_str]
        if arch_str and arch_str != existing_archetype:
            warnings.append(
                f"Deck {url_str}: first recorded as '{existing_archetype}', "
                f"now listed as '{arch_str}'. Fix the fuckup."
            )
        return deck_id

    archetype_id: int = _resolve_archetype_id()

    deck_id_str: str = extract_deck_id(url_str)
    if not re.fullmatch(r"[\w-]+", deck_id_str):
        return _create_deck_without_cards(
            archetype_id,
            f"'{url_str}' isn't a usable Moxfield URL",
        )

    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_file: Path = snapshot_dir / f"{deck_id_str}.json"
    snapshot_data: dict[str, Any]
    if snapshot_file.exists():
        snapshot_data = json.loads(snapshot_file.read_text())
    else:
        print(f"  fetching new deck snapshot: {url_str}")
        try:
            snapshot_data = fetch_fn(url_str)
        except InvalidMoxfieldURLError:
            return _create_deck_without_cards(
                archetype_id,
                f"'{url_str}' isn't a usable Moxfield URL 2",
            )
        snapshot_file.write_text(json.dumps(snapshot_data, indent=2))

    cards: dict[str, CardInfo]
    raw_name: str | None
    if "boards" in snapshot_data:
        cards = extract_cards_from_snapshot(snapshot_data)
        raw_name = extract_name_from_snapshot(snapshot_data)
    else:
        cards = snapshot_data  # type: ignore[assignment]
        raw_name = None

    deck_name: str | None = clean_deck_name(raw_name, is_mtgo=is_mtgo)

    cur: sqlite3.Cursor = conn.execute(
        "INSERT INTO decks (player_id, archetype_id, moxfield_url, name, date_added) "
        "VALUES (?, ?, ?, ?, ?)",
        (player_id, archetype_id, url_str, deck_name, date_added),
    )
    deck_id = cur.lastrowid  # type: ignore[assignment]

    card_name: str
    info: CardInfo
    for card_name, info in cards.items():
        existing: sqlite3.Row | None = conn.execute(
            "SELECT id FROM cards WHERE name = ?", (card_name,)
        ).fetchone()
        card_id: int
        if existing:
            card_id = int(existing[0])
        else:
            cur2: sqlite3.Cursor = conn.execute(
                "INSERT INTO cards (name, scryfall_id, first_seen_date) VALUES (?, ?, ?)",
                (card_name, info.get("scryfall_id"), date_added),
            )
            card_id = cur2.lastrowid  # type: ignore[assignment]
        conn.execute(
            "INSERT INTO deck_cards (deck_id, card_id, quantity, "
            "mainboard_quantity, sideboard_quantity) VALUES (?, ?, ?, ?, ?)",
            (deck_id, card_id, int(info["quantity"]),
             int(info.get("mainboard_quantity", 0)),
             int(info.get("sideboard_quantity", 0))),
        )

    deck_cache[url_str] = (deck_id, arch_str)
    return deck_id

def _build_from_dataframes(
    tournaments_df: pd.DataFrame, games_df: pd.DataFrame,
    standings_df: pd.DataFrame, players_df: pd.DataFrame,
    archetypes_df: pd.DataFrame, keyword_maps_df: pd.DataFrame,
    db_path: Path = DB_PATH, fetch_fn: FetchFn = fetch_full_snapshot,
    snapshot_dir: Path = SNAPSHOT_DIR, confirm_fn: ConfirmFn = default_confirm,
    source_label: str = "",
) -> list[str]:

    # Pre-write validation
    unknown_tournaments: list[str] = find_unknown_tournaments(games_df, standings_df, tournaments_df)
    if unknown_tournaments:
        raise ValueError(
            f"Tournament ID(s) referenced in Games/Standings but missing from "
            f"the Tournaments sheet: {unknown_tournaments}"
        )

    unknown_archetypes: list[str] = find_unknown_archetypes(standings_df, archetypes_df)
    if unknown_archetypes:
        raise ValueError(
            f"Archetype(s) referenced in Standings but missing from the "
            f"Archetypes sheet: {unknown_archetypes}"
        )

    alias_conflicts: list[str] = find_alias_conflicts(games_df, standings_df, players_df)
    if alias_conflicts:
        raise ValueError(
            "Alias conflict(s) found (same person can't appear twice in one "
            f"tournament):\n" + "\n".join(alias_conflicts)
        )

    unknown_players: list[str] = find_unknown_players(games_df, standings_df, players_df)
    if unknown_players:
        if not confirm_fn(unknown_players):
            print("Abort")
            sys.exit(1)

    conn: sqlite3.Connection = sqlite3.connect(db_path)
    rebuild_schema(conn)

    warnings: list[str] = []
    archetype_cache: ArchetypeCache = insert_archetypes_sheet(conn, archetypes_df)
    insert_archetype_search_aliases(conn, archetype_cache, keyword_maps_df, warnings)
    player_cache: PlayerCache
    alias_to_player_id: AliasMap
    player_cache, alias_to_player_id = insert_players_sheet(conn, players_df)
    deck_cache: DeckCache = {}
    played_on_by_tournament: dict[str, str] = {}

    for _, row in tournaments_df.iterrows():
        tid: str = str(row["tournament_id"]).strip()
        if not tid:
            continue
        played_on: str = str(row["played_on"])[:10]
        played_on_by_tournament[tid] = played_on
        conn.execute(
            "INSERT INTO tournaments (id, name, played_on, format, venue) VALUES (?,?,?,?,?)",
            (tid, row["name"], played_on, row["format"], str(row["venue"]).strip() or None),
        )

    for _, row in games_df.iterrows():
        tid = str(row["tournament_id"]).strip()
        if not tid:
            continue

        player_1_name: str = str(row["player_1"]).strip()
        p1_id: int = resolve_player_id(conn, player_1_name, alias_to_player_id, player_cache)

        result: str = str(row["result"]).strip()
        if result.lower() == "bye":
            result = "bye"
        else:
            try:
                parse_wld(result)
            except ValueError as e:
                raise ValueError(f"Tournament '{tid}' round {row['round']}: {e}") from e

        p2_id: int | None
        if result == "bye":
            p2_id = None
        else:
            player_2_name: str = str(row["player_2"]).strip()
            p2_id = resolve_player_id(conn, player_2_name, alias_to_player_id, player_cache)

        conn.execute(
            "INSERT INTO matches (tournament_id, round_number, player_1_id, "
            "player_2_id, result) VALUES (?,?,?,?,?)",
            (tid, int(row["round"]), p1_id, p2_id, result),
        )

    format_by_tournament: dict[str, str] = {}
    for _, row in tournaments_df.iterrows():
        tid = str(row["tournament_id"]).strip()
        if tid:
            format_by_tournament[tid] = str(row["format"]).strip()

    standings_rows: list[tuple[int, Any]] = [
        (i, row) for i, (_, row) in enumerate(standings_df.iterrows())
        if str(row["tournament_id"]).strip()
    ]
    total_standings: int = len(standings_rows)

    for progress_idx, (_, row) in enumerate(standings_rows):
        tid = str(row["tournament_id"]).strip()
        played_on = played_on_by_tournament[tid]
        is_mtgo: bool = format_by_tournament.get(tid, "") == "MTGO"

        p_id: int = resolve_player_id(conn, row["player"], alias_to_player_id, player_cache)
        deck_id: int = get_or_create_deck(
            conn, row["deck_url"], row["archetype"], p_id, played_on,
            archetype_cache, deck_cache, warnings, is_mtgo=is_mtgo,
            fetch_fn=fetch_fn, snapshot_dir=snapshot_dir,
            context_label=f"tournament '{tid}', player '{row['player']}'",
        )

        if (progress_idx + 1) % 25 == 0 or progress_idx + 1 == total_standings:
            print(f"  standings: {progress_idx + 1}/{total_standings} processed")

        try:
            wins: int
            losses: int
            draws: int
            wins, losses, draws = parse_wld(row["score"])
        except ValueError as e:
            raise ValueError(
                f"Tournament '{tid}', player '{row['player']}': invalid score -- {e}"
            ) from e

        conn.execute(
            "INSERT INTO tournament_standings (tournament_id, player_id, deck_id, "
            "final_rank, wins, losses, draws) VALUES (?,?,?,?,?,?,?)",
            (tid, p_id, deck_id, int(row["final_rank"]), wins, losses, draws),
        )

    conn.commit()
    conn.close()

    if warnings:
        print("\nWARNINGS:")
        for w in warnings:
            print(" *", w)

    print(f"\nBuilt {db_path} from {source_label}")
    return warnings

def build(
    xlsx_path: Path = XLSX_PATH, db_path: Path = DB_PATH,
    fetch_fn: FetchFn = fetch_full_snapshot,
    snapshot_dir: Path = SNAPSHOT_DIR, confirm_fn: ConfirmFn = default_confirm,
) -> list[str]:

    if db_path == DB_PATH:
        ensure_db_extracted(db_path)
    sheets: SheetTuple = load_sheets(xlsx_path)
    return _build_from_dataframes(
        *sheets,
        db_path=db_path, fetch_fn=fetch_fn, snapshot_dir=snapshot_dir,
        confirm_fn=confirm_fn, source_label=str(xlsx_path),
    )

def build_single_tournament(
    tournament_id: str, xlsx_path: Path = XLSX_PATH,
    db_path: Path | None = None,
    fetch_fn: FetchFn = fetch_full_snapshot,
    snapshot_dir: Path = SNAPSHOT_DIR,
    confirm_fn: ConfirmFn = default_confirm,
) -> list[str]:
    """Build a standalone test database for one tournament only."""
    if db_path is None:
        db_path = XLSX_PATH.parent / f"mtg_data_test_{tournament_id}.db"

    tournaments_df: pd.DataFrame
    games_df: pd.DataFrame
    standings_df: pd.DataFrame
    players_df: pd.DataFrame
    archetypes_df: pd.DataFrame
    keyword_maps_df: pd.DataFrame
    tournaments_df, games_df, standings_df, players_df, archetypes_df, keyword_maps_df = load_sheets(xlsx_path)

    tournaments_df = tournaments_df[
        tournaments_df["tournament_id"].astype(str).str.strip() == tournament_id
    ]
    if tournaments_df.empty:
        raise ValueError(f"Tournament '{tournament_id}' not found in the Tournaments sheet.")

    games_df = games_df[games_df["tournament_id"].astype(str).str.strip() == tournament_id]
    standings_df = standings_df[standings_df["tournament_id"].astype(str).str.strip() == tournament_id]

    print(f"Testing tournament '{tournament_id}' only: "
          f"{len(games_df)} Games row(s), {len(standings_df)} Standings row(s).")

    return _build_from_dataframes(
        tournaments_df, games_df, standings_df, players_df, archetypes_df, keyword_maps_df,
        db_path=db_path, fetch_fn=fetch_fn, snapshot_dir=snapshot_dir,
        confirm_fn=confirm_fn, source_label=f"tournament '{tournament_id}' only",
    )

if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--tournament":
        build_single_tournament(sys.argv[2])
    else:
        build()
        