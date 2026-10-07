"""Command line.

    python -m dbc draft ideas/papas-keepers-mug.toml     # idea -> drafts/<id>.json + .md
    python -m dbc check drafts/papas-keepers-mug.json    # re-check a hand-edited draft
    python -m dbc --json draft ideas/x.toml              # one JSON object on stdout, for n8n
    python -m dbc printify-check                         # is the Printify token working? which shop?
    python -m dbc --json watch-orders                    # held orders, reminders, problems (read-only)
    python -m dbc --json update                          # nightly: fast-forward to what was merged on GitHub
    python -m dbc --json research                        # weekly idea research (Anthropic API, costs money)
    python -m dbc research-check                         # is the Anthropic key working? (free)
    python -m dbc themes                                 # which themes the research reads, and the sheet's CSV link
    python -m dbc themes --themes sheet.csv              # check a downloaded copy of the sheet, list what changed
    python -m dbc themes --lingo                         # also print each theme's lingo (context for art prompts)
    python -m dbc research-brief                         # this week's research instructions (any engine)
    python -m dbc art-log add limit-r02-B --prompt art/prompts/limit-r02-B.md   # log an art image (docs/art-log.md)
    python -m dbc art-log set limit-r02-B decision=keep                         # keep, redo or drop
    python -m dbc research-ingest answer.json            # check an answer, write ideas/inbox/<week>/report.md

Exit code 1 when any check fails (with --json the exit code is 0 and "ok" says it). Nothing here publishes or orders.
Keys come from ~/.config/dinnerbellco/.env or /etc/dinnerbellco/.env (DBC_ENV_FILE overrides); see docs/keys.md.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

from . import artlog, banned, checks, config, drafter, printify, research, updater, watcher


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


def cmd_printify_check(args) -> int:
    """Read-only token check: lists the shops the token sees and the one the watcher would use."""
    out = {"ok": True, "command": "printify-check", "shops": [], "watching": None, "note": "", "error": None}
    try:
        client = printify.Client(os.environ.get("PRINTIFY_TOKEN", ""))
        shops = client.shops()
        out["shops"] = [{k: s.get(k) for k in ("id", "title", "sales_channel")} for s in shops]
        shop, out["note"] = printify.pick_shop(shops, os.environ.get("PRINTIFY_SHOP_ID") or None)
        out["watching"] = shop and {"id": shop.get("id"), "title": shop.get("title")}
    except printify.PrintifyError as e:
        out.update(ok=False, error=str(e))
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
        return 0
    if not out["ok"]:
        print(f"error: {out['error']}")
        return 1
    print(f"token works; {len(out['shops'])} shop(s) in Printify")
    for s in out["shops"]:
        print(f"  {s['id']}  {s['title']}  ({s['sales_channel']})")
    print(f"watching: {out['watching']['title']}" if out["watching"] else out["note"])
    return 0


def cmd_watch_orders(args) -> int:
    if not args.dry_run and not os.environ.get("ALERT_EMAIL_TO"):
        # A config crash (non-zero exit) so n8n's error workflow tells John, instead of silent alerts.
        print(f"error: ALERT_EMAIL_TO is not set in {config.env_file()} (see .env.example)", file=sys.stderr)
        return 2
    now = dt.datetime.fromisoformat(args.now) if args.now else dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    state = args.state or config.state_dir() / "watch-orders.json"
    result = watcher.run(printify.Client, config.shop(args.config), state, now, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
        return 0
    print(f"{result['orders_checked']} recent order(s), {result['on_hold']} on hold, "
          f"{len(result['alerts'])} new alert(s){' (dry run: nothing remembered)' if args.dry_run else ''}")
    for note in result["notes"]:
        print(f"  note: {note}")
    if result["error"]:
        print(f"  error: {result['error']}")
    if result["email"]["send"]:
        print(f"\nSubject: {result['email']['subject']}\n\n{result['email']['text']}")
    return 0 if result["ok"] else 1


def _need_alert_email() -> int | None:
    if os.environ.get("ALERT_EMAIL_TO"):
        return None
    # A config crash (non-zero exit) so n8n's error workflow tells John, instead of silent alerts.
    print(f"error: ALERT_EMAIL_TO is not set in {config.env_file()} (see .env.example)", file=sys.stderr)
    return 2


def _print_email(result: dict) -> None:
    if result["email"]["send"]:
        print(f"\nSubject: {result['email']['subject']}\n\n{result['email']['text']}")


def cmd_update(args) -> int:
    if not args.dry_run and (code := _need_alert_email()):
        return code
    result = updater.run(config.ROOT, os.environ.get("ALERT_EMAIL_TO", ""),
                         os.environ.get("ALERT_EMAIL_FROM", ""), dry_run=args.dry_run)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if result["error"]:
        print(f"error: {result['error']}")
    elif not result["commits"]:
        print(f"up to date at {result['before']}")
    else:
        verb = "would update" if args.dry_run else "updated"
        print(f"{verb} {result['before']} -> {result['after']}: {len(result['commits'])} commit(s)")
        _print_email(result)
    return 0 if result["ok"] else 1


def _inputs(args) -> research.Inputs:
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    return research.Inputs(config.ROOT, today, args.inbox, config_dir=args.config, banned_path=args.banned,
                           themes_file=getattr(args, "themes", None))


def cmd_research(args) -> int:
    if (code := _need_alert_email()):
        return code
    result = research.run(research.make_client, _inputs(args), os.environ["ALERT_EMAIL_TO"],
                          os.environ.get("ALERT_EMAIL_FROM", ""), force=args.force)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if result["skipped"]:
        print(result["note"])
    elif result["error"]:
        print(f"error: {result['error']}")
    else:
        print(f"{result['ideas']} ideas, {len(result['drafted'])} drafted, about ${result['cost_usd']:.2f}; "
              f"report: {result['dir']}/report.md")
    return 0 if result["ok"] else 1


def cmd_research_brief(args) -> int:
    """For any research engine (e.g. a Claude routine): the instructions and the answer format."""
    inp = _inputs(args)
    if args.json:
        print(json.dumps({"week": inp.week, "dir": str(inp.out_dir), "themes_from": inp.themes_from,
                          "brief": inp.brief, "schema": inp.schema}, ensure_ascii=False))
        return 0
    print(f"{inp.brief}\n\nHand in one JSON object that matches this JSON Schema, saved to a file, "
          f"then run: python3 -m dbc research-ingest <file>\n\n{json.dumps(inp.schema, indent=1)}")
    return 0


def cmd_research_ingest(args) -> int:
    inp = _inputs(args)
    try:
        data = json.loads(Path(args.answer).read_text(encoding="utf-8"))
        result = research.ingest(data, inp, args.engine)
    except (OSError, ValueError, research.ResearchError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(result["report"])
        print(f"({result['ideas']} ideas, {result['blocked']} blocked; files in {result['dir']})")
    return 0


def cmd_themes(args) -> int:
    """Which themes the research will use. With --themes, checks a downloaded copy of John's sheet and
    lists what it changed compared with config/themes.csv."""
    cfg = config.load_toml(args.config / "research.toml")
    url = cfg.get("themes", {}).get("sheet_csv_url", "")
    try:
        themes, where = research.load_themes(config.ROOT, cfg, args.themes)
        repo, _ = research.load_themes(config.ROOT, {"themes": {"file": cfg.get("themes", {}).get("file", "config/themes.csv")}})
        terms = banned.load(config.ROOT / "data" / "banned_terms.txt")
    except (OSError, UnicodeDecodeError, research.ResearchError) as e:
        print(json.dumps({"ok": False, "error": str(e)}) if args.json else f"error: {e}")
        return 0 if args.json else 1
    result = {"ok": True, "from": where, "sheet_url": url, "csv_url": research.sheet_csv_url(url) if url else "",
              "themes": [{"theme": t["theme"], "products": t["products"],
                          "lingo": len(research.parse_lingo(t.get("lingo", ""))),
                          "lingo_blocked": research.screen_lingo(research.parse_lingo(t.get("lingo", "")), terms)[1]}
                         for t in themes],
              "changes": research.theme_changes(themes, repo) if args.themes else []}
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
        return 0
    print(f"{len(themes)} active themes from {where}:")
    for t in themes:
        print(f"  {t['theme']} ({', '.join(t['products']) or 'any product'}; {len(research.parse_lingo(t.get('lingo', '')))} lingo terms)")
        if args.lingo:
            for x in research.parse_lingo(t.get("lingo", "")):
                print(f"      {x['term']}" + (f": {x['meaning']}" if x["meaning"] else ""))
    for t in result["themes"]:
        for d in t["lingo_blocked"]:
            print(f"  ⛔ remove from {t['theme']} lingo: {d}")
    if url:
        print(f"Google Sheet CSV link: {result['csv_url']}")
    for line in result["changes"]:
        print(f"  {line}")
    return 0


def cmd_art_log(args) -> int:
    try:
        if args.action == "add":
            row = artlog.add(args.id, prompt=args.prompt or "", image=args.image or "",
                             check=artlog.load_check(args.check), parent=args.parent or "")
            rows = [row]
        elif args.action == "set":
            rows = [artlog.set_fields(args.id, args.pairs)]
        else:
            rows = artlog.read()
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(rows, ensure_ascii=False))
        return 0
    for r in rows:
        check = r["check"].split(";")[0] or "not checked"
        print(f"{r['id']}  {r['decision'] or 'undecided'}  {check}  {r['notes']}".rstrip())
    return 0


def cmd_research_check(args) -> int:
    model = config.load_toml(args.config / "research.toml")["run"]["model"]
    result = research.check(research.make_client, model)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
        return 0
    print(f"Anthropic key works; {result['model_name']} is available" if result["ok"] else f"error: {result['error']}")
    return 0 if result["ok"] else 1


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
    pc = sub.add_parser("printify-check", help="check the Printify token and list its shops (read-only)")
    pc.set_defaults(func=cmd_printify_check)
    w = sub.add_parser("watch-orders", help="held orders, 18-hour reminders and problems (read-only)")
    w.add_argument("--state", type=Path, help="state file (default: $DBC_STATE_DIR/watch-orders.json)")
    w.add_argument("--dry-run", action="store_true", help="don't remember what was alerted")
    w.add_argument("--now", help="pretend time, ISO 8601 (for tests)")
    w.set_defaults(func=cmd_watch_orders)
    u = sub.add_parser("update", help="fast-forward the server's code to what was merged on GitHub")
    u.add_argument("--dry-run", action="store_true", help="fetch and say what would change, change nothing")
    u.set_defaults(func=cmd_update)
    inbox = config.ROOT / "ideas" / "inbox"
    r = sub.add_parser("research", help="weekly idea research through the Anthropic API (needs a key, costs money)")
    r.add_argument("--inbox", type=Path, default=inbox)
    r.add_argument("--force", action="store_true", help="run again even if this week is done")
    r.set_defaults(func=cmd_research)
    th = sub.add_parser("themes", help="which themes the research reads (checks a downloaded copy of the sheet)")
    th.add_argument("--themes", type=Path, help="a downloaded copy of the themes sheet to check")
    th.add_argument("--lingo", action="store_true", help="also print each theme's lingo (context for prompts)")
    th.set_defaults(func=cmd_themes)
    rb = sub.add_parser("research-brief", help="this week's research instructions and answer format")
    rb.add_argument("--inbox", type=Path, default=inbox)
    rb.add_argument("--themes", type=Path, help="themes CSV to use instead of config/themes.csv or the sheet")
    rb.set_defaults(func=cmd_research_brief)
    ri = sub.add_parser("research-ingest", help="check a research answer and write this week's report")
    ri.add_argument("answer", type=Path)
    ri.add_argument("--inbox", type=Path, default=inbox)
    ri.add_argument("--themes", type=Path, help="themes CSV to use instead of config/themes.csv or the sheet")
    ri.add_argument("--engine", default="claude-routine")
    ri.set_defaults(func=cmd_research_ingest)
    al = sub.add_parser("art-log", help="log of art images: prompt, image, check, decision (art/log.csv)")
    al_sub = al.add_subparsers(dest="action", required=True)
    aa = al_sub.add_parser("add", help="add an image (or fill in one already logged)")
    aa.add_argument("id", help="design-r<round>-<variant>, e.g. limit-r02-B; a redo is limit-r02-B2")
    aa.add_argument("--prompt", help="the prompt file in the repo, e.g. art/prompts/limit-r02-B.md")
    aa.add_argument("--image", help="the image in the project folder, e.g. designs/limit/round-02/limit-r02-B.png")
    aa.add_argument("--check", type=Path, help="the image checker's <id>_check.json")
    aa.add_argument("--parent", help="the image this one builds on (a redo's parent is filled in for you)")
    asg = al_sub.add_parser("set", help="set fields: decision=keep|redo|drop notes=... check=...")
    asg.add_argument("id")
    asg.add_argument("pairs", nargs="+", metavar="name=value")
    al_sub.add_parser("show", help="list the log")
    al.set_defaults(func=cmd_art_log)
    rc = sub.add_parser("research-check", help="check the Anthropic key without spending anything")
    rc.set_defaults(func=cmd_research_check)
    args = p.parse_args(argv)
    config.load_env()
    try:
        return args.func(args)
    except drafter.IdeaError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
