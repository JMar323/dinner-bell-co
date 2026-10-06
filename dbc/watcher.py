"""Held-order watcher: reads Printify orders and says what John needs to look at.

Three kinds of alert, each emailed once per order:
  held      a new order waiting on hold for John's review in Printify
  reminder  still on hold after reminder_after_hours (we promise a 1-day review)
  problem   has issues, unfulfillable, payment not received or canceled (again if it changes)

It never approves, sends to production, cancels or edits anything: the Printify client is
GET-only. What was already alerted lives in a small JSON state file (DBC_STATE_DIR).
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import printify

HELD = "on-hold"
ORDER_PROBLEMS = {
    "has-issues": "has issues (usually the shipping address): fix it in Printify",
    "unfulfillable": "is unfulfillable (the print provider can't make an item): switch provider or cancel and message the buyer",
    "payment-not-received": "is stuck because Printify couldn't charge the card: check Printify billing",
    "canceled": "was canceled: if you didn't cancel it, the print provider did, so message the buyer",
}
ITEM_PROBLEMS = {"has-issues", "unfulfillable"}
STATE_VERSION = 1


def norm(status) -> str:
    return str(status or "").strip().lower().replace("_", "-").replace(" ", "-")


def parse_time(value) -> dt.datetime | None:
    if not value:
        return None
    try:
        t = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- reading Printify

def collect_orders(client: printify.Client, shop_id, now: dt.datetime,
                   lookback_days: int, max_pages: int) -> list[dict]:
    """Recent orders, newest page first, stopping at a page that is entirely too old.

    Printify's docs don't say which way the list is sorted, so page 1 decides: if it runs
    oldest to newest, walk back from the last page instead.
    """
    cutoff = now - dt.timedelta(days=lookback_days)
    first = client.orders(shop_id, page=1)
    last_page = int(first.get("last_page") or 1)
    times = [t for t in (parse_time(o.get("created_at")) for o in first.get("data") or []) if t]
    oldest_first = len(times) > 1 and times[0] < times[-1]
    pages = list(range(last_page, 0, -1)) if oldest_first and last_page > 1 else list(range(1, last_page + 1))
    out = []
    for page in pages[:max_pages]:
        resp = first if page == 1 else client.orders(shop_id, page=page)
        data = resp.get("data") or []
        recent = [o for o in data if (parse_time(o.get("created_at")) or now) >= cutoff]
        out.extend(recent)
        if not recent:
            break
    return out


def summarize(order: dict, now: dt.datetime) -> dict:
    meta = order.get("metadata") or {}
    created = parse_time(order.get("created_at"))
    items = []
    for li in order.get("line_items") or []:
        m = li.get("metadata") or {}
        items.append({
            "title": m.get("title") or li.get("product_id") or "item",
            "variant": m.get("variant_label") or "",
            "quantity": li.get("quantity") or 1,
            "status": norm(li.get("status")),
        })
    return {
        "order_id": str(order.get("id")),
        "receipt": str(meta.get("shop_order_label") or meta.get("shop_order_id") or ""),
        "status": norm(order.get("status")),
        "created_at": iso(created) if created else None,
        "age_hours": round((now - created).total_seconds() / 3600, 1) if created else None,
        "items": items,
        # Buyer's personalization text needs the Etsy app (docs/plan.md build step 3).
        "personalization": None,
    }


def problems(summary: dict) -> list[str]:
    found = []
    if summary["status"] in ORDER_PROBLEMS:
        found.append(summary["status"])
    for item in summary["items"]:
        if item["status"] in ITEM_PROBLEMS and item["status"] not in found:
            found.append(item["status"])
    return found


# ---------------------------------------------------------------- deciding what to alert

def evaluate(orders: list[dict], state: dict, now: dt.datetime, settings: dict) -> tuple[list[dict], dict]:
    """(alerts, updated state). Pure: no I/O, so the tests drive it directly."""
    remind_after = float(settings.get("reminder_after_hours", 18))
    seen = {k: dict(v) for k, v in (state.get("orders") or {}).items()}
    alerts = []
    for order in orders:
        s = summarize(order, now)
        rec = seen.setdefault(s["order_id"], {})
        rec["last_seen"] = iso(now)
        rec["status"] = s["status"]
        if s["status"] == HELD:
            overdue = s["age_hours"] is not None and s["age_hours"] >= remind_after
            if "held_alerted" not in rec:
                alerts.append({"kind": "held", **s})
                rec["held_alerted"] = iso(now)
                if overdue:                       # first seen late: one email, not two
                    rec["reminded"] = iso(now)
            elif overdue and "reminded" not in rec:
                alerts.append({"kind": "reminder", **s})
                rec["reminded"] = iso(now)
        found = problems(s)
        key = ",".join(found)
        if found and rec.get("problem") != key:
            alerts.append({"kind": "problem", "problems": found, **s})
        if found or "problem" in rec:
            rec["problem"] = key
    keep_after = now - dt.timedelta(days=int(settings.get("lookback_days", 30)) + 7)
    seen = {k: v for k, v in seen.items() if (parse_time(v.get("last_seen")) or now) >= keep_after}
    return alerts, {**state, "version": STATE_VERSION, "orders": seen}


# ---------------------------------------------------------------- the email

def _local(t: str | None, tz: dt.tzinfo) -> str:
    parsed = parse_time(t)
    if not parsed:
        return "unknown time"
    t = parsed.astimezone(tz)   # no %-d: musl (Alpine, n8n's Docker image) doesn't support it
    return f"{t:%a %b} {t.day}, {t.hour % 12 or 12}:{t:%M} {'AM' if t.hour < 12 else 'PM'} {t.tzname()}"


def _order_lines(a: dict, tz: dt.tzinfo) -> list[str]:
    receipt = f"Etsy order #{a['receipt']}" if a["receipt"] else "Order (no Etsy receipt number)"
    age = f", {a['age_hours']:.0f}h ago" if a["age_hours"] is not None else ""
    lines = [f"• {receipt} · Printify order {a['order_id']} · came in {_local(a['created_at'], tz)}{age}"]
    for item in a["items"]:
        variant = f" ({item['variant']})" if item["variant"] else ""
        lines.append(f"    {item['quantity']} × {item['title']}{variant}")
    return lines


def render_email(alerts: list[dict], settings: dict, shop_name: str) -> dict:
    tz = _tz(settings.get("timezone"))
    review_hours = settings.get("review_within_hours", 24)
    held = [a for a in alerts if a["kind"] == "held"]
    reminders = [a for a in alerts if a["kind"] == "reminder"]
    probs = [a for a in alerts if a["kind"] == "problem"]
    parts = []
    if held:
        parts.append(f"{len(held)} new order{'s' if len(held) > 1 else ''} to review")
    if reminders:
        parts.append(f"{len(reminders)} still waiting after {settings.get('reminder_after_hours', 18)}h")
    if probs:
        parts.append(f"{len(probs)} order problem{'s' if len(probs) > 1 else ''}")
    lines = []
    if held:
        lines += [f"NEW ORDERS TO REVIEW (we promise to review within {review_hours} hours)", ""]
        for a in held:
            lines += _order_lines(a, tz)
            lines.append("    Check the buyer's names and spelling in Printify before you approve.")
        lines.append("")
    if reminders:
        lines += [f"STILL ON HOLD AFTER {settings.get('reminder_after_hours', 18)} HOURS", ""]
        for a in reminders:
            lines += _order_lines(a, tz)
        lines.append("")
    if probs:
        lines += ["PROBLEMS", ""]
        for a in probs:
            lines += _order_lines(a, tz)
            for p in a["problems"]:
                lines.append(f"    This order {ORDER_PROBLEMS.get(p, p)}.")
        lines.append("")
    lines += [
        "Open Printify → Orders to act on these.",
        "This watcher only reads Printify. Nothing was approved, sent to production or changed.",
    ]
    return {"send": bool(alerts), "subject": f"{shop_name}: " + ", ".join(parts) if parts else "",
            "text": "\n".join(lines) if alerts else ""}


def _tz(name: str | None) -> dt.tzinfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return dt.timezone.utc


# ---------------------------------------------------------------- state file

def load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": STATE_VERSION, "orders": {}}
    except json.JSONDecodeError:
        # A corrupt file would re-alert everything once; better than crashing every 30 minutes.
        return {"version": STATE_VERSION, "orders": {}, "note": "state file was unreadable and was reset"}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------- one run

def run(client_factory, shop_cfg: dict, state_path: Path, now: dt.datetime,
        env: dict | None = None, dry_run: bool = False) -> dict:
    """One watcher pass. Printify trouble becomes ok=false plus one error email (not one every 30 min)."""
    env = os.environ if env is None else env
    settings = shop_cfg.get("orders", {})
    shop_name = shop_cfg["shop"]["name"]
    state = load_state(state_path)
    result = {
        "ok": True, "command": "watch-orders", "checked_at": iso(now), "dry_run": dry_run,
        "shop": None, "orders_checked": 0, "on_hold": 0, "alerts": [], "notes": [], "error": None,
    }
    if state.get("note"):
        result["notes"].append(state.pop("note"))
    try:
        client = client_factory(env.get("PRINTIFY_TOKEN", ""))
        shop, note = printify.pick_shop(client.shops(), env.get("PRINTIFY_SHOP_ID") or None)
        if note:
            result["notes"].append(note)
        orders = []
        if shop:
            result["shop"] = {"id": shop.get("id"), "title": shop.get("title")}
            orders = collect_orders(client, shop["id"], now,
                                    int(settings.get("lookback_days", 30)), int(settings.get("max_pages", 10)))
        alerts, state = evaluate(orders, state, now, settings)
        result.update(orders_checked=len(orders), alerts=alerts,
                      on_hold=sum(1 for o in orders if norm(o.get("status")) == HELD))
        email = render_email(alerts, settings, shop_name)
        if state.pop("last_error", None):
            result["notes"].append("Printify is reachable again")
    except printify.PrintifyError as e:
        result.update(ok=False, error=str(e))
        email = _error_email(state, str(e), now, settings, shop_name)
    email.update(to=env.get("ALERT_EMAIL_TO", ""), **{"from": env.get("ALERT_EMAIL_FROM", "")})
    result["email"] = email
    if not dry_run:
        save_state(state_path, state)
    return result


def _error_email(state: dict, message: str, now: dt.datetime, settings: dict, shop_name: str) -> dict:
    last = state.get("last_error") or {}
    repeat = dt.timedelta(hours=float(settings.get("error_repeat_hours", 6)))
    sent = parse_time(last.get("emailed"))
    send = last.get("message") != message or sent is None or now - sent >= repeat
    state["last_error"] = {"message": message, "emailed": iso(now) if send else last.get("emailed")}
    return {
        "send": send,
        "subject": f"{shop_name}: order watcher can't check Printify",
        "text": "\n".join([
            "The order watcher couldn't read Printify, so new orders may not be emailed to you.",
            "",
            f"Error: {message}",
            "",
            "Until it's fixed, check Printify → Orders by hand.",
            f"It keeps retrying every 30 minutes and repeats this email at most every "
            f"{settings.get('error_repeat_hours', 6)} hours while the error lasts.",
        ]),
    }
