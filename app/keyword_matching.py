
from __future__ import annotations
import re
from typing import Pattern
import pandas as pd

def parse_keyword_groups(keyword_maps_df: pd.DataFrame) -> list[list[str]]:
    """Parse the KeywordMaps sheet into equivalence groups"""
    
    groups: list[list[str]] = []
    for _, row in keyword_maps_df.iterrows():
        terms: list[str] = [
            str(c).strip()
            for c in row
            if str(c).strip() and str(c).strip().lower() != "nan"
        ]
        seen: set[str] = set()
        deduped: list[str] = []
        for t in terms:
            if t.lower() not in seen:
                seen.add(t.lower())
                deduped.append(t)
        if len(deduped) >= 2:
            groups.append(deduped)
    return groups

def _term_pattern(term: str) -> Pattern[str]:
    return re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.IGNORECASE)

def generate_alias_variants(archetype_name: str, keyword_groups: list[list[str]]) -> set[str]:
    """Generate every alias of an archetype name."""
    
    aliases: set[str] = set()
    term_and_group: list[tuple[str, list[str]]] = [
        (term, group) for group in keyword_groups for term in group
    ]
    term_and_group.sort(key=lambda tg: len(tg[0]), reverse=True)
    matched_groups: set[int] = set()
    for term, group in term_and_group:
        if id(group) in matched_groups:
            continue
        m: re.Match[str] | None = _term_pattern(term).search(archetype_name)
        if not m:
            continue
        matched_groups.add(id(group))
        for synonym in group:
            if synonym != term:
                aliases.add(
                    archetype_name[: m.start()] + synonym + archetype_name[m.end() :]
                )
    return aliases

def generate_all_search_aliases(names: list[str], groups: list[list[str]]) -> dict[str, set[str]]:
    """Generate aliases for every archetype name that has at least one keyword-group match."""
    result: dict[str, set[str]] = {}
    for name in names:
        aliases: set[str] = generate_alias_variants(name, groups)
        if aliases:
            result[name] = aliases
    return result
