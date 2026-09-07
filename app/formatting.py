
from urllib.parse import urlparse

def username_from_url(url:str):
    if not url: 
        return url
    parsed = urlparse(url)
    if not parsed.netloc: 
        return url
    segments = [s for s in parsed.path.split("/") if s]
    if segments:
        return segments[-1]
    return url

def clean_deck_name(raw_name: str | None, is_mtgo: bool = False) -> str | None:
    if not raw_name or not str(raw_name).strip(): 
        return None
    name = str(raw_name).strip()
    if is_mtgo:
        before, sep, _ = name.partition(" by ")
        if sep: 
            name = before.strip()
    return name or None

def truncate_for_display(text:str, max_length:int=40):
    if not text: 
        return text
    if len(text) <= max_length: 
        return text
    return text[:max_length - 1] + "…"
