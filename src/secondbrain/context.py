"""Fixed-budget context pack for an AI: the profile plus the top relevant memory lines."""

from __future__ import annotations

from pathlib import Path

from .index import Index

PROFILE_MAX_CHARS = 3000
TOP_K = 8
PER_SOURCE_CAP = 4
PROFILE_HEADER = "# About me\n"
MEMORY_HEADER = "# Relevant memory\n"
SEPARATOR = "\n\n"


def _flat(text: str) -> str:
    return " ".join(text.split())


def _read_profile(path: Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def build_context(question: str, index: Index, profile_path: Path, max_chars: int = 8000) -> str:
    """Profile (<= 3000 chars) + top hits as `- [id] title: snippet`, never more than max_chars in total.

    The size depends on the budget and top-k, not on how many cards exist.
    """
    if max_chars <= 0:
        return ""
    sections: list[str] = []
    used = 0

    profile = _read_profile(profile_path)
    room = max_chars - len(PROFILE_HEADER)
    if profile and room > 0:
        section = PROFILE_HEADER + profile[: min(PROFILE_MAX_CHARS, room)]
        sections.append(section)
        used = len(section)

    budget = max_chars - used - (len(SEPARATOR) if sections else 0) - len(MEMORY_HEADER)
    chosen: list[str] = []
    if budget > 0:
        for hit in index.search(question, k=TOP_K, per_source_cap=PER_SOURCE_CAP):
            title, snippet = _flat(hit.title), _flat(hit.snippet)
            line = f"- [{hit.card_id}] {title}: {snippet}" if snippet else f"- [{hit.card_id}] {title}"
            cost = len(line) + (1 if chosen else 0)
            if cost > budget:
                break
            chosen.append(line)
            budget -= cost
    if chosen:
        sections.append(MEMORY_HEADER + "\n".join(chosen))
    return SEPARATOR.join(sections)
