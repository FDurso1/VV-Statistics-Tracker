
import os
import sqlite3
from pathlib import Path
from app.db_archive import ensure_db_extracted

_override = os.environ.get("MTG_TRACKER_DB_PATH")
DB_PATH = (
    Path(_override).resolve() if _override
    else Path(__file__).resolve().parent.parent / "data" / "mtg_data.db"
)

if not _override:
    ensure_db_extracted(DB_PATH)

def get_db():
    uri = DB_PATH.as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn