"""Banned and caution terms (data/banned_terms.txt).

Line format: ``phrase | level | products | why``. Matching ignores case,
apostrophes and punctuation, and also catches a trailing "s".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

LEVELS = ("block", "caution")
PRODUCTS = ("all", "mug", "apparel")


def normalize(text: str) -> str:
    """Lowercase, fold & and + to "and", drop apostrophes, turn other punctuation into spaces."""
    text = text.lower()
    text = text.replace("♥", " heart ").replace("❤", " heart ")
    text = re.sub(r"[&+]", " and ", text)
    text = re.sub(r"['’‘`]", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


@dataclass(frozen=True)
class Term:
    phrase: str
    level: str
    products: str
    why: str

    @property
    def pattern(self) -> re.Pattern[str]:
        return re.compile(r"(?<![a-z0-9])" + re.escape(normalize(self.phrase)) + r"s?(?![a-z0-9])")

    def applies_to(self, kind: str) -> bool:
        return self.products in ("all", kind)


@dataclass(frozen=True)
class Hit:
    term: Term
    field: str


def load(path: str | Path) -> list[Term]:
    terms = []
    for n, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 4:
            raise ValueError(f"{path}:{n}: expected 'phrase | level | products | why'")
        phrase, level, products, why = parts
        if level not in LEVELS or products not in PRODUCTS or not normalize(phrase):
            raise ValueError(f"{path}:{n}: bad level/products/phrase in {line!r}")
        terms.append(Term(phrase, level, products, why))
    return terms


def scan(terms: list[Term], kind: str, fields: dict[str, str]) -> list[Hit]:
    """Return one hit per (term, field). A block entry for this product wins over a caution."""
    applicable = [t for t in terms if t.applies_to(kind)]
    hits: dict[tuple[str, str], Hit] = {}
    for field, text in fields.items():
        norm = normalize(text)
        for term in applicable:
            if term.pattern.search(norm):
                key = (normalize(term.phrase), field)
                if key not in hits or term.level == "block":
                    hits[key] = Hit(term, field)
    return list(hits.values())
