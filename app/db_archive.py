
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "mtg_data.db"
DB_ZIP_PATH = ROOT / "data" / "mtg_data.db.zip"

def compress_db(db_path:Path=DB_PATH, zip_path:Path=DB_ZIP_PATH):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf: 
        zf.write(db_path, arcname=db_path.name)
    
def extract_db(zip_path:Path=DB_ZIP_PATH, dest_dir:Path|None=None):
    dest_dir = dest_dir or zip_path.parent
    with zipfile.ZipFile(zip_path, "r") as zf: 
        zf.extractall(dest_dir)
    
def ensure_db_extracted(db_path:Path=DB_PATH, zip_path:Path=DB_ZIP_PATH):
    if db_path.exists(): 
        return False
    if zip_path.exists(): 
        extract_db(zip_path, db_path.parent)
        return True
    return False
