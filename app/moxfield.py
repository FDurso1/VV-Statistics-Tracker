
from __future__ import annotations
import os
import re
import time
from typing import Any, TypedDict
import requests
from dotenv import load_dotenv

load_dotenv()

API_URL: str = "https://api2.moxfield.com/v3/decks/all/{deck_id}"
USER_AGENT_ENV_VAR: str = "MOXFIELD_USER_AGENT"
_MIN_INTERVAL_SECONDS: float = 5.0 # theoretically can be 1 second, but in practice failed. 5 is safer.
_last_request_at: float = 0.0

class CardInfo(TypedDict):
    """Per-card entry returned by _extract_cards."""
    quantity: int
    mainboard_quantity: int
    sideboard_quantity: int
    scryfall_id: str | None

class DeckResult(TypedDict):
    """Return shape of fetch_deck."""
    name: str
    author: str
    cards: dict[str, CardInfo]

class InvalidMoxfieldURLError(ValueError):
    """Raised before any HTTP request when the URL isn't a valid
    Moxfield deck reference."""

def _get_user_agent() -> str:
    """Read the Moxfield User-Agent from the environment."""
    user_agent: str | None = os.environ.get(USER_AGENT_ENV_VAR)
    if not user_agent:
        raise RuntimeError(
            f"{USER_AGENT_ENV_VAR} is not set. Add it to a local .env file."
        )
    return user_agent

def _rate_limit() -> None:
    """Block until at least _MIN_INTERVAL_SECONDS since the last request."""
    global _last_request_at
    elapsed: float = time.monotonic() - _last_request_at
    if elapsed < _MIN_INTERVAL_SECONDS:
        time.sleep(_MIN_INTERVAL_SECONDS - elapsed)
    _last_request_at = time.monotonic()

def extract_deck_id(moxfield_url_or_id: str) -> str:
    match: re.Match[str] | None = re.search(
        r"moxfield\.com/decks/([\w-]+)", moxfield_url_or_id
    )
    if match:    
        return match.group(1)
    else:
        return moxfield_url_or_id.strip()

def _fetch_raw_deck_json(moxfield_url: str) -> dict[str, Any]:
    """Single HTTP request point."""
    
    deck_id: str = extract_deck_id(moxfield_url)
    if not re.fullmatch(r"[\w-]+", deck_id):
        raise InvalidMoxfieldURLError(
            f"{moxfield_url!r} doesn't look like a real Moxfield deck URL or ID."
        )
    headers: dict[str, str] = {"User-Agent": _get_user_agent()}
    _rate_limit()
    resp: requests.Response = requests.get(
        API_URL.format(deck_id=deck_id), headers=headers, timeout=15
    )
    resp.raise_for_status()
    result: dict[str, Any] = resp.json()
    return result

def _extract_cards(data: dict[str, Any]) -> dict[str, CardInfo]:
    """Extract {card_name: CardInfo} from mainboard & sideboard."""
    
    cards: dict[str, CardInfo] = {}
    boards: dict[str, Any] = data.get("boards") or {}
    for board_name in ("mainboard", "sideboard"):
        board: dict[str, Any] = boards.get(board_name) or {}
        board_cards: dict[str, Any] = board.get("cards") or {}
        for entry in board_cards.values():
            card: dict[str, Any] = entry["card"]
            name: str = card["name"]
            qty: int = entry["quantity"]
            scryfall_id: str | None = card.get("scryfall_id")
            if name not in cards:
                cards[name] = {
                    "quantity": 0,
                    "mainboard_quantity": 0,
                    "sideboard_quantity": 0,
                    "scryfall_id": scryfall_id,
                }
            cards[name]["quantity"] += qty
            cards[name][f"{board_name}_quantity"] += qty  # type: ignore[literal-required]
    return cards

def _extract_author(data: dict[str, Any]) -> str:
    
    authors: list[dict[str, Any]] = data.get("authors") or []
    names: list[str] = [a.get("displayName") for a in authors if a.get("displayName")] # type: ignore
    if names:
        return ", ".join(names)
    created_by: dict[str, Any] = data.get("createdByUser") or {}
    return created_by.get("displayName") or created_by.get("userName") or "Unknown"

def fetch_full_snapshot(moxfield_url: str) -> dict[str, Any]:
    return _fetch_raw_deck_json(moxfield_url)

def extract_cards_from_snapshot(data: dict[str, Any]) -> dict[str, CardInfo]:
    return _extract_cards(data)

def extract_name_from_snapshot(data: dict[str, Any]) -> str | None:
    return data.get("name") or None

def extract_author_from_snapshot(data: dict[str, Any]) -> str:
    return _extract_author(data)

def fetch_decklist(moxfield_url: str) -> dict[str, CardInfo]:
    data: dict[str, Any] = _fetch_raw_deck_json(moxfield_url)
    return _extract_cards(data)

def fetch_deck(moxfield_url: str) -> DeckResult:
    data: dict[str, Any] = _fetch_raw_deck_json(moxfield_url)
    return {
        "name": data.get("name") or "(untitled deck)",
        "author": _extract_author(data),
        "cards": _extract_cards(data),
    }
    