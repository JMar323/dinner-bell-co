"""Command line.

    python -m dbc draft ideas/papas-keepers-mug.toml     # idea -> drafts/<id>.json + .md
    python -m dbc check drafts/papas-keepers-mug.json    # re-check a hand-edited draft
    python -m dbc --json draft ideas/x.toml              # one JSON object on stdout, for n8n

Exit code 1 when any check fails (with --json the exit code is 0 and "ok" says it). Nothing here publishes or orders.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from . import banned, checks, config, drafter


def render_markdown(d: dict, issues: list[checks.Issue]) -> str:
    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]
    verdict = "FAILED checks" if errors else "passed checks (needs John's OK)"
    lines = [
        f"# Draft: {d['id']}",
        "",
        f"**{verdict}** · {d['product']} · ${d['price']:.2f} ({d['price_status']}) · drafted {d['drafted_on']}",
        "",
        f"## Title ({len(d['title'])} characters, {len(d['title'].split())} words)",
        "",
        d["title"],
        "",
        f"## Tags ({len(d['tags'])})",
        "",
        " · ".join(f"`{t}`" for t in d["tags"]),
        "",
        "## Personalization",
        "",
        "| # | Question | Instructions | Max |",
        "|---|---|---|---|",
    ]
    for n, f in enumerate(d["personalization"], 1):
        lines.append(f"| {n} | {f['question']} | {f['instructions']} | {f['max_chars']} |")
    lines += ["", "## Description", "", d["description"], "", "## Settings", ""]
    lines += [f"- {k.replace('_', ' ')}: {v}" for k, v in {**d["settings"], **d["attributes"]}.items()]
    lines += ["", "## Checks", ""]
    lines += [f"- ❌ {i.field}: {i.message}" for i in errors]
    lines += [f"- ⚠️ {i.field}: {i.message}" for i in warnings]
    if not issues:
        lines.append("- ✅ no issues")
    return "\n".join(lines) + "\n"


def report(d: dict, issues: list[checks.Issue], as_json: bool = False, **extra) -> int:
    errors = [i for i in issues if i.level == "error"]
    if as_json:
        # One JSON object on stdout, for n8n's Execute Command node to parse.
        print(json.dumps({
            "id": d["id"],
            "ok": not errors,
            "errors": [{"field": i.field, "message": i.message} for i in errors],
            "warnings": [{"field": i.field, "message": i.message} for i in issues if i.level == "warning"],
            **extra,
        }, ensure_ascii=False))
    else:
        print(f"{d['id']}: {len(errors)} error(s), {len(issues) - len(errors)} warning(s)")
        for issue in issues:
            print(f"  {issue}")
        for k, v in extra.items():
            print(f"  {k.replace('_', ' ')}: {v}")
    # n8n's Execute Command node treats a non-zero exit as a crash, so JSON mode reports via "ok".
    return 0 if as_json or not errors else 1


def cmd_draft(args) -> int:
    shop = config.shop(args.config)
    idea = config.load_toml(args.idea)
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    d = drafter.draft(idea, config.products(args.config), shop, today)
    issues = checks.run(d, shop, banned.load(args.banned), drafter.holiday_active(shop, today))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{d['id']}.json").write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / f"{d['id']}.md").write_text(render_markdown(d, issues), encoding="utf-8")
    return report(d, issues, args.json, draft=str(out / f"{d['id']}.json"), review=str(out / f"{d['id']}.md"))


def cmd_check(args) -> int:
    shop = config.shop(args.config)
    d = json.loads(Path(args.draft).read_text(encoding="utf-8"))
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    issues = checks.run(d, shop, banned.load(args.banned), drafter.holiday_active(shop, today))
    return report(d, issues, args.json)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="dbc", description="Dinner Bell Co listing tools")
    p.add_argument("--config", type=Path, default=config.CONFIG_DIR)
    p.add_argument("--banned", type=Path, default=config.BANNED_TERMS)
    p.add_argument("--today", help="pretend date, YYYY-MM-DD (for tests)")
    p.add_argument("--json", action="store_true", help="print one JSON object (for n8n)")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draft", help="draft a listing from an idea file")
    d.add_argument("idea", type=Path)
    d.add_argument("--out", default="drafts")
    d.set_defaults(func=cmd_draft)
    c = sub.add_parser("check", help="re-run checks on a draft JSON")
    c.add_argument("draft", type=Path)
    c.set_defaults(func=cmd_check)
    args = p.parse_args(argv)
    try:
        return args.func(args)
    except drafter.IdeaError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
