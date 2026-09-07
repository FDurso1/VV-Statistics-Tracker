
"""
Stats and aggregation queries.
"""

from __future__ import annotations
import random
import sqlite3
from datetime import date, timedelta
from typing import Any, Literal, TypedDict
from rapidfuzz import process, fuzz
from app.constants import BASIC_LAND_NAMES
from app.scoring import win_equivalent, loss_equivalent
from collections.abc import Mapping

BAYESIAN_K: int = 10
BAYESIAN_PRIOR: float = 0.5

# Type aliases
Row = sqlite3.Row
SearchResult = tuple[Row, float]
TrophyTier = Literal["bronze", "silver", "gold", "ZODIAC"]
SortOrder = Literal["date_desc", "date_asc", "record_desc", "record_asc"]

class WinLossDraw(TypedDict):
    wins: int
    losses: int
    draws: int

class WinLossDrawScore(WinLossDraw):
    score: float

class ArchetypePlayrate(TypedDict):
    deck_count: int
    total_decks: int
    share: float

class ArchetypeMatchup(TypedDict):
    opponent_id: int
    opponent_name: str
    wins: int
    losses: int
    draws: int

class PlayerDeckRecord(TypedDict):
    id: int
    moxfield_url: str | None
    deck_name: str | None
    archetype: str
    archetype_id: int
    wins: int
    losses: int
    draws: int

class LeaderboardEntry(TypedDict, total=False):
    rank: int  # always present
    id: int  # always present
    name: str  # always present
    is_public: bool  # always present
    wins: int  # public only
    losses: int  # public only
    draws: int  # public only
    score: float  # public only

class PodiumFinish(TypedDict):
    tournament_id: str
    tournament_name: str
    played_on: str
    final_rank: int
    undefeated: bool

class PioneerArchetype(TypedDict):
    id: int
    name: str

class LoyalArchetype(TypedDict):
    archetype_id: int
    archetype_name: str
    count: int
    tier: TrophyTier

class RoundRecordEntry(TypedDict):
    id: int
    name: str
    wins: float
    losses: float

class PriceHistoryPoint(TypedDict):
    date: str
    price: float

class CardPriceStats(TypedDict):
    current_price: float | None
    low: float | None
    high: float | None
    history: list[PriceHistoryPoint]
    has_data: bool

class ChartCard(CardPriceStats):
    name: str

class DeckSectionRow(TypedDict):
    name: str
    quantity: int
    current_price: float | None
    combined_price: float | None
    low: float | None
    high: float | None
    has_data: bool

class DeckVisualizerData(TypedDict):
    chart_cards: list[ChartCard]
    mainboard_cards: list[DeckSectionRow]
    sideboard_cards: list[DeckSectionRow]
    mainboard_total: float
    sideboard_total: float
    total_price: float
    missing_data_count: int

class UndefeatedPlacement(TypedDict):
    tournament_id: str
    player_id: int
    player_name: str
    archetype_id: int
    archetype_name: str
    moxfield_url: str | None

TrophyBadge = dict[str, Any]  # union of podium/first played/diversity/loyalty shapes

TROPHY_TIER_THRESHOLDS: list[tuple[int, TrophyTier]] = [
    (50, "ZODIAC"), (20, "gold"), (10, "silver"), (5, "bronze"),
]

ORDER_CLAUSES: dict[SortOrder, str] = {
    "date_desc": "t.played_on DESC",
    "date_asc": "t.played_on ASC",
    "record_desc": "ts.wins DESC, ts.losses ASC",
    "record_asc": "ts.wins ASC, ts.losses DESC",
}

def bayesian_score(wins: float, losses: float) -> float:
    """Bayesian-shrunk win rate, prior fixed at 0.5."""
    games: float = wins + losses
    return (wins + BAYESIAN_K * BAYESIAN_PRIOR) / (games + BAYESIAN_K)

# ---------- search ----------

def search_players(conn: sqlite3.Connection, query: str, limit: int = 5, score_cutoff: int = 60) -> list[SearchResult]:
    """Fuzzy-match against public players only."""
    
    rows: list[Row] = conn.execute(
        "SELECT id, name FROM players WHERE is_public = 1"
    ).fetchall()
    names: dict[str, Row] = {row["name"]: row for row in rows}
    matches = process.extract(
        query, names.keys(), scorer=fuzz.WRatio, limit=limit, score_cutoff=score_cutoff
    )
    return [(names[name], score) for name, score, _ in matches]

# ---------- players ----------

def get_player(conn: sqlite3.Connection, player_id: int) -> Row | None:
    return conn.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()

def list_players(conn: sqlite3.Connection) -> list[Row]:
    return conn.execute("SELECT * FROM players ORDER BY name").fetchall()

def player_record(conn: sqlite3.Connection, player_id: int) -> WinLossDraw:
    """Overall W/L/D across all tournaments from tournament_standings."""
    row: Row = conn.execute(
        "SELECT SUM(wins) AS wins, SUM(losses) AS losses, SUM(draws) AS draws "
        "FROM tournament_standings WHERE player_id = ?",
        (player_id,),
    ).fetchone()
    return {
        "wins": int(row["wins"] or 0),
        "losses": int(row["losses"] or 0),
        "draws": int(row["draws"] or 0),
    }

def player_decks(conn: sqlite3.Connection, player_id: int) -> list[PlayerDeckRecord]:
    """Every deck this player has piloted, with per-deck W/L/D."""
    deck_ids: list[Row] = conn.execute(
        "SELECT DISTINCT deck_id FROM tournament_standings WHERE player_id = ?",
        (player_id,),
    ).fetchall()

    decks: list[PlayerDeckRecord] = []
    for (deck_id,) in deck_ids:
        deck: Row = conn.execute(
            """
            SELECT decks.id, decks.moxfield_url, decks.name AS deck_name,
                   archetypes.name AS archetype, archetypes.id AS archetype_id
            FROM decks JOIN archetypes ON decks.archetype_id = archetypes.id
            WHERE decks.id = ?
            """,
            (deck_id,),
        ).fetchone()
        record: Row = conn.execute(
            "SELECT SUM(wins) AS wins, SUM(losses) AS losses, SUM(draws) AS draws "
            "FROM tournament_standings WHERE player_id = ? AND deck_id = ?",
            (player_id, deck_id),
        ).fetchone()
        decks.append({
            "id": int(deck["id"]),
            "moxfield_url": deck["moxfield_url"],
            "deck_name": deck["deck_name"],
            "archetype": str(deck["archetype"]),
            "archetype_id": int(deck["archetype_id"]),
            "wins": int(record["wins"] or 0),
            "losses": int(record["losses"] or 0),
            "draws": int(record["draws"] or 0),
        })
    return decks

def player_tournament_wins(conn: sqlite3.Connection, player_id: int) -> list[Row]:
    """Tournaments where this player placed 1st."""
    return conn.execute(
        """
        SELECT tournaments.id, tournaments.name, tournaments.played_on, tournaments.format
        FROM tournament_standings
        JOIN tournaments ON tournaments.id = tournament_standings.tournament_id
        WHERE tournament_standings.player_id = ? AND tournament_standings.final_rank = 1
        ORDER BY tournaments.played_on DESC
        """,
        (player_id,),
    ).fetchall()

def player_leaderboard(conn: sqlite3.Connection) -> list[LeaderboardEntry]:
    """All players ranked by Bayesian win rate. Private players show rank and name only."""
    rows: list[Row] = conn.execute(
        """
        SELECT p.id, p.name, p.is_public,
          SUM(ts.wins) AS wins, SUM(ts.losses) AS losses, SUM(ts.draws) AS draws
        FROM players p
        LEFT JOIN tournament_standings ts ON ts.player_id = p.id
        GROUP BY p.id
        """
    ).fetchall()

    scored: list[dict[str, Any]] = []
    for row in rows:
        wins: int = int(row["wins"] or 0)
        losses: int = int(row["losses"] or 0)
        draws: int = int(row["draws"] or 0)
        score: float = bayesian_score(
            win_equivalent(wins, losses, draws),
            loss_equivalent(wins, losses, draws),
        )
        scored.append({
            "id": int(row["id"]), "name": str(row["name"]),
            "is_public": bool(row["is_public"]),
            "wins": wins, "losses": losses, "draws": draws, "score": score,
        })
    scored.sort(key=lambda p: (-p["score"], p["name"]))

    leaderboard: list[LeaderboardEntry] = []
    for rank, p in enumerate(scored, start=1):
        entry: LeaderboardEntry = {
            "rank": rank, "id": p["id"], "name": p["name"], "is_public": p["is_public"],
        }
        if p["is_public"]:
            entry["wins"] = p["wins"]
            entry["losses"] = p["losses"]
            entry["draws"] = p["draws"]
            entry["score"] = p["score"]
        leaderboard.append(entry)
    return leaderboard

def player_rank(conn: sqlite3.Connection, player_id: int) -> LeaderboardEntry | None:
    """Single player's leaderboard entry."""
    for entry in player_leaderboard(conn):
        if entry["id"] == player_id: #type: ignore
            return entry
    return None

# ---------- archetypes ----------

def search_archetypes(conn: sqlite3.Connection, query: str, limit: int = 5, score_cutoff: int = 60) -> list[SearchResult]:

    rows: list[Row] = conn.execute("SELECT id, name FROM archetypes").fetchall()
    names: dict[str, Row] = {row["name"]: row for row in rows}
    matches = process.extract(
        query, names.keys(), scorer=fuzz.WRatio, limit=limit, score_cutoff=score_cutoff
    )
    return [(names[name], score) for name, score, _ in matches]

def get_archetype(conn: sqlite3.Connection, archetype_id: int) -> Row | None:
    return conn.execute("SELECT * FROM archetypes WHERE id = ?", (archetype_id,)).fetchone()

def list_archetypes(conn: sqlite3.Connection) -> list[Row]:
    return conn.execute("SELECT * FROM archetypes ORDER BY name").fetchall()

def archetype_playrate(conn: sqlite3.Connection, archetype_id: int) -> ArchetypePlayrate:
    """Share of all recorded decks that are this archetype."""
    
    deck_count: int = int(conn.execute(
        "SELECT COUNT(*) FROM decks WHERE archetype_id = ?", (archetype_id,)
    ).fetchone()[0])
    total_decks: int = int(conn.execute(
        "SELECT COUNT(*) FROM decks"
    ).fetchone()[0])
    if total_decks:
        share: float = (deck_count / total_decks)
    else:
        share = 0.0
    return {"deck_count": deck_count, "total_decks": total_decks, "share": share}

def archetype_winrate(conn: sqlite3.Connection, archetype_id: int) -> WinLossDraw:

    row: Row = conn.execute(
        """
        SELECT SUM(ts.wins) AS wins, SUM(ts.losses) AS losses, SUM(ts.draws) AS draws
        FROM tournament_standings ts
        JOIN decks d ON d.id = ts.deck_id
        WHERE d.archetype_id = ?
        """,
        (archetype_id,),
    ).fetchone()
    return {
        "wins": int(row["wins"] or 0),
        "losses": int(row["losses"] or 0),
        "draws": int(row["draws"] or 0),
    }

def archetype_matchups(conn: sqlite3.Connection, archetype_id: int) -> list[ArchetypeMatchup]:

    rows: list[Row] = conn.execute(
        """
        SELECT m.result, 1 AS side, d2.archetype_id AS opp_archetype_id
        FROM matches m
        JOIN tournament_standings ts1 ON ts1.tournament_id = m.tournament_id AND ts1.player_id = m.player_1_id
        JOIN decks d1 ON d1.id = ts1.deck_id
        LEFT JOIN tournament_standings ts2 ON ts2.tournament_id = m.tournament_id AND ts2.player_id = m.player_2_id
        LEFT JOIN decks d2 ON d2.id = ts2.deck_id
        WHERE d1.archetype_id = :aid AND d2.archetype_id IS NOT NULL AND d2.archetype_id != :aid
        UNION ALL
        SELECT m.result, 2 AS side, d1.archetype_id AS opp_archetype_id
        FROM matches m
        JOIN tournament_standings ts2 ON ts2.tournament_id = m.tournament_id AND ts2.player_id = m.player_2_id
        JOIN decks d2 ON d2.id = ts2.deck_id
        JOIN tournament_standings ts1 ON ts1.tournament_id = m.tournament_id AND ts1.player_id = m.player_1_id
        JOIN decks d1 ON d1.id = ts1.deck_id
        WHERE d2.archetype_id = :aid AND d1.archetype_id != :aid
        """,
        {"aid": archetype_id},
    ).fetchall()

    totals: dict[int, list[int]] = {}  # opp_id -> [wins, losses, draws]
    for row in rows:
        result_str: str = row["result"]
        if result_str.lower() == "bye":
            continue
        parts: list[str] = result_str.split("-")
        p1_wins: int = int(parts[0])
        p1_losses: int = int(parts[1])
        p1_draws: int = int(parts[2]) if len(parts) > 2 else 0

        if row["side"] == 1:
            my_w, my_l, my_d = p1_wins, p1_losses, p1_draws
        else:
            my_w, my_l, my_d = p1_losses, p1_wins, p1_draws

        agg: list[int] = totals.setdefault(row["opp_archetype_id"], [0, 0, 0])
        agg[0] += my_w
        agg[1] += my_l
        agg[2] += my_d

    result: list[ArchetypeMatchup] = []
    for opp_id, (wins, losses, draws) in totals.items():
        opp: Row = conn.execute(
            "SELECT name FROM archetypes WHERE id = ?", (opp_id,)
        ).fetchone()
        result.append({
            "opponent_id": opp_id, "opponent_name": str(opp["name"]),
            "wins": wins, "losses": losses, "draws": draws,
        })
    result.sort(key=lambda r: -(r["wins"] + r["losses"] + r["draws"]))
    return result

def archetype_top_players(conn: sqlite3.Connection, archetype_id: int, limit: int = 10) -> list[dict[str, Any]]:
    """Public players ranked by Bayesian win rate with this archetype."""
    
    rows: list[Row] = conn.execute(
        """
        SELECT p.id, p.name,
          SUM(ts.wins) AS wins, SUM(ts.losses) AS losses, SUM(ts.draws) AS draws
        FROM tournament_standings ts
        JOIN decks d ON d.id = ts.deck_id
        JOIN players p ON p.id = ts.player_id
        WHERE d.archetype_id = :aid AND p.is_public = 1
        GROUP BY p.id
        """,
        {"aid": archetype_id},
    ).fetchall()

    scored: list[dict[str, Any]] = []
    for row in rows:
        wins: int = int(row["wins"] or 0)
        losses: int = int(row["losses"] or 0)
        draws: int = int(row["draws"] or 0)
        score: float = bayesian_score(
            win_equivalent(wins, losses, draws),
            loss_equivalent(wins, losses, draws),
        )
        scored.append({
            "id": int(row["id"]), "name": str(row["name"]),
            "wins": wins, "losses": losses, "draws": draws, "score": score,
        })
    scored.sort(key=lambda p: (-p["score"], p["name"]))
    return scored[:limit]

# ---------- cards ----------

def search_cards(conn: sqlite3.Connection, query: str, limit: int = 5, score_cutoff: int = 60) -> list[SearchResult]:
    """Fuzzy-match against tournament-seen card names.""" # maybe all card names? probably just seen ones
    rows: list[Row] = conn.execute("SELECT id, name FROM cards").fetchall()
    names: dict[str, Row] = {row["name"]: row for row in rows}
    matches = process.extract(
        query, names.keys(), scorer=fuzz.WRatio, limit=limit, score_cutoff=score_cutoff
    )
    return [(names[name], score) for name, score, _ in matches]

def get_card(conn: sqlite3.Connection, card_id: int) -> Row | None:
    return conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()

def get_card_by_name(conn: sqlite3.Connection, card_name: str) -> Row | None:
    """Returns the cards-table row if tournament-seen, else None."""
    return conn.execute("SELECT * FROM cards WHERE name = ?", (card_name,)).fetchone()

def list_cards(conn: sqlite3.Connection) -> list[Row]:
    return conn.execute("SELECT * FROM cards ORDER BY name").fetchall()

def card_popularity(conn: sqlite3.Connection, card_id: int) -> list[Row]:
    """Which archetypes run this card, by card_id."""
    
    return conn.execute(
        """
        SELECT archetypes.id, archetypes.name,
               COUNT(DISTINCT deck_cards.deck_id) AS deck_count,
               AVG(deck_cards.quantity) AS avg_quantity
        FROM deck_cards
        JOIN decks ON decks.id = deck_cards.deck_id
        JOIN archetypes ON archetypes.id = decks.archetype_id
        WHERE deck_cards.card_id = ?
        GROUP BY archetypes.id
        ORDER BY deck_count DESC
        """,
        (card_id,),
    ).fetchall()

def card_winrate(conn: sqlite3.Connection, card_id: int) -> WinLossDrawScore:
    """W/L/D for decks containing this card, by card_id."""
    
    row: Row = conn.execute(
        """
        SELECT SUM(ts.wins) AS wins, SUM(ts.losses) AS losses, SUM(ts.draws) AS draws
        FROM tournament_standings ts
        WHERE ts.deck_id IN (SELECT deck_id FROM deck_cards WHERE card_id = ?)
        """,
        (card_id,),
    ).fetchone()
    wins: int = int(row["wins"] or 0)
    losses: int = int(row["losses"] or 0)
    draws: int = int(row["draws"] or 0)
    score: float = bayesian_score(
        win_equivalent(wins, losses, draws),
        loss_equivalent(wins, losses, draws),
    )
    return {"wins": wins, "losses": losses, "draws": draws, "score": score}

def card_price_history(conn: sqlite3.Connection, card_id: int) -> list[Row]:
    
    card: Row | None = conn.execute(
        "SELECT name FROM cards WHERE id = ?", (card_id,)
    ).fetchone()
    if card is None:
        return []
    return conn.execute(
        "SELECT price_date, price FROM card_price_cache "
        "WHERE card_name = ? ORDER BY price_date",
        (card["name"],),
    ).fetchall()

def card_price_history_by_name(conn: sqlite3.Connection, card_name: str) -> list[Row]:

    return conn.execute(
        "SELECT price_date, price FROM card_price_cache "
        "WHERE card_name = ? ORDER BY price_date",
        (card_name,),
    ).fetchall()

def card_popularity_by_name(conn: sqlite3.Connection, card_name: str) -> list[Row]:

    return conn.execute(
        """
        SELECT archetypes.id, archetypes.name,
               COUNT(DISTINCT deck_cards.deck_id) AS deck_count,
               AVG(deck_cards.quantity) AS avg_quantity,
               AVG(deck_cards.mainboard_quantity) AS avg_mainboard,
               AVG(deck_cards.sideboard_quantity) AS avg_sideboard
        FROM deck_cards
        JOIN cards ON cards.id = deck_cards.card_id
        JOIN decks ON decks.id = deck_cards.deck_id
        JOIN archetypes ON archetypes.id = decks.archetype_id
        WHERE cards.name = ?
        GROUP BY archetypes.id
        ORDER BY deck_count DESC
        """,
        (card_name,),
    ).fetchall()

def card_winrate_by_name(conn: sqlite3.Connection, card_name: str) -> WinLossDrawScore:

    row: Row = conn.execute(
        """
        SELECT SUM(ts.wins) AS wins, SUM(ts.losses) AS losses, SUM(ts.draws) AS draws
        FROM tournament_standings ts
        WHERE ts.deck_id IN (
            SELECT dc.deck_id FROM deck_cards dc
            JOIN cards c ON c.id = dc.card_id
            WHERE c.name = ?
        )
        """,
        (card_name,),
    ).fetchone()
    wins: int = int(row["wins"] or 0)
    losses: int = int(row["losses"] or 0)
    draws: int = int(row["draws"] or 0)
    score: float = bayesian_score(
        win_equivalent(wins, losses, draws),
        loss_equivalent(wins, losses, draws),
    )
    return {"wins": wins, "losses": losses, "draws": draws, "score": score}

def random_card_name(conn: sqlite3.Connection) -> str | None:
    """Random card name from tournament-seen cards."""
    
    names: list[str] = [r[0] for r in conn.execute("SELECT name FROM cards")]
    return random.choice(names) if names else None

# ---------- tournaments ----------

def search_tournaments(conn: sqlite3.Connection, query: str, limit: int = 5, score_cutoff: int = 60) -> list[SearchResult]:
    # kinda useless rn given naming structure, but will be important once paper tournaments added
    
    rows: list[Row] = conn.execute("SELECT id, name FROM tournaments").fetchall()
    names: dict[str, Row] = {row["name"]: row for row in rows}
    matches = process.extract(
        query, names.keys(), scorer=fuzz.WRatio, limit=limit, score_cutoff=score_cutoff
    )
    return [(names[name], score) for name, score, _ in matches]

def list_tournaments(
    conn: sqlite3.Connection,
    format: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[Row]:
    """Filterable tournament list."""
    
    sql: str = "SELECT * FROM tournaments WHERE 1=1"
    params: list[str] = []
    if format:
        sql += " AND format = ?"
        params.append(format)
    if date_from:
        sql += " AND played_on >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND played_on <= ?"
        params.append(date_to)
    sql += " ORDER BY played_on DESC"
    return conn.execute(sql, params).fetchall()

def get_tournament(conn: sqlite3.Connection, tournament_id: str) -> Row | None:
    return conn.execute("SELECT * FROM tournaments WHERE id = ?", (tournament_id,)).fetchone()

def tournament_round_results(conn: sqlite3.Connection, tournament_id: str) -> list[Row]:
    """Per-round matchups. Byes show NULL for player_2/archetype_2."""
    
    return conn.execute(
        """
        SELECT m.round_number, m.result,
               p1.name AS player_1, a1.name AS archetype_1,
               p2.name AS player_2, a2.name AS archetype_2
        FROM matches m
        JOIN players p1 ON p1.id = m.player_1_id
        JOIN tournament_standings ts1 ON ts1.tournament_id = m.tournament_id AND ts1.player_id = m.player_1_id
        JOIN decks d1 ON d1.id = ts1.deck_id
        JOIN archetypes a1 ON a1.id = d1.archetype_id
        LEFT JOIN players p2 ON p2.id = m.player_2_id
        LEFT JOIN tournament_standings ts2 ON ts2.tournament_id = m.tournament_id AND ts2.player_id = m.player_2_id
        LEFT JOIN decks d2 ON d2.id = ts2.deck_id
        LEFT JOIN archetypes a2 ON a2.id = d2.archetype_id
        WHERE m.tournament_id = ?
        ORDER BY m.round_number, p1.name
        """,
        (tournament_id,),
    ).fetchall()

def tournament_final_standings(conn: sqlite3.Connection, tournament_id: str) -> list[Row]:
    """Final rankings"""
    
    return conn.execute(
        """
        SELECT ts.final_rank, ts.wins, ts.losses, ts.draws,
               p.id AS player_id, p.name AS player_name,
               a.id AS archetype_id, a.name AS archetype
        FROM tournament_standings ts
        JOIN players p ON p.id = ts.player_id
        JOIN decks d ON d.id = ts.deck_id
        JOIN archetypes a ON a.id = d.archetype_id
        WHERE ts.tournament_id = ?
        ORDER BY ts.final_rank
        """,
        (tournament_id,),
    ).fetchall()

# ---------- deck visualizer ----------

def deck_visualizer_data(conn: sqlite3.Connection, card_info: Mapping[str, Mapping[str, Any]], days: int) -> DeckVisualizerData:
    """Build chart and table data for the deck visualizer."""
    
    names: list[str] = list(card_info.keys())
    if not names:
        return {
            "chart_cards": [], "mainboard_cards": [], "sideboard_cards": [],
            "mainboard_total": 0.0, "sideboard_total": 0.0, "total_price": 0.0,
            "missing_data_count": 0,
        }

    non_basic_names: list[str] = [n for n in names if n not in BASIC_LAND_NAMES]
    full_history_by_name: dict[str, list[PriceHistoryPoint]] = {}
    if non_basic_names:
        placeholders: str = ",".join("?" * len(non_basic_names))
        rows: list[Row] = conn.execute(
            f"SELECT card_name, price_date, price FROM card_price_cache "
            f"WHERE card_name IN ({placeholders}) ORDER BY card_name, price_date",
            non_basic_names,
        ).fetchall()
        for row in rows:
            full_history_by_name.setdefault(row["card_name"], []).append(
                {"date": row["price_date"], "price": float(row["price"])}
            )

    cutoff: str = (date.today() - timedelta(days=days - 1)).isoformat()

    stats_by_name: dict[str, CardPriceStats] = {}
    missing_data_count: int = 0
    for name in names:
        if name in BASIC_LAND_NAMES:
            stats_by_name[name] = {
                "current_price": 0.0, "low": 0.0, "high": 0.0,
                "history": [], "has_data": True,
            }
            continue

        full_history: list[PriceHistoryPoint] = full_history_by_name.get(name, [])
        window_history: list[PriceHistoryPoint] = [
            h for h in full_history if h["date"] >= cutoff
        ]

        current_price: float | None
        has_data: bool
        if full_history:
            current_price = full_history[-1]["price"]
            has_data = True
        else:
            current_price = None
            has_data = False
            missing_data_count += 1

        low: float | None
        high: float | None
        if window_history:
            prices: list[float] = [h["price"] for h in window_history]
            low, high = min(prices), max(prices)
        else:
            low = high = None

        stats_by_name[name] = {
            "current_price": current_price, "low": low, "high": high,
            "history": window_history, "has_data": has_data,
        }

    chart_cards: list[ChartCard] = [
        {"name": name, **stats_by_name[name]}  # type: ignore[typeddict-item]
        for name in names if name not in BASIC_LAND_NAMES
    ]
    chart_cards.sort(key=lambda c: c["name"])

    def build_section(
        board_quantity_key: str,
    ) -> tuple[list[DeckSectionRow], float]:
        section_rows: list[DeckSectionRow] = []
        section_total: float = 0.0
        for name, info in card_info.items():
            qty: int = info.get(board_quantity_key, 0)
            if qty <= 0:
                continue
            s: CardPriceStats = stats_by_name[name]
            combined_price: float | None = (
                (s["current_price"] * qty) if s["has_data"] and s["current_price"] is not None else None
            )
            if combined_price is not None:
                section_total += combined_price
            section_rows.append({
                "name": name, "quantity": qty,
                "current_price": s["current_price"],
                "combined_price": combined_price,
                "low": s["low"], "high": s["high"],
                "has_data": s["has_data"],
            })
        section_rows.sort(key=lambda c: c["name"])
        return section_rows, section_total

    mainboard_cards, mainboard_total = build_section("mainboard_quantity")
    sideboard_cards, sideboard_total = build_section("sideboard_quantity")

    return {
        "chart_cards": chart_cards,
        "mainboard_cards": mainboard_cards,
        "sideboard_cards": sideboard_cards,
        "mainboard_total": mainboard_total,
        "sideboard_total": sideboard_total,
        "total_price": mainboard_total + sideboard_total,
        "missing_data_count": missing_data_count,
    }

# ---------- random / archetype home helpers ----------

def random_archetype_id(conn: sqlite3.Connection) -> int | None:
    ids: list[int] = [r[0] for r in conn.execute("SELECT id FROM archetypes")]
    if ids:
        return random.choice(ids)
    else:
        return None

def recent_undefeated_placements(
    conn: sqlite3.Connection,
    archetype_id: int | None = None,
    limit: int = 3,
) -> list[UndefeatedPlacement]:

    tournaments: list[Row] = conn.execute(
        "SELECT id FROM tournaments ORDER BY played_on DESC"
    ).fetchall()
    results: list[UndefeatedPlacement] = []
    for (tid,) in tournaments:
        standings: list[Row] = conn.execute(
            """
            SELECT ts.final_rank, ts.losses, p.id AS player_id, p.name AS player_name,
                   d.moxfield_url, a.id AS archetype_id, a.name AS archetype_name
            FROM tournament_standings ts
            JOIN players p ON p.id = ts.player_id
            JOIN decks d ON d.id = ts.deck_id
            JOIN archetypes a ON a.id = d.archetype_id
            WHERE ts.tournament_id = ?
            ORDER BY ts.final_rank
            """,
            (tid,),
        ).fetchall()
        for row in standings:
            if row["losses"] > 0:
                break
            if archetype_id is not None and row["archetype_id"] != archetype_id:
                continue
            results.append({
                "tournament_id": tid,
                "player_id": int(row["player_id"]),
                "player_name": str(row["player_name"]),
                "archetype_id": int(row["archetype_id"]),
                "archetype_name": str(row["archetype_name"]),
                "moxfield_url": row["moxfield_url"],
            })
            if len(results) >= limit:
                return results
    return results

def archetype_recent_results(
    conn: sqlite3.Connection,
    archetype_id: int,
    limit: int = 15,
    offset: int = 0,
) -> list[Row]:

    return conn.execute(
        """
        SELECT t.id AS tournament_id, t.name AS tournament_name, t.played_on,
               p.id AS player_id, p.name AS player_name,
               d.moxfield_url, ts.final_rank, ts.wins, ts.losses, ts.draws
        FROM tournament_standings ts
        JOIN tournaments t ON t.id = ts.tournament_id
        JOIN players p ON p.id = ts.player_id
        JOIN decks d ON d.id = ts.deck_id
        WHERE d.archetype_id = ?
        ORDER BY t.played_on DESC, ts.final_rank ASC
        LIMIT ? OFFSET ?
        """,
        (archetype_id, limit, offset),
    ).fetchall()

def archetype_card_stats(
    conn: sqlite3.Connection,
    archetype_id: int,
    recent_only: bool = False,
    recency_days: int = 90,
) -> list[Row]:

    if recent_only:
        cutoff: str = (date.today() - timedelta(days=recency_days)).isoformat()
        deck_id_rows: list[Row] = conn.execute(
            """
            SELECT DISTINCT d.id FROM decks d
            JOIN tournament_standings ts ON ts.deck_id = d.id
            JOIN tournaments t ON t.id = ts.tournament_id
            WHERE d.archetype_id = ? AND t.played_on >= ?
            """,
            (archetype_id, cutoff),
        ).fetchall()
        deck_ids: list[int] = [r[0] for r in deck_id_rows]
        if not deck_ids:
            return []
        placeholders: str = ",".join("?" * len(deck_ids))
        return conn.execute(
            f"""
            SELECT c.name, COUNT(DISTINCT dc.deck_id) AS deck_count, AVG(dc.quantity) AS avg_quantity,
                   AVG(dc.mainboard_quantity) AS avg_mainboard, AVG(dc.sideboard_quantity) AS avg_sideboard
            FROM deck_cards dc JOIN cards c ON c.id = dc.card_id
            WHERE dc.deck_id IN ({placeholders})
            GROUP BY c.id ORDER BY deck_count DESC
            """,
            deck_ids,
        ).fetchall()

    return conn.execute(
        """
        SELECT c.name, COUNT(DISTINCT dc.deck_id) AS deck_count, AVG(dc.quantity) AS avg_quantity,
               AVG(dc.mainboard_quantity) AS avg_mainboard, AVG(dc.sideboard_quantity) AS avg_sideboard
        FROM deck_cards dc
        JOIN cards c ON c.id = dc.card_id
        JOIN decks d ON d.id = dc.deck_id
        WHERE d.archetype_id = ?
        GROUP BY c.id ORDER BY deck_count DESC
        """,
        (archetype_id,),
    ).fetchall()

# ---------- player trophy case ----------

def _tier_for_count(count: int) -> TrophyTier | None:

    for threshold, tier in TROPHY_TIER_THRESHOLDS:
        if count >= threshold:
            return tier
    return None

def _podium_finishes(conn: sqlite3.Connection, player_id: int) -> list[PodiumFinish]:

    rows: list[Row] = conn.execute(
        """
        SELECT ts.final_rank, ts.losses, t.id AS tournament_id,
               t.name AS tournament_name, t.played_on
        FROM tournament_standings ts
        JOIN tournaments t ON t.id = ts.tournament_id
        WHERE ts.player_id = ? AND ts.final_rank <= 3
        ORDER BY t.played_on DESC
        """,
        (player_id,),
    ).fetchall()
    return [
        {
            "tournament_id": str(r["tournament_id"]),
            "tournament_name": str(r["tournament_name"]),
            "played_on": str(r["played_on"]),
            "final_rank": int(r["final_rank"]),
            "undefeated": r["losses"] == 0,
        }
        for r in rows
    ]

def _pioneer_archetypes(conn: sqlite3.Connection, player_id: int) -> list[PioneerArchetype]:

    rows: list[Row] = conn.execute(
        """
        SELECT a.id, a.name FROM archetypes a
        JOIN decks d ON d.id = (
            SELECT id FROM decks WHERE archetype_id = a.id
            ORDER BY date_added ASC, id ASC LIMIT 1
        )
        WHERE d.player_id = ? AND a.unclaimable = 0
        """, # unclaimable ones are ones that are too broad to really be awarded to one player
        (player_id,),
    ).fetchall()
    return [{"id": int(r["id"]), "name": str(r["name"])} for r in rows]

def _distinct_archetypes_played(conn: sqlite3.Connection, player_id: int) -> int:
    return int(conn.execute(
        "SELECT COUNT(DISTINCT archetype_id) FROM decks WHERE player_id = ?",
        (player_id,),
    ).fetchone()[0])


def _archetype_loyalty_entries(conn: sqlite3.Connection, player_id: int) -> list[Row]:

    return conn.execute(
        """
        SELECT a.id AS archetype_id, a.name AS archetype_name, COUNT(*) AS cnt
        FROM tournament_standings ts
        JOIN decks d ON d.id = ts.deck_id
        JOIN archetypes a ON a.id = d.archetype_id
        WHERE ts.player_id = ?
        GROUP BY d.archetype_id
        ORDER BY cnt DESC
        """,
        (player_id,),
    ).fetchall()

def player_trophy_case(conn: sqlite3.Connection, player_id: int) -> list[TrophyBadge]:

    badges: list[TrophyBadge] = []

    podium: list[PodiumFinish] = _podium_finishes(conn, player_id)
    if podium:
        badges.append({"type": "podium", "finishes": podium})

    pioneer: list[PioneerArchetype] = _pioneer_archetypes(conn, player_id)
    if pioneer:
        badges.append({"type": "pioneer", "archetypes": pioneer})

    diversity_count: int = _distinct_archetypes_played(conn, player_id)
    diversity_tier: TrophyTier | None = _tier_for_count(diversity_count)
    if diversity_tier:
        badges.append({
            "type": "diversity", "tier": diversity_tier, "count": diversity_count,
        })

    loyalty_entries: list[Row] = _archetype_loyalty_entries(conn, player_id)
    loyal_archetypes: list[LoyalArchetype] = []
    for entry in loyalty_entries:
        tier: TrophyTier | None = _tier_for_count(int(entry["cnt"]))
        if tier:
            loyal_archetypes.append({
                "archetype_id": int(entry["archetype_id"]),
                "archetype_name": str(entry["archetype_name"]),
                "count": int(entry["cnt"]),
                "tier": tier,
            })
    if loyal_archetypes:
        badges.append({"type": "loyalty", "archetypes": loyal_archetypes})

    return badges

# ---------- cards home: hottest cards ----------

def top_cards_by_recent_tournaments(conn: sqlite3.Connection, tournament_count: int = 3, limit: int = 5) -> list[Row]:

    recent_tids: list[Row] = conn.execute(
        "SELECT id FROM tournaments ORDER BY played_on DESC LIMIT ?",
        (tournament_count,),
    ).fetchall()
    if not recent_tids:
        return []
    tid_list: list[str] = [r[0] for r in recent_tids]
    placeholders: str = ",".join("?" * len(tid_list))
    basic_placeholders: str = ",".join("?" * len(BASIC_LAND_NAMES))
    return conn.execute(
        f"""
        SELECT c.id, c.name, COUNT(DISTINCT dc.deck_id) AS deck_count
        FROM deck_cards dc
        JOIN cards c ON c.id = dc.card_id
        JOIN decks d ON d.id = dc.deck_id
        JOIN tournament_standings ts ON ts.deck_id = d.id
        WHERE ts.tournament_id IN ({placeholders})
          AND c.name NOT IN ({basic_placeholders})
        GROUP BY c.id
        ORDER BY deck_count DESC
        LIMIT ?
        """,
        tid_list + list(BASIC_LAND_NAMES) + [limit],
    ).fetchall()

def random_card_id(conn: sqlite3.Connection) -> int | None:

    ids: list[int] = [r[0] for r in conn.execute("SELECT id FROM cards")]
    return random.choice(ids) if ids else None

# ---------- player page: tournament history + archetype stats ----------

def player_tournament_history(
    conn: sqlite3.Connection,
    player_id: int,
    sort: SortOrder = "date_desc",
) -> list[Row]:

    order: str = ORDER_CLAUSES.get(sort, ORDER_CLAUSES["date_desc"])
    return conn.execute(
        f"""
        SELECT t.id AS tournament_id, t.name AS tournament_name, t.played_on, t.format,
               ts.final_rank, ts.wins, ts.losses, ts.draws,
               a.id AS archetype_id, a.name AS archetype, d.moxfield_url, d.name AS deck_name
        FROM tournament_standings ts
        JOIN tournaments t ON t.id = ts.tournament_id
        JOIN decks d ON d.id = ts.deck_id
        JOIN archetypes a ON a.id = d.archetype_id
        WHERE ts.player_id = ?
        ORDER BY {order}
        """,
        (player_id,),
    ).fetchall()

def player_archetype_stats(conn: sqlite3.Connection, player_id: int) -> list[Row]:

    return conn.execute(
        """
        SELECT a.id AS archetype_id, a.name AS archetype_name,
               SUM(ts.wins) AS wins, SUM(ts.losses) AS losses, SUM(ts.draws) AS draws,
               COUNT(*) AS tournaments_played
        FROM tournament_standings ts
        JOIN decks d ON d.id = ts.deck_id
        JOIN archetypes a ON a.id = d.archetype_id
        WHERE ts.player_id = ?
        GROUP BY a.id
        ORDER BY COUNT(*) DESC
        """,
        (player_id,),
    ).fetchall()
    