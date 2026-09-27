
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.scryfall import all_vintage_legal_prices  # noqa: E402
from app.constants import BASIC_LAND_NAMES  # noqa: E402
from app.db_archive import ensure_db_extracted  # noqa: E402

DB_PATH = ROOT / "data" / "mtg_data.db"
RETENTION_DAYS = 30

def update_prices(
    db_path: Path = DB_PATH,
    price_lookup_fn: Callable[[], dict[str, float]] = all_vintage_legal_prices,
) -> None:
    if db_path == DB_PATH:
        ensure_db_extracted(db_path)
    conn: sqlite3.Connection = sqlite3.connect(db_path)

    prices: dict[str, float] = price_lookup_fn()

    name: str
    for name in BASIC_LAND_NAMES:
        prices[name] = 0.0

    today: str = date.today().isoformat()
    price: float
    for name, price in prices.items():
        conn.execute(
            "INSERT OR REPLACE INTO card_price_cache (card_name, price_date, price) VALUES (?, ?, ?)",
            (name, today, price),
        )

    cutoff: str = (date.today() - timedelta(days=RETENTION_DAYS)).isoformat()
    deleted: int = conn.execute(
        "DELETE FROM card_price_cache WHERE price_date < ?", (cutoff,)
    ).rowcount

    conn.commit()
    conn.close()

    print(
        f"Priced {len(prices)} card(s) for {today}. "
        f"Pruned {deleted} row(s) older than {RETENTION_DAYS} days."
    )

if __name__ == "__main__":
    update_prices()
