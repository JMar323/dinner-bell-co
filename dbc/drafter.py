"""Listing drafter: one idea in, an Etsy listing draft out.

Follows the approved listing template (shop/setup-kit.md section 6). The draft
is a file for John to review; nothing here talks to Etsy or Printify.
"""

from __future__ import annotations

import datetime as dt
import re

TITLE_MAX_CHARS = 140
TITLE_MAX_WORDS = 14          # Etsy April 2026: "under 15 words"
TAG_MAX_CHARS = 20
TAG_COUNT = 13


class IdeaError(ValueError):
    """The idea file is missing something the drafter needs."""


def _require(idea: dict, *keys: str) -> None:
    missing = [k for k in keys if not idea.get(k)]
    if missing:
        raise IdeaError(f"idea {idea.get('id', '?')!r} is missing: {', '.join(missing)}")


def build_title(idea: dict, product: dict) -> str:
    """Use the idea's title, or build one: item first, then the second buyer phrase, then size."""
    if idea.get("title"):
        return idea["title"]
    noun = product["title_noun"]
    lead = f"Personalized {idea['recipient']} {noun}"
    if idea.get("motif"):
        lead += f" with {idea['motif']}"
    parts = [lead]
    theme, alt = idea.get("theme", ""), idea.get("recipient_alt", "")
    if theme and alt and theme.lower() != alt.lower():
        parts.append(f"Custom {theme.title()} {noun} for {alt}")
    elif theme or alt:
        parts.append(f"Custom {(alt or theme).title()} {noun}")
    if product.get("size_label"):
        parts.append(product["size_label"])
    # Drop trailing parts until it fits; the checker still reports anything left over.
    while len(parts) > 1:
        title = ", ".join(parts)
        if len(title) <= TITLE_MAX_CHARS and len(title.split()) <= TITLE_MAX_WORDS:
            return title
        parts.pop()
    return parts[0]


def _tag_ok(tag: str) -> bool:
    return 0 < len(tag) <= TAG_MAX_CHARS and re.fullmatch(r"[a-z0-9 \-'™©®]+", tag) is not None


def build_tags(idea: dict, product: dict) -> list[str]:
    """The idea's keywords first, topped up to 13 with phrases built from the idea."""
    noun = product["noun"]
    recipient = idea["recipient"].lower()
    alt = (idea.get("recipient_alt") or "").lower()
    theme = (idea.get("theme") or "").lower()
    fallback = [
        f"{recipient} {noun}",
        f"personalized {recipient}",
        f"custom {theme} {noun}" if theme else "",
        f"gift for {recipient}",
        f"{recipient} christmas gift",
        f"{alt} {noun}" if alt else "",
        f"gift for {alt}" if alt else "",
        f"{alt} christmas gift" if alt else "",
        f"{theme} gift" if theme and theme not in (recipient, alt) else "",
        *product.get("tag_seeds", []),
        f"names {noun}",
        f"family names {noun}",
        f"{recipient} {noun} gift",
        f"{recipient} birthday gift",
        f"{alt} birthday gift" if alt else "",
    ]
    tags: list[str] = []
    for raw in list(idea.get("keywords", [])) + fallback:
        tag = " ".join(raw.lower().split())
        if tag and tag not in tags and (raw in idea.get("keywords", []) or _tag_ok(tag)):
            tags.append(tag)
    # Idea keywords are kept even when bad, so the checker can name them; fallbacks are pre-filtered.
    return tags[:TAG_COUNT]


def build_personalization(idea: dict) -> list[dict]:
    fields = []
    for spec in idea.get("personalization", []):
        repeat = int(spec.get("repeat", 1))
        for n in range(1, repeat + 1):
            fields.append({
                "question": spec["question"].format(n=n),
                "instructions": spec.get("instructions", "").format(n=n),
                "max_chars": int(spec["max_chars"]),
                "required": bool(spec.get("required", True)),
            })
    return fields


def holiday_active(shop: dict, today: dt.date) -> bool:
    h = shop.get("holiday", {})
    return bool(h.get("enabled")) and today <= h["order_by"]


def build_description(idea: dict, product: dict, shop: dict, today: dt.date) -> str:
    blocks = [idea["opening"].strip()]

    steps = list(idea.get("how_to_order", [])) or ["Fill in each personalization box exactly as it should print."]
    steps.append(shop["how_to_order"]["last_step"])
    emoji = idea.get("order_emoji", "✏️")
    blocks.append(f"{emoji} How to order\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1)))

    specs = list(product["specs"])
    specs[1:1] = idea.get("extra_specs", [])
    blocks.append(product["heading"] + "\n" + "\n".join(f"• {s}" for s in specs))

    if holiday_active(shop, today):
        h = shop["holiday"]
        blocks.append(
            f"{h['emoji']} {h['name']} timing\n"
            f"{shop['shop']['processing_line']} Order by {h['order_by_label']} for {h['name']}."
        )
    else:
        blocks.append(f"📦 Timing\n{shop['shop']['processing_line']}")

    promise = shop["promise"]
    blocks.append(promise["heading"] + "\n" + promise["text"].format(noun=product["noun"]))
    blocks.append(shop["disclosure"]["line"])
    return "\n\n".join(blocks)


def draft(idea: dict, products: dict, shop: dict, today: dt.date | None = None) -> dict:
    _require(idea, "id", "product", "recipient", "opening")
    today = today or dt.date.today()
    if idea["product"] not in products:
        raise IdeaError(f"unknown product {idea['product']!r}; known: {', '.join(products)}")
    product = products[idea["product"]]
    tags = build_tags(idea, product)
    return {
        "id": idea["id"],
        "status": "draft: needs John's OK before anything is created or published",
        "drafted_on": today.isoformat(),
        "line": idea.get("line", ""),
        "product": idea["product"],
        "product_kind": product["kind"],
        "print_provider": product.get("provider", ""),
        "title": build_title(idea, product),
        "primary_keyword": idea.get("primary_keyword") or (tags[0] if tags else ""),
        "tags": tags,
        "description": build_description(idea, product, shop, today),
        "personalization": build_personalization(idea),
        "design_text": list(idea.get("design_text", [])),
        "price": product["price"],
        "price_status": product["price_status"],
        "attributes": {**product.get("attributes", {}), **idea.get("attributes", {})},
        "settings": {
            "production_partner": shop["shop"]["production_partner"],
            "return_policy": shop["shop"]["return_policy"],
            "processing_profile": shop["shop"]["processing_profile"],
            "section": idea.get("section", ""),
            "who_made": "Designed by a seller",
        },
        "confirm": list(product.get("confirm", [])),
    }
