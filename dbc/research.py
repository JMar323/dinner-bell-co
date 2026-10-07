"""Weekly idea research (routine 1): gift ideas found on the web, scored and screened for John.

Inputs (John's side): the themes sheet (config/themes.csv or a Google Sheet), config/research.toml
(products, focus, how many ideas), ideas/feedback.md (his likes and no-gos), the ideas he already
kept (ideas/*.toml) and the last few weeks' lists, so nothing repeats.

Two steps, so any research engine can do the middle part:
  brief   builds the instructions and the answer format (dbc research-brief)
  ingest  checks an answer: scores it, screens banned terms, writes ideas/inbox/<year>-W<week>/
          report.md + ideas.json, and drafts listings for any idea John kept (dbc research-ingest)

Engines: a weekly Claude routine reads the brief, researches, writes the answer and runs ingest;
or `dbc research` asks the Anthropic API itself (needs ANTHROPIC_API_KEY and costs money per run).
Nothing is created in Printify or Etsy: John picks ideas, and only then does art or listing work start.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import re
import urllib.request
from pathlib import Path

from . import banned, checks, config, drafter

FALLBACK_BETA = "server-side-fallback-2026-07-01"
SUBMIT = "submit_ideas"


class ResearchError(RuntimeError):
    pass


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


# ---------------------------------------------------------------- inputs

def parse_themes(text: str) -> list[dict]:
    """Rows of the themes sheet with active = yes. Column names are matched loosely."""
    rows = []
    for raw in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        if row.get("active", "yes").lower() not in ("yes", "y", "true", "1", "x") or not row.get("theme"):
            continue
        row["id"] = slug(row["theme"])
        row["products"] = [p.strip() for p in re.split(r"[;,]", row.get("products", "")) if p.strip()]
        rows.append(row)
    return rows


def load_themes(root: Path, cfg: dict, override: Path | None = None) -> tuple[list[dict], str]:
    """A CSV given on the command line, else the Google Sheet when it's set and reachable, else the
    CSV in the repo. Returns (rows, where they came from)."""
    if override:
        themes = parse_themes(Path(override).read_text(encoding="utf-8"))
        if not themes:
            raise ResearchError(f"no active themes in {override}")
        return themes, str(override)
    url = cfg.get("themes", {}).get("sheet_csv_url", "")
    if url:
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                themes = parse_themes(r.read().decode("utf-8"))
            if themes:
                return themes, "Google Sheet"
        except (OSError, ValueError, UnicodeDecodeError):
            pass
    path = root / cfg.get("themes", {}).get("file", "config/themes.csv")
    themes = parse_themes(path.read_text(encoding="utf-8"))
    if not themes:
        raise ResearchError(f"no active themes in {path}")
    return themes, str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def week_id(today: dt.date) -> str:
    year, week, _ = today.isocalendar()
    return f"{year}-W{week:02d}"


def recent_names(inbox: Path, this_week: str, weeks: int = 6) -> list[str]:
    names = []
    for d in sorted((p for p in inbox.glob("*-W*") if p.is_dir() and p.name != this_week), reverse=True)[:weeks]:
        try:
            names += [i["name"] for i in json.loads((d / "ideas.json").read_text(encoding="utf-8"))["ideas"]]
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return names


# ---------------------------------------------------------------- the brief

def answer_schema(cfg: dict, theme_ids: list[str]) -> dict:
    """JSON Schema of the answer every engine hands in (also the submit_ideas tool input)."""
    personalization = {
        "type": "object", "additionalProperties": False,
        "required": ["question", "instructions", "max_chars", "repeat"],
        "properties": {
            "question": {"type": "string", "description": "At most 45 characters. Use {n} when repeat > 1."},
            "instructions": {"type": "string", "description": "At most 120 characters."},
            "max_chars": {"type": "integer"},
            "repeat": {"type": "integer", "description": "1, or how many boxes of this kind (names)."},
        },
    }
    listing = {
        "type": "object", "additionalProperties": False,
        "description": "Only when asked: the listing draft fields",
        "required": ["recipient", "recipient_alt", "theme", "motif", "design_text", "title",
                     "primary_keyword", "keywords", "opening", "how_to_order", "order_emoji",
                     "personalization", "holiday", "occasion", "recipient_attribute"],
        "properties": {
            "recipient": {"type": "string", "description": "Who it's for as it reads in the title, e.g. Papa"},
            "recipient_alt": {"type": "string", "description": "Second name for the same person, e.g. Grandpa"},
            "theme": {"type": "string"},
            "motif": {"type": "string", "description": "Short design phrase for the title, e.g. Grandkids Names on Fish"},
            "design_text": {"type": "array", "items": {"type": "string"},
                            "description": "Every word printed on the product, besides the buyer's names"},
            "title": {"type": "string", "description": "Under 15 words, at most 140 characters, no quotes, buyer phrase first"},
            "primary_keyword": {"type": "string"},
            "keywords": {"type": "array", "items": {"type": "string"},
                         "description": "Exactly 13 Etsy tags, lowercase, each at most 20 characters"},
            "opening": {"type": "string", "description": "Two warm sentences that open the description"},
            "how_to_order": {"type": "array", "items": {"type": "string"},
                             "description": "One step per personalization box; the shop adds the final spelling step"},
            "order_emoji": {"type": "string"},
            "personalization": {"type": "array", "items": personalization,
                                "description": "At most 5 boxes in total, counting repeats"},
            "holiday": {"type": "string", "description": "Etsy holiday attribute, e.g. Christmas, or empty"},
            "occasion": {"type": "string", "description": "Etsy occasion attribute, e.g. Birthday, or empty"},
            "recipient_attribute": {"type": "string", "description": "Etsy recipient attribute, e.g. Grandparents, Men"},
        },
    }
    source = {"type": "object", "additionalProperties": False, "required": ["url", "title"],
              "properties": {"url": {"type": "string"}, "title": {"type": "string"}}}
    idea = {
        "type": "object", "additionalProperties": False,
        "required": ["id", "name", "line", "product", "occasion", "concept", "why", "demand",
                     "demand_evidence", "competition", "competition_evidence", "gift_fit",
                     "ip_check", "sources"],
        "properties": {
            "id": {"type": "string", "description": "lowercase-with-dashes, e.g. papas-keepers-mug"},
            "name": {"type": "string", "description": "Short name John will recognize"},
            "line": {"type": "string", "enum": theme_ids, "description": "The theme id it belongs to"},
            "product": {"type": "string", "enum": list(cfg["products"]["allowed"])},
            "occasion": {"type": "string"},
            "concept": {"type": "string", "description": "What the design shows and where the names go, in 1-2 sentences"},
            "why": {"type": "string", "description": "Why it should sell, in 1-2 sentences"},
            "demand": {"type": "integer", "description": "1-5"},
            "demand_evidence": {"type": "string"},
            "competition": {"type": "integer", "description": "1-5, where 5 = few good listings for this exact angle"},
            "competition_evidence": {"type": "string"},
            "gift_fit": {"type": "integer", "description": "1-5"},
            "ip_check": {"type": "string", "description": "Phrases checked and any trademark worry"},
            "sources": {"type": "array", "items": source, "description": "Pages you actually read"},
            "listing": listing,
        },
    }
    return {
        "type": "object", "additionalProperties": False, "required": ["summary", "ideas"],
        "properties": {
            "summary": {"type": "string", "description": "3-5 sentences: what's trending this week and what you'd make first"},
            "ideas": {"type": "array", "items": idea},
        },
    }


RULES = """You research new product ideas for Dinner Bell Co, a brand-new Etsy shop that sells \
personalized family gifts printed on demand by Printify. The owner, John, picks which ideas move \
forward; nothing is made or listed without his OK.

What sells for this shop: heartfelt family gifts with the recipient's people on them, mostly bought \
by grown kids, grandkids and spouses. The model design is "Papa Caught His Limit": an 11oz mug with each \
grandkid's name on a fish, bought for the grandpa who fishes. Aim for that feeling: warm, a little \
funny, never mean.

Rules you must follow:
- Original ideas only. Use other listings to judge demand and competition, never to copy a design, phrase or layout.
- No trademarks, brands, sports teams, franchises (Star Wars, Star Trek, Lord of the Rings, Marvel, Disney...), \
characters, celebrities, song lyrics, movie quotes or other sellers' slogans. A theme can be in a fandom's spirit \
(space, fantasy quests), never use its names, characters, ships, places or quotes. Check coined phrases against \
USPTO trademark search results or news of trademark disputes, and say what you checked.
- No profanity, no politics, nothing racist or crude. Never use the word "gang" (say crew or buddies).
- Personalization is the point: names, years or nicknames the buyer types in. At most 5 boxes per listing.
- US buyers. Prices are fixed by the shop; don't suggest prices.

How to work: search Etsy (bestsellers, reviews, how many listings target the angle), Google/Pinterest trends \
and gift guides. Score each idea 1-5 on demand, competition (5 = wide open) and gift fit, with one line of \
evidence for each. Cite the pages you read."""


def build_brief(cfg: dict, products: dict, themes: list[dict], today: dt.date, feedback: str,
                kept: list[str], recent: list[str], banned_terms: list[banned.Term], example: str) -> str:
    run = cfg["run"]
    theme_lines = "\n".join(
        f"- {t['id']}: {t['theme']}. Bought by {t.get('buyers') or 'families'}."
        + (f" Angles: {t['angles']}." if t.get("angles") else "")
        + (f" Products: {', '.join(t['products'])}." if t["products"] else "")
        for t in themes)
    allowed = "\n".join(
        f"- {p}: {products[p]['title_noun']} {products[p].get('size_label', '')}" if p in products else f"- {p}"
        for p in cfg["products"]["allowed"])
    focus = cfg.get("focus", {})
    blocked = ", ".join(sorted({t.phrase for t in banned_terms if t.level == "block"}))
    listing_ask = (f"For your best {run['drafted']} ideas also fill in \"listing\", written the way this "
                   f"approved example is:\n<example>\n{example.strip()}\n</example>"
                   if run.get("drafted") else
                   "Leave out \"listing\": John picks the ideas first, and listings are written after that.")
    return f"""{RULES}

Today is {today:%A %B %d, %Y}. Find {run['ideas']} new product ideas for this week.

Focus: {focus.get('text', '')}
Evergreen occasions that also count: {", ".join(focus.get('evergreen', []))}.

Themes (from John's sheet; use the id as "line", spread the ideas across them, more where demand is strongest):
{theme_lines}

Products you may suggest:
{allowed}
{cfg['products'].get('note', '')}

John's notes on what he wants (follow these):
<feedback>
{feedback.strip() or "(none yet)"}
</feedback>

Ideas John already kept (don't repeat them): {", ".join(kept) or "none"}
Ideas suggested in recent weeks (don't repeat them): {", ".join(recent) or "none"}

Never use these words or phrases anywhere (trademark or house rules): {blocked}

{listing_ask}"""


class Inputs:
    """Everything one week's research needs, loaded once."""

    def __init__(self, root: Path, today: dt.date, inbox: Path, config_dir: Path | None = None,
                 banned_path: Path | None = None, themes_file: Path | None = None):
        self.root, self.today, self.inbox = root, today, inbox
        config_dir = config_dir or root / "config"
        self.cfg = config.load_toml(config_dir / "research.toml")
        self.products = config.products(config_dir)
        self.shop = config.shop(config_dir)
        self.terms = banned.load(banned_path or root / "data" / "banned_terms.txt")
        self.themes, self.themes_from = load_themes(root, self.cfg, themes_file)
        self.week = week_id(today)
        self.out_dir = inbox / self.week
        feedback_file = root / "ideas" / "feedback.md"
        feedback = feedback_file.read_text(encoding="utf-8") if feedback_file.exists() else ""
        kept = sorted(p.stem for p in (root / "ideas").glob("*.toml"))
        example = (root / "ideas" / "papas-keepers-mug.toml").read_text(encoding="utf-8")
        self.brief = build_brief(self.cfg, self.products, self.themes, today, feedback, kept,
                                 recent_names(inbox, self.week), self.terms, example)
        self.schema = answer_schema(self.cfg, [t["id"] for t in self.themes])


# ---------------------------------------------------------------- the Anthropic API engine

def submit_tool(schema: dict) -> dict:
    return {"name": SUBMIT, "eager_input_streaming": True, "input_schema": schema,
            "description": "Hand in this week's idea list. Call it exactly once, when the research is done."}


def _usage_add(total: dict, usage) -> None:
    if usage is None:
        return
    for key in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
        total[key] = total.get(key, 0) + (getattr(usage, key, 0) or 0)
    stu = getattr(usage, "server_tool_use", None)
    total["web_search_requests"] = total.get("web_search_requests", 0) + (getattr(stu, "web_search_requests", 0) or 0)


def estimate_cost(usage: dict, run: dict) -> float:
    m = 1_000_000
    return round(
        usage.get("input_tokens", 0) * run["price_input"] / m
        + usage.get("cache_creation_input_tokens", 0) * run["price_input"] * 1.25 / m
        + usage.get("cache_read_input_tokens", 0) * run["price_cache_read"] / m
        + usage.get("output_tokens", 0) * run["price_output"] / m
        + usage.get("web_search_requests", 0) * run["price_search"], 2)


def ask_claude(client, run: dict, brief: str, schema: dict) -> tuple[dict, dict, list]:
    """Run the research conversation. Returns (submitted answer, usage totals, raw content blocks)."""
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": run["max_searches"]},
             submit_tool(schema)]
    prompt = f"Do this week's research, then call {SUBMIT} once."
    messages: list[dict] = [{"role": "user", "content": prompt}]
    usage: dict = {}
    raw: list = []
    nudged = False
    for _ in range(run["max_continuations"] + 2):
        try:
            with client.beta.messages.stream(
                model=run["model"], max_tokens=run["max_tokens"], system=brief, messages=messages,
                tools=tools, thinking={"type": "adaptive"}, output_config={"effort": run["effort"]},
                cache_control={"type": "ephemeral"}, betas=[FALLBACK_BETA], fallbacks="default",
            ) as stream:
                msg = stream.get_final_message()
        except ValueError as e:      # the idea list came back as JSON that can't be read at all
            raise ResearchError(f"Claude's idea list couldn't be read ({e}); run it again with --force") from e
        _usage_add(usage, msg.usage)
        raw.extend(b.to_dict() if hasattr(b, "to_dict") else b for b in msg.content)
        if msg.stop_reason == "refusal":
            raise ResearchError("Claude declined the research request (refusal); nothing was written")
        call = next((b for b in msg.content if b.type == "tool_use" and b.name == SUBMIT), None)
        if call is not None:
            if msg.stop_reason == "max_tokens":
                raise ResearchError("the idea list was cut off (max_tokens); raise run.max_tokens in config/research.toml")
            return dict(call.input), usage, raw
        if msg.stop_reason == "max_tokens":
            raise ResearchError("Claude ran out of room before handing in ideas; raise run.max_tokens")
        messages.append({"role": "assistant", "content": msg.content})
        if msg.stop_reason == "pause_turn":
            continue                 # long search: the API resumes from the trailing assistant turn
        if nudged:
            break
        messages.append({"role": "user", "content": f"Please hand in the list now with {SUBMIT}."})
        nudged = True
    raise ResearchError("Claude finished without handing in an idea list")


def make_client():
    try:
        import anthropic
    except ImportError as e:
        raise ResearchError("the anthropic package isn't installed: python3 -m pip install --user anthropic") from e
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ResearchError(f"ANTHROPIC_API_KEY is not set in {config.env_file()} (docs/keys.md #6)")
    return anthropic.Anthropic(max_retries=4, timeout=900)


# ---------------------------------------------------------------- checking an answer

def score(idea: dict, weights: dict) -> int:
    def clamp(v):
        try:
            return min(5, max(1, int(v)))
        except (TypeError, ValueError):
            return 1
    keys = ("demand", "competition", "gift_fit")
    return round(sum(weights[k] * clamp(idea.get(k)) for k in keys) / sum(weights[k] for k in keys) / 5 * 100)


def seen_urls(raw: list) -> set[str]:
    """Every URL that appeared in a search result, to mark sources Claude didn't actually see."""
    urls: set[str] = set()

    def walk(x):
        if isinstance(x, dict):
            if isinstance(x.get("url"), str):
                urls.add(x["url"].rstrip("/"))
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk([b for b in raw if isinstance(b, dict) and b.get("type") not in ("tool_use", "text")])
    return urls


def validate(data: dict, inp: Inputs) -> list[dict]:
    """Clean up an answer: flag malformed ideas, score, screen banned terms. Best first."""
    if not isinstance(data, dict) or not isinstance(data.get("ideas"), list):
        raise ResearchError("the answer has no idea list")
    themes = {t["id"] for t in inp.themes}
    out, ids = [], set()
    for raw in data["ideas"]:
        if not isinstance(raw, dict):
            continue
        idea = dict(raw)
        problems = []
        idea["id"] = slug(idea.get("id", "")) or slug(idea.get("name", "")) or "idea"
        while idea["id"] in ids:
            idea["id"] += "-2"
        ids.add(idea["id"])
        if idea.get("line") not in themes:
            problems.append(f"theme {idea.get('line')!r} isn't an active row in the themes sheet")
        if idea.get("product") not in inp.cfg["products"]["allowed"]:
            problems.append(f"product {idea.get('product')!r} isn't on the list")
        for key in ("name", "concept", "why", "occasion"):
            idea[key] = str(idea.get(key) or "")
        idea["score"] = score(idea, inp.cfg["score"])
        kind = inp.products.get(idea.get("product"), {}).get("kind", "apparel" if idea.get("product") != "mug11" else "mug")
        lst = idea.get("listing") if isinstance(idea.get("listing"), dict) else None
        fields = {"name": idea["name"], "concept": idea["concept"]}
        if lst:
            fields.update(design_text=" | ".join(map(str, lst.get("design_text", []))), title=str(lst.get("title", "")),
                          tags=" | ".join(map(str, lst.get("keywords", []))), motif=str(lst.get("motif", "")))
        hits = banned.scan(inp.terms, kind, fields)
        if checks.GANG.search(" ".join(fields.values())):
            problems.append('uses "gang"')
        idea["blocked"] = [f"{h.term.phrase} ({h.field}): {h.term.why}" for h in hits if h.term.level == "block"]
        idea["caution"] = [f"{h.term.phrase} ({h.field}): {h.term.why}" for h in hits if h.term.level == "caution"]
        idea["problems"] = problems
        idea["listing"] = lst
        idea["sources"] = [s for s in idea.get("sources") or [] if isinstance(s, dict)]
        out.append(idea)
    out.sort(key=lambda i: (bool(i["blocked"] or i["problems"]), -i["score"]))   # blocked ones last
    return out


def to_idea_file(idea: dict, inp: Inputs) -> dict:
    """The drafter's idea format (ideas/papas-keepers-mug.toml), from the listing fields."""
    lst = idea["listing"]
    section = next((t.get("section", "") for t in inp.themes if t["id"] == idea["line"]), "")
    out = {
        "id": idea["id"], "line": idea["line"], "product": idea["product"], "section": section,
        "recipient": lst["recipient"], "recipient_alt": lst.get("recipient_alt", ""),
        "theme": lst.get("theme", ""), "motif": lst.get("motif", ""),
        "design_text": list(lst.get("design_text", [])),
        "title": lst.get("title", ""), "primary_keyword": lst.get("primary_keyword", ""),
        "keywords": list(lst.get("keywords", [])),
        "opening": lst["opening"], "order_emoji": lst.get("order_emoji") or "✏️",
        "how_to_order": list(lst.get("how_to_order", [])),
        "concept": idea["concept"],
        "attributes": {k: v for k, v in (("holiday", lst.get("holiday")), ("occasion", lst.get("occasion")),
                                          ("recipient", lst.get("recipient_attribute"))) if v},
        "personalization": [
            {k: v for k, v in (("repeat", int(p.get("repeat") or 1)), ("question", p["question"]),
                                ("instructions", p.get("instructions", "")), ("max_chars", int(p["max_chars"])))
             if not (k == "repeat" and v == 1)}
            for p in lst.get("personalization", [])],
    }
    return {k: v for k, v in out.items() if v not in ("", [], {})}


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)        # JSON strings are valid TOML basic strings


def to_toml(idea: dict, header: str = "") -> str:
    lines = [f"# {line}" for line in header.splitlines()]
    is_tables = lambda v: isinstance(v, list) and v and isinstance(v[0], dict)
    lines += [f"{k} = {_toml_value(v)}" for k, v in idea.items() if not isinstance(v, dict) and not is_tables(v)]
    for k, v in idea.items():
        if isinstance(v, dict):
            lines += ["", f"[{k}]"] + [f"{kk} = {_toml_value(vv)}" for kk, vv in v.items()]
    for k, v in idea.items():
        if is_tables(v):
            for item in v:
                lines += ["", f"[[{k}]]"] + [f"{kk} = {_toml_value(vv)}" for kk, vv in item.items()]
    return "\n".join(lines) + "\n"


def draft_one(idea: dict, inp: Inputs, out_dir: Path) -> dict | None:
    """Write <id>.toml and drafts/<id>.json + .md for an idea with listing fields. None if it can't."""
    if idea["product"] not in inp.products:
        idea["problems"].append(f"no listing template for {idea['product']} yet (needs specs and John's price)")
        return None
    idea_file = to_idea_file(idea, inp)
    try:
        d = drafter.draft(idea_file, inp.products, inp.shop, inp.today)
    except (drafter.IdeaError, KeyError, ValueError, TypeError) as e:
        idea["problems"].append(f"couldn't draft it: {e}")
        return None
    issues = checks.run(d, inp.shop, inp.terms, drafter.holiday_active(inp.shop, inp.today))
    errors = [i for i in issues if i.level == "error"]
    header = (f"Suggested by the weekly idea research, {inp.week}. Score {idea['score']}/100.\n"
              f"Not approved yet: it becomes a kept idea when it moves to ideas/.")
    (out_dir / f"{idea['id']}.toml").write_text(to_toml(idea_file, header), encoding="utf-8")
    drafts = out_dir / "drafts"
    drafts.mkdir(exist_ok=True)
    (drafts / f"{d['id']}.json").write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    from .cli import render_markdown           # one renderer for every draft
    (drafts / f"{d['id']}.md").write_text(render_markdown(d, issues), encoding="utf-8")
    return {
        "title": d["title"], "tags": d["tags"],
        "verdict": "passed (needs John's OK)" if not errors else f"{len(errors)} problem(s) to fix before listing",
        "notes": [f"{i.field}: {i.message}" for i in errors]
                 + [f"{i.field}: {i.message}" for i in issues if i.level == "warning" and i.field != "specs"],
    }


def render_report(inp: Inputs, summary: str, ideas: list[dict], drafted: dict, cost_line: str) -> str:
    L = [f"Dinner Bell Co idea research, week {inp.week} ({inp.today:%b %d, %Y})",
         f"Focus: {inp.cfg.get('focus', {}).get('text', '')}",
         f"Themes ({inp.themes_from}): {', '.join(t['theme'] for t in inp.themes)}", "", summary.strip(), ""]
    if drafted:
        L += ["DRAFTED LISTINGS (waiting for your OK)", ""]
        for idea in (i for i in ideas if i["id"] in drafted):
            d = drafted[idea["id"]]
            L += [f"- {idea['name']} [{idea['id']}]", f"  Title: {d['title']}",
                  f"  Tags: {', '.join(d['tags'])}", f"  Checks: {d['verdict']}"]
            L += [f"  ⚠️ {w}" for w in d["notes"]]
        L.append("")
    L += ["IDEAS (best first)", ""]
    for n, idea in enumerate(ideas, 1):
        flag = " ⛔ BLOCKED" if idea["blocked"] or idea["problems"] else ""
        L += [f"{n}. {idea['name']}  {idea['score']}/100{flag}",
              f"   {idea.get('product', '?')} · {idea.get('line', '?')} · {idea['occasion']}",
              f"   Design: {idea['concept']}",
              f"   Why: {idea['why']}",
              f"   Demand {idea.get('demand')}/5: {idea.get('demand_evidence', '')}",
              f"   Competition {idea.get('competition')}/5: {idea.get('competition_evidence', '')}",
              f"   Gift fit {idea.get('gift_fit')}/5 · IP: {idea.get('ip_check', '')}"]
        L += [f"   ⛔ {b}" for b in idea["blocked"] + idea["problems"]]
        L += [f"   ⚠️ {c}" for c in idea["caution"]]
        for s in idea["sources"][:4]:
            mark = "" if s.get("seen", True) else "  (not in the search results: check it)"
            L.append(f"   - {s.get('title', '')}: {s.get('url', '')}{mark}")
        L.append("")
    L += ["HOW TO PICK",
          "Tell Claude in the Etsy project which ideas to move forward (by number or name).",
          "Claude writes their listings and adds them to ideas/ in the repo. Nothing gets made,",
          "listed or ordered until you say so."]
    if cost_line:
        L += ["", cost_line]
    return "\n".join(L) + "\n"


def ingest(data: dict, inp: Inputs, engine: str, raw: list | None = None, usage: dict | None = None,
           cost: float | None = None) -> dict:
    """Check an answer and write this week's files. Returns the result (with the report as an email)."""
    ideas = validate(data, inp)
    if raw:
        seen = seen_urls(raw)
        for idea in ideas:
            for s in idea["sources"]:
                s["seen"] = str(s.get("url", "")).rstrip("/") in seen if seen else True
    out_dir = inp.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        (out_dir / "raw.json").write_text(json.dumps({"brief": inp.brief, "content": raw, "usage": usage},
                                                     ensure_ascii=False, default=str), encoding="utf-8")
    drafted: dict[str, dict] = {}
    for idea in ideas:
        if len(drafted) >= inp.cfg["run"].get("drafted", 0):
            break
        if idea["listing"] and not idea["blocked"] and not idea["problems"]:
            if (d := draft_one(idea, inp, out_dir)):
                drafted[idea["id"]] = d
    summary = str(data.get("summary", ""))
    usage = usage or {}
    cost_line = ""
    if cost is not None:
        cost_line = (f"Cost of this run: about ${cost:.2f} ({usage.get('web_search_requests', 0)} searches, "
                     f"{usage.get('output_tokens', 0):,} tokens written).")
    (out_dir / "ideas.json").write_text(json.dumps(
        {"week": inp.week, "engine": engine, "summary": summary, "ideas": ideas}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    report = render_report(inp, summary, ideas, drafted, cost_line)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    blocked = sum(1 for i in ideas if i["blocked"] or i["problems"])
    return {"ok": True, "week": inp.week, "engine": engine, "ideas": len(ideas), "blocked": blocked,
            "drafted": list(drafted), "dir": str(out_dir), "report": report,
            "subject": f"Dinner Bell Co: {len(ideas)} new ideas for week {inp.week}"}


# ---------------------------------------------------------------- dbc research (API engine)

def run(client_factory, inp: Inputs, alert_to: str, alert_from: str, force: bool = False) -> dict:
    result = {"ok": True, "command": "research", "week": inp.week, "skipped": False, "ideas": 0,
              "drafted": [], "cost_usd": 0.0, "usage": {}, "dir": str(inp.out_dir), "error": None,
              "email": {"send": False}}
    if (inp.out_dir / "report.md").exists() and not force:
        result.update(skipped=True, note=f"week {inp.week} already researched; use --force to run it again")
        return result
    email = {"send": True, "to": alert_to, "from": alert_from or alert_to}
    try:
        data, usage, raw = ask_claude(client_factory(), inp.cfg["run"], inp.brief, inp.schema)
        cost = estimate_cost(usage, inp.cfg["run"])
        done = ingest(data, inp, "anthropic-api", raw=raw, usage=usage, cost=cost)
    except ResearchError as e:
        result.update(ok=False, error=str(e))
        result["email"] = {**email, "subject": "Dinner Bell Co: idea research didn't finish",
                           "text": f"This week's idea research ({inp.week}) stopped:\n\n{e}\n\n"
                                   f"Nothing was written. Run it again from n8n, or tell Claude.\n"}
        return result
    result.update(ideas=done["ideas"], drafted=done["drafted"], cost_usd=cost, usage=usage)
    result["email"] = {**email, "subject": done["subject"], "text": done["report"]}
    return result


def check(client_factory, model: str) -> dict:
    """Free check that the key works and the model is reachable (no tokens used)."""
    out = {"ok": True, "command": "research-check", "model": model, "error": None}
    try:
        info = client_factory().models.retrieve(model)
        out["model_name"] = getattr(info, "display_name", model)
    except ResearchError as e:
        out.update(ok=False, error=str(e))
    except Exception as e:      # noqa: BLE001 - any API error is reported, never the key
        out.update(ok=False, error=f"{type(e).__name__}: {str(getattr(e, 'message', e))[:300]}")
    return out
