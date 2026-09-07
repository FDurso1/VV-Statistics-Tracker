
"""
Scryfall bulk-data client. Downloads the full card database, filters
for tournament-legal printings, and extracts cheapest USD prices.
"""

from __future__ import annotations

import gzip
import json
import os
import tempfile
from typing import Any, BinaryIO, Iterator

import ijson  #type: ignore[MissingTypeStub]
import requests

BULK_DATA_LIST_URL: str = "https://api.scryfall.com/bulk-data"
HEADERS: dict[str, str] = {
    "User-Agent": "MTGTracker/1.0 (personal tournament-tracking site)",
    "Accept": "application/json;q=0.9,*/*;q=0.8",
}
GZIP_MAGIC: bytes = b"\x1f\x8b"
NON_TOURNAMENT_SET_TYPES: set[str] = {"memorabilia", "funny"}

def _get_default_cards_download_uri() -> str:

    resp: requests.Response = requests.get(
        BULK_DATA_LIST_URL, headers=HEADERS, timeout=30,
    )
    resp.raise_for_status()
    data: list[dict[str, Any]] = resp.json()["data"]
    for item in data:
        if item["type"] == "default_cards":
            uri: str | None = (
                item.get("download_uri") or item.get("jsonl_download_uri")
            )
            if uri is None:
                raise RuntimeError(
                    "Scryfall's default_cards entry has neither "
                    "'download_uri' nor 'jsonl_download_uri' -- "
                    f"available keys: {sorted(item.keys())}"
                )
            return uri
    raise RuntimeError(
        "Scryfall's bulk-data listing did not include a 'default_cards' entry"
    )

def _download_to_temp_file(url: str) -> str:

    fd: int
    path: str
    fd, path = tempfile.mkstemp(suffix=".scryfall-bulk")
    os.close(fd)
    resp: requests.Response = requests.get(
        url, headers=HEADERS, stream=True, timeout=120,
    )
    resp.raise_for_status()
    with open(path, "wb") as f:
        chunk: bytes
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
    return path

def _iter_cards(file_obj: BinaryIO) -> Iterator[dict[str, Any]]:

    magic: bytes = file_obj.peek(2)[:2]  # type: ignore[attr-defined]

    if magic == GZIP_MAGIC:
        with gzip.GzipFile(fileobj=file_obj) as gz:
            line: bytes
            for line in gz:
                line = line.strip()
                if line:
                    yield json.loads(line)
    else:
        card: dict[str, Any]
        for card in ijson.items(file_obj, "item"):
            yield card

def _is_tournament_legal_printing(card: dict[str, Any]) -> bool:

    vintage_status: str | None = (card.get("legalities") or {}).get("vintage") # type: ignore
    if vintage_status not in ("legal", "restricted"):
        return False
    if card.get("oversized"):
        return False
    if card.get("set_type") in NON_TOURNAMENT_SET_TYPES:
        return False
    if "paper" not in (card.get("games") or []):
        return False
    if card.get("set") == "sum":
        return False
    return True

def _cheapest_prices_from_bulk(
    name_filter: set[str] | None = None,
) -> dict[str, float]:

    download_uri: str = _get_default_cards_download_uri()
    cheapest: dict[str, float] = {}

    temp_path: str = _download_to_temp_file(download_uri)
    try:
        with open(temp_path, "rb") as f:
            for card in _iter_cards(f):
                name: str | None = card.get("name")
                if name is None:
                    continue
                if name_filter is not None and name not in name_filter:
                    continue
                if not _is_tournament_legal_printing(card):
                    continue
                prices: dict[str, str | None] = card.get("prices") or {}
                price_key: str
                for price_key in ("usd", "usd_foil"):
                    price_str: str | None = prices.get(price_key)
                    if price_str is None:
                        continue
                    price: float = float(price_str)
                    if name not in cheapest or price < cheapest[name]:
                        cheapest[name] = price
    finally:
        os.unlink(temp_path)

    return cheapest

def cheapest_vintage_legal_prices(
    card_names: set[str],
) -> dict[str, float | None]:

    wanted: set[str] = set(card_names)
    cheapest: dict[str, float] = _cheapest_prices_from_bulk(name_filter=wanted)
    return {name: cheapest.get(name) for name in wanted}

def all_vintage_legal_prices() -> dict[str, float]:
    return _cheapest_prices_from_bulk(name_filter=None)