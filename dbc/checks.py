"""Automatic checks on a listing draft. Errors fail the draft; warnings go to John."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from . import banned
from .drafter import TAG_COUNT, TAG_MAX_CHARS, TITLE_MAX_CHARS, TITLE_MAX_WORDS

MAX_FIELDS = 5               # Etsy custom options and Printify's field mapping
QUESTION_MAX = 45
INSTRUCTIONS_MAX = 120       # Etsy personalization instructions (API tutorial)
TEXT_MAX = 1024
GANG = re.compile(r"(?<![a-z])gang", re.IGNORECASE)   # also catches gangs, gangster, gang's
HOLIDAY_WORDS = re.compile(r"\b(christmas|xmas|holiday|thanksgiving|hanukkah|easter|valentine)", re.I)
STOP_WORDS = {"a", "an", "and", "for", "of", "on", "the", "to", "with", "in", "custom", "personalized"}


@dataclass(frozen=True)
class Issue:
    level: str      # "error" or "warning"
    field: str
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper():7} {self.field}: {self.message}"


def _title_char_ok(ch: str) -> bool:
    # Etsy: letters, numbers, punctuation, math symbols, whitespace, ™ © ®.
    if ch in "™©®":
        return True
    cat = unicodedata.category(ch)
    return cat[0] in ("L", "P") or cat in ("Nd", "Sm", "Zs")


def check_title(title: str) -> list[Issue]:
    out = []
    err = lambda m: out.append(Issue("error", "title", m))
    words = title.split()
    if not title.strip():
        err("title is empty")
        return out
    if len(words) > TITLE_MAX_WORDS:
        err(f"{len(words)} words; Etsy wants under 15")
    if len(title) > TITLE_MAX_CHARS:
        err(f"{len(title)} characters; the limit is {TITLE_MAX_CHARS}")
    if title != title.strip():
        err("leading or trailing space (Printify publish fails)")
    if "  " in title:
        err("double space")
    if any(q in title for q in '"“”'):
        err("quotation marks (Printify publish fails)")
    bad = sorted({ch for ch in title if not _title_char_ok(ch)})
    if bad:
        err(f"characters Etsy rejects in titles: {' '.join(bad)}")
    for ch in "%:&+":
        if title.count(ch) > 1:
            err(f"{ch!r} can only be used once in an Etsy title")
    if "$" in title or "%" in title:
        err("no price or sale text in titles")
    if HOLIDAY_WORDS.search(title):
        out.append(Issue("warning", "title", "holiday word in title; Etsy says only if essential (put it in tags)"))
    counts = Counter(w.lower().strip(",.") for w in words)
    repeats = [w for w, c in counts.items() if c > 2 and w not in STOP_WORDS]
    if repeats:
        out.append(Issue("warning", "title", f"words repeated 3+ times: {', '.join(repeats)}"))
    if counts["gift"] + counts["gifts"] > 1:
        out.append(Issue("warning", "title", "'gift' used more than once; Etsy says avoid repeating gifting words"))
    return out


def check_tags(tags: list[str]) -> list[Issue]:
    out = []
    if len(tags) != TAG_COUNT:
        out.append(Issue("error", "tags", f"{len(tags)} tags; need exactly {TAG_COUNT}"))
    seen = set()
    for tag in tags:
        if len(tag) > TAG_MAX_CHARS:
            out.append(Issue("error", "tags", f"{tag!r} is {len(tag)} characters; max {TAG_MAX_CHARS}"))
        if not re.fullmatch(r"[\w \-'™©®]+", tag) or "_" in tag:
            out.append(Issue("error", "tags", f"{tag!r} has characters Etsy rejects in tags"))
        if tag.lower() in seen:
            out.append(Issue("error", "tags", f"{tag!r} is a duplicate"))
        seen.add(tag.lower())
    return out


def check_description(d: dict, shop: dict, holiday_on: bool) -> list[Issue]:
    out = []
    desc = d["description"]
    disc = shop["disclosure"]
    if disc["ai_phrase"] not in desc:
        out.append(Issue("error", "description", f"AI disclosure missing ({disc['ai_phrase']!r})"))
    if disc["partner_phrase"] not in desc:
        out.append(Issue("error", "description", f"production partner disclosure missing ({disc['partner_phrase']!r})"))
    if shop["promise"]["required_phrase"] not in desc:
        out.append(Issue("error", "description", "returns/misprint promise missing"))
    if holiday_on and shop["holiday"]["order_by_label"] not in desc:
        out.append(Issue("error", "description", "holiday order-by date missing"))
    key = d.get("primary_keyword", "")
    head = banned.normalize(desc[:160])
    missing = [w for w in banned.normalize(key).split() if w not in head.split()]
    if key and missing:
        out.append(Issue("warning", "description",
                         f"first 160 characters don't restate {key!r} (missing: {', '.join(missing)})"))
    return out


def check_personalization(fields: list[dict]) -> list[Issue]:
    out = []
    if len(fields) > MAX_FIELDS:
        out.append(Issue("error", "personalization", f"{len(fields)} fields; Etsy and Printify allow {MAX_FIELDS}"))
    for i, f in enumerate(fields, 1):
        name = f"personalization {i}"
        if not f["question"].strip():
            out.append(Issue("error", name, "question is empty"))
        if len(f["question"]) > QUESTION_MAX:
            out.append(Issue("error", name, f"question is {len(f['question'])} characters; max {QUESTION_MAX}"))
        if len(f["instructions"]) > INSTRUCTIONS_MAX:
            out.append(Issue("error", name, f"instructions are {len(f['instructions'])} characters; max {INSTRUCTIONS_MAX}"))
        if not 1 <= f["max_chars"] <= TEXT_MAX:
            out.append(Issue("error", name, f"max_chars {f['max_chars']} must be 1–{TEXT_MAX}"))
    return out


def check_settings(d: dict, shop: dict) -> list[Issue]:
    out = []
    if d["settings"].get("production_partner") != shop["shop"]["production_partner"]:
        out.append(Issue("error", "settings", "production partner must be exactly 'Printify'"))
    if d["price_status"] != "approved":
        out.append(Issue("warning", "price", f"${d['price']:.2f} is not approved by John yet"))
    if d["price"] <= 0:
        out.append(Issue("error", "price", "no price set"))
    for note in d.get("confirm", []):
        out.append(Issue("warning", "specs", f"confirm before listing: {note}"))
    return out


def check_terms(d: dict, terms: list[banned.Term]) -> list[Issue]:
    fields = {
        "title": d["title"],
        "tags": " | ".join(d["tags"]),
        "description": d["description"],
        "design text": " | ".join(d.get("design_text", [])),
        "personalization": " | ".join(f"{f['question']} {f['instructions']}" for f in d["personalization"]),
    }
    out = []
    for field, text in fields.items():
        if GANG.search(text):
            out.append(Issue("error", field, "uses 'gang'; say crew or buddies instead"))
    for hit in banned.scan(terms, d["product_kind"], fields):
        if normalize_gang(hit.term.phrase):
            continue  # already reported above
        level = "error" if hit.term.level == "block" else "warning"
        out.append(Issue(level, hit.field, f"{hit.term.level}: {hit.term.phrase!r} ({hit.term.why})"))
    return out


def normalize_gang(phrase: str) -> bool:
    return banned.normalize(phrase) == "gang"


def run(d: dict, shop: dict, terms: list[banned.Term], holiday_on: bool) -> list[Issue]:
    issues = (
        check_title(d["title"])
        + check_tags(d["tags"])
        + check_description(d, shop, holiday_on)
        + check_personalization(d["personalization"])
        + check_settings(d, shop)
        + check_terms(d, terms)
    )
    return sorted(issues, key=lambda i: i.level != "error")
