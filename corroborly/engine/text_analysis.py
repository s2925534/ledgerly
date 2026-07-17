from __future__ import annotations

import re


def split_sentences(text: str) -> list[str]:
    normalized = " ".join(text.replace("\n", " ").split())
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", normalized) if part.strip()]


def has_inline_citation(sentence: str) -> bool:
    return bool(
        re.search(r"\([A-Z][A-Za-z'-]+(?: et al\.)?,\s*\d{4}[a-z]?\)", sentence)
        or re.search(r"\[[0-9,\s-]+\]", sentence)
    )
