
from __future__ import annotations

import json
import re
import sqlite3

from flask import Blueprint, render_template, request, abort, redirect, url_for
from werkzeug.wrappers import Response
from datetime import date, timedelta

from app.db import get_db
from app import queries
from app.moxfield import fetch_deck, DeckResult
from typing import Any
from app.moxfield import extract_deck_id

bp: Blueprint = Blueprint("main", __name__)

def _normalize_card_query(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower())

@bp.route("/")
def index() -> str:
    db: sqlite3.Connection = get_db()
    tournament_count: int = db.execute(
        "SELECT COUNT(*) FROM tournaments"
    ).fetchone()[0]
    db.close()
    return render_template("index.html", tournament_count=tournament_count)

@bp.route("/players")
def players_index() -> str:
    """Leaderboard with optional hide-private toggle."""
    
    q: str = request.args.get("q", "").strip()
    hide_private: bool = request.args.get("hide_private") == "1"
    db: sqlite3.Connection = get_db()
    if q:
        matches: list[queries.SearchResult] = queries.search_players(db, q)
        results: list[sqlite3.Row] = [row for row, _ in matches]
        db.close()
        return render_template(
            "players.html", players=results, query=q,
            leaderboard=None, hide_private=hide_private,
        )
    else:
        leaderboard: list[queries.LeaderboardEntry] = queries.player_leaderboard(db)
        db.close()
        return render_template(
            "players.html", players=None, query=q,
            leaderboard=leaderboard, hide_private=hide_private,
        )

@bp.route("/players/<int:player_id>")
def player_detail(player_id: int) -> str:
    db: sqlite3.Connection = get_db()
    player: sqlite3.Row | None = queries.get_player(db, player_id)
    if player is None:
        db.close()
        abort(404)

    rank_entry: queries.LeaderboardEntry | None = queries.player_rank(db, player_id)
    record: queries.WinLossDraw | None = None
    tournament_wins: list[sqlite3.Row] | None = None
    trophy_case: list[queries.TrophyBadge] | None = None
    tournament_history: list[sqlite3.Row] | None = None
    archetype_stats: list[sqlite3.Row] | None = None

    if player["is_public"]:
        record = queries.player_record(db, player_id)
        tournament_wins = queries.player_tournament_wins(db, player_id)
        trophy_case = queries.player_trophy_case(db, player_id)
        tournament_history = queries.player_tournament_history(db, player_id)
        archetype_stats = queries.player_archetype_stats(db, player_id)
    db.close()

    return render_template(
        "player_detail.html",
        player=player,
        rank_entry=rank_entry,
        record=record,
        tournament_wins=tournament_wins,
        trophy_case=trophy_case,
        tournament_history=tournament_history,
        archetype_stats=archetype_stats,
    )

@bp.route("/archetypes")
def archetypes_index() -> str:
    q: str = request.args.get("q", "").strip()
    db: sqlite3.Connection = get_db()
    if q:
        results: list[sqlite3.Row] = [
            row for row, _ in queries.search_archetypes(db, q)
        ]
        db.close()
        return render_template(
            "archetypes.html", archetypes=results, query=q,
            undefeated=None, alltime_json="[]", recent_json="[]",
        )
    else:
        undefeated = queries.recent_undefeated_placements(db, limit=3)
        cutoff: str = (date.today() - timedelta(days=90)).isoformat()
        alltime: list[dict[str, Any]] = queries.all_archetypes_with_stats(db)
        recent: list[dict[str, Any]] = queries.all_archetypes_with_stats(db, cutoff=cutoff)
        db.close()
        return render_template(
            "archetypes.html", archetypes=None, query=q,
            undefeated=undefeated,
            alltime_json=json.dumps(alltime),
            recent_json=json.dumps(recent),
        )

@bp.route("/archetypes/random")
def archetype_random() -> Response:
    db: sqlite3.Connection = get_db()
    archetype_id: int | None = queries.random_archetype_id(db)
    db.close()
    if archetype_id is None:
        abort(404)
    return redirect(url_for(
        "main.archetype_detail", archetype_id=archetype_id, via="random",
    ))

@bp.route("/archetypes/<int:archetype_id>")
def archetype_detail(archetype_id: int) -> str:
    db: sqlite3.Connection = get_db()
    archetype: sqlite3.Row | None = queries.get_archetype(db, archetype_id)
    if archetype is None:
        db.close()
        abort(404)

    playrate: queries.ArchetypePlayrate = queries.archetype_playrate(db, archetype_id)
    winrate: queries.WinLossDraw = queries.archetype_winrate(db, archetype_id)
    matchups: list[queries.ArchetypeMatchup] = queries.archetype_matchups(db, archetype_id)
    top_players: list[dict[str, Any]] = queries.archetype_top_players(db, archetype_id)
    pinned_undefeated: list[queries.UndefeatedPlacement] = (
        queries.recent_undefeated_placements(db, archetype_id=archetype_id, limit=1)
    )

    recent_results: list[sqlite3.Row] = queries.archetype_recent_results(
        db, archetype_id, limit=500, offset=0,
    )

    recent_only: bool = request.args.get("recent") == "1"
    card_stats: list[sqlite3.Row] = queries.archetype_card_stats(
        db, archetype_id, recent_only=recent_only,
    )
    db.close()

    return render_template(
        "archetype_detail.html",
        archetype=archetype,
        playrate=playrate,
        winrate=winrate,
        matchups=matchups,
        top_players=top_players,
        pinned_undefeated=pinned_undefeated[0] if pinned_undefeated else None,
        recent_results=recent_results,
        card_stats=card_stats,
        recent_only=recent_only,
    )

@bp.route("/cards")
def cards_index() -> str | Response:
    """Card search with exact-match redirect (case/punctuation insensitive)."""
    q: str = request.args.get("q", "").strip()
    db: sqlite3.Connection = get_db()
    if q:
        # Case-insensitive exact match
        exact: sqlite3.Row | None = db.execute(
            "SELECT card_name FROM card_price_cache "
            "WHERE card_name = ? COLLATE NOCASE LIMIT 1",
            (q,),
        ).fetchone()
        if not exact:
            exact = db.execute(
                "SELECT name AS card_name FROM cards "
                "WHERE name = ? COLLATE NOCASE LIMIT 1",
                (q,),
            ).fetchone()

        # Punctuation-insensitive fallback
        if not exact:
            norm_q: str = _normalize_card_query(q)
            for row in db.execute("SELECT DISTINCT card_name FROM card_price_cache"):
                if _normalize_card_query(row[0]) == norm_q:
                    exact = row
                    break
            if not exact:
                for row in db.execute("SELECT name AS card_name FROM cards"):
                    if _normalize_card_query(row[0]) == norm_q:
                        exact = row
                        break

        if exact:
            db.close()
            return redirect(url_for("main.card_detail", card_name=exact["card_name"]))

        results: list[sqlite3.Row] = [
            row for row, _ in queries.search_cards(db, q)
        ]
        db.close()
        return render_template(
            "cards.html", cards=results, query=q,
            top_cards=None,  alltime_with_json="[]", alltime_no_json="[]",
            recent_with_json="[]", recent_no_json="[]",
        )
    else:
        top_cards: list[sqlite3.Row] = queries.top_cards_by_recent_tournaments(
            db, tournament_count=3, limit=5,
        )
        cutoff: str = (date.today() - timedelta(days=30)).isoformat()
        alltime_with: list[dict[str, Any]] = queries.all_cards_with_stats(db, exclude_banned=False)
        alltime_no: list[dict[str, Any]] = queries.all_cards_with_stats(db, exclude_banned=True)
        recent_with: list[dict[str, Any]] = queries.all_cards_with_stats(db, cutoff=cutoff, exclude_banned=False)
        recent_no: list[dict[str, Any]] = queries.all_cards_with_stats(db, cutoff=cutoff, exclude_banned=True)
        db.close()
        return render_template(
            "cards.html", cards=None, query=q, top_cards=top_cards,
            alltime_with_json=json.dumps(alltime_with),
            alltime_no_json=json.dumps(alltime_no),
            recent_with_json=json.dumps(recent_with),
            recent_no_json=json.dumps(recent_no),
        )

@bp.route("/cards/random")
def card_random() -> Response:
    db: sqlite3.Connection = get_db()
    card_name: str | None = queries.random_card_name(db)
    db.close()
    if card_name is None:
        abort(404)
    return redirect(url_for("main.card_detail", card_name=card_name, via="random"))

@bp.route("/cards/<path:card_name>")
def card_detail(card_name: str) -> str:

    db: sqlite3.Connection = get_db()
    popularity: list[sqlite3.Row] = queries.card_popularity_by_name(db, card_name)
    winrate: queries.WinLossDrawScore = queries.card_winrate_by_name(db, card_name)
    price_history: list[sqlite3.Row] = queries.card_price_history_by_name(db, card_name)

    card_row: sqlite3.Row | None = queries.get_card_by_name(db, card_name)
    scryfall_id: str | None = card_row["scryfall_id"] if card_row else None
    db.close()

    price_history_json: str = json.dumps([
        {"date": row["price_date"], "price": row["price"]}
        for row in price_history
    ])

    return render_template(
        "card_detail.html",
        card_name=card_name,
        scryfall_id=scryfall_id,
        popularity=popularity,
        winrate=winrate,
        price_history=price_history,
        price_history_json=price_history_json,
    )


@bp.route("/tournaments")
def tournaments_index() -> str:
    db: sqlite3.Connection = get_db()
    tournaments: list[sqlite3.Row] = queries.list_tournaments(db)
    db.close()
    return render_template("tournaments.html", tournaments=tournaments)


@bp.route("/tournaments/<tournament_id>")
def tournament_detail(tournament_id: str) -> str:
    db: sqlite3.Connection = get_db()
    tournament: sqlite3.Row | None = queries.get_tournament(db, tournament_id)
    if tournament is None:
        db.close()
        abort(404)

    rounds: list[sqlite3.Row] = queries.tournament_round_results(db, tournament_id)
    standings: list[sqlite3.Row] = queries.tournament_final_standings(db, tournament_id)
    db.close()

    rounds_by_number: dict[int, list[sqlite3.Row]] = {}
    for match in rounds:
        rounds_by_number.setdefault(match["round_number"], []).append(match)

    return render_template(
        "tournament_detail.html",
        tournament=tournament,
        rounds_by_number=rounds_by_number,
        standings=standings,
    )

@bp.route("/visualizer")
def deck_visualizer() -> str:
    url: str = request.args.get("url", "").strip()
    days: int = 30 if request.args.get("days") == "30" else 7

    if not url:
        return render_template(
            "deck_visualizer.html", url="", days=days,
            deck_name=None, deck_author=None, data=None, 
            error=None, price_snapshot=None
        )

    error: str | None = None
    data: queries.DeckVisualizerData | None = None
    deck_name: str | None = None
    deck_author: str | None = None
    price_snapshot: queries.DeckPriceSnapshot | None = None
    db: sqlite3.Connection = get_db()
    try:
        deck: DeckResult = fetch_deck(url)
        deck_name = deck["name"]
        deck_author = deck["author"]
        deck_id: str = extract_deck_id(url)
        price_snapshot: queries.DeckPriceSnapshot | None = (
            queries.get_deck_price_snapshot(db, deck_id) if deck_id else None
        )
        data = queries.deck_visualizer_data(db, deck["cards"], days)
    except Exception as e:
        error = f"Couldn't load that deck: {e}"
    finally:
        db.close()

    return render_template(
        "deck_visualizer.html", url=url, days=days,
        deck_name=deck_name, deck_author=deck_author, data=data, error=error,
        price_snapshot=price_snapshot,
    )
