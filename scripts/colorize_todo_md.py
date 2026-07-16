#!/usr/bin/env python3
"""Normalize color-coded emoji markers on TODO.md checklist items.

Inserts colored emoji markers right after the tag chain of each checklist
item, matching the colors used by scripts/generate_todo_html.py:
    - [x] **Done** - **Deterministic** - 🟢 🔵 Fix the parser.
    - [x] **Done Done** - **API** - ✅ 🟣 Add the sync route, verified end-to-end.
    - [ ] **Pending** - **API** - 🟡 🟣 Add another route.

Two kinds of markers, both derived from the tag chain:
  - A status-tier marker: 🟢 Done (implemented), ✅ Done Done (implemented
    AND independently re-verified — a stricter claim than Done, don't
    apply it retroactively without checking), or 🟡 Pending (not done
    yet). Unchecked items with no explicit status tag get a **Pending**
    tag inserted automatically; checked items are left as whatever
    Done/Done Done tag they already carry (never synthesized).
  - A category dot for the remaining tag (e.g. Deterministic/AI/API),
    assigned by first-appearance order in the file — the same rule
    generate_todo_html.py uses for its HTML palette, so the two stay
    visually consistent.

Idempotent: re-running strips any existing markers and re-derives them
from the tags, so it's safe to run on every edit/commit.
"""
import re
import sys
from pathlib import Path

ITEM_RE = re.compile(r"^(\s*-\s\[([ xX])\]\s)(.+?)(\s*)$")
TAG_RE = re.compile(r"^\*\*([^*]+)\*\*\s*-\s*")
EMOJI_RE = re.compile(
    r"^(?:(?:\U0001F534|\U0001F7E0|\U0001F7E1|\U0001F7E2|\U0001F535|\U0001F7E3|\U0001F7E4|⚫|⚪|✅)\s+)+"
)

# Category dot rotation, assigned by first-appearance order. Avoids green/
# yellow/checkmark, which are reserved for the Done/Pending status markers
# below so the two marker kinds never share a color.
EMOJI_PALETTE = ["\U0001F535", "\U0001F7E3", "\U0001F7E0", "\U0001F534", "\U0001F7E4", "⚫"]

# Status-tier markers: not done / done / independently re-verified.
STATUS_EMOJI = {"pending": "\U0001F7E1", "done": "\U0001F7E2", "done done": "✅"}


def split_tags(rest: str):
    tags = []
    while True:
        m = TAG_RE.match(rest)
        if not m:
            break
        tags.append(m.group(1).strip())
        rest = rest[m.end():]
    return tags, rest


def split_status(tags):
    if tags and tags[0].lower() in STATUS_EMOJI:
        return tags[0], tags[1:]
    return None, tags


def category_of(tags):
    _, cat_tags = split_status(tags)
    return cat_tags[-1] if cat_tags else None


def colorize(md_text: str) -> str:
    lines = md_text.splitlines()

    categories = []
    for line in lines:
        m = ITEM_RE.match(line)
        if not m:
            continue
        tags, _ = split_tags(m.group(3))
        cat = category_of(tags)
        if cat and cat not in categories:
            categories.append(cat)
    emoji_for = {c: EMOJI_PALETTE[i % len(EMOJI_PALETTE)] for i, c in enumerate(categories)}

    out = []
    for line in lines:
        m = ITEM_RE.match(line)
        if not m:
            out.append(line)
            continue
        prefix, checkbox, body, trail = m.groups()
        is_checked = checkbox.lower() == "x"
        tags, rest = split_tags(body)
        rest = EMOJI_RE.sub("", rest)

        status_tag, cat_tags = split_status(tags)
        if status_tag is None and not is_checked:
            status_tag = "Pending"  # only ever synthesized for unchecked items

        markers = []
        if status_tag:
            markers.append(STATUS_EMOJI[status_tag.lower()])
        cat = cat_tags[-1] if cat_tags else None
        cat_emoji = emoji_for.get(cat)
        if cat_emoji:
            markers.append(cat_emoji)

        full_tags = ([status_tag] if status_tag else []) + cat_tags
        tag_chain = "".join(f"**{t}** - " for t in full_tags)
        marker_str = (" ".join(markers) + " ") if markers else ""
        new_body = tag_chain + marker_str + rest
        out.append(f"{prefix}{new_body}{trail}")

    text = "\n".join(out)
    return text + "\n" if md_text.endswith("\n") else text


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("TODO.md")
    if not path.exists():
        print(f"colorize-todo: source file not found: {path}", file=sys.stderr)
        return 0

    text = path.read_text(encoding="utf-8")
    new_text = colorize(text)
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
        print(f"colorize-todo: updated {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
