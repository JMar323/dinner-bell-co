"""Art log: one row per image John makes in ChatGPT from our prompts (docs/art-log.md).

    python -m dbc art-log add limit-r02-B --prompt art/prompts/limit-r02-B.md
    python -m dbc art-log add limit-r02-B --image designs/limit/round-02/limit-r02-B.png --check B_check.json
    python -m dbc art-log set limit-r02-B score=4 notes="love the colors" decision=keep
    python -m dbc art-log show

IDs are <design>-r<round>-<variant>, e.g. limit-r02-B; a redo of B in the same round is limit-r02-B2.
The log is art/log.csv; John's Google Sheet shows it with IMPORTDATA. Images stay in the private
project folder, never in this public repo.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
from pathlib import Path

from .config import ROOT

LOG = ROOT / "art" / "log.csv"
COLUMNS = ["id", "date", "design", "round", "variant", "parent_id", "model", "prompt_file", "references",
           "image_file", "width", "height", "transparent", "edges_ok", "check_notes", "john_score",
           "john_notes", "decision"]
DECISIONS = ("waiting", "keep", "revise", "drop", "approved")
ID = re.compile(r"^(?P<design>[a-z0-9]+(?:-[a-z0-9]+)*)-r(?P<round>\d{2})-(?P<variant>[A-Z])(?P<redo>\d*)$")
# short names John and Claude type; the left side is what `set` accepts
FIELDS = {"score": "john_score", "notes": "john_notes", "decision": "decision", "model": "model",
          "prompt": "prompt_file", "refs": "references", "image": "image_file", "parent": "parent_id",
          "check_notes": "check_notes"}


class ArtLogError(ValueError):
    pass


def parse_id(art_id: str) -> dict:
    m = ID.match(art_id)
    if not m:
        raise ArtLogError(f"{art_id!r} isn't an art ID like limit-r02-B (design-r<2-digit round>-<letter>[redo number])")
    redo = m["redo"]
    parent = ""
    if redo:
        n = int(redo)
        if n < 2:
            raise ArtLogError(f"{art_id}: a redo number starts at 2 ({art_id[:-len(redo)]}2)")
        base = art_id[:-len(redo)]
        parent = base if n == 2 else f"{base}{n - 1}"
    return {"design": m["design"], "round": str(int(m["round"])), "variant": m["variant"] + redo, "parent_id": parent}


def read(path: Path = LOG) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for c in COLUMNS:
            r.setdefault(c, "")
    return rows


def write(rows: list[dict], path: Path = LOG) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n", extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(buf.getvalue(), encoding="utf-8")


def from_check(check: dict) -> dict:
    """Columns filled from the image checker's <id>_check.json (designs/tools/study.py)."""
    transparent = bool(check.get("has_alpha_channel") and check.get("corners_transparent"))
    edges_ok = (transparent and not check.get("touches_edge") and check.get("stray_specks", 0) <= 3
                and check.get("pct_light_fringe", 0) <= 25)
    notes = [n for n in check.get("verdict", []) if not n.startswith("clean")]
    return {"width": str(check.get("width", "")), "height": str(check.get("height", "")),
            "transparent": "yes" if transparent else "no", "edges_ok": "yes" if edges_ok else "no",
            "check_notes": "; ".join(notes)}


def _validate(row: dict) -> None:
    if row["decision"] not in DECISIONS:
        raise ArtLogError(f"decision must be one of {', '.join(DECISIONS)}, not {row['decision']!r}")
    if row["john_score"] and row["john_score"] not in ("1", "2", "3", "4", "5"):
        raise ArtLogError(f"score must be 1 to 5, not {row['john_score']!r}")


def add(art_id: str, *, model: str = "ChatGPT Images", prompt: str = "", refs: str = "", image: str = "",
        check: dict | None = None, parent: str = "", today: dt.date | None = None, path: Path = LOG) -> dict:
    """New row, or fills in an existing one (e.g. the image arrives after the prompt was logged)."""
    rows = read(path)
    row = next((r for r in rows if r["id"] == art_id), None)
    if row is None:
        row = {c: "" for c in COLUMNS} | {"id": art_id, "decision": "waiting"} | parse_id(art_id)
        rows.append(row)
    row["date"] = row["date"] or (today or dt.date.today()).isoformat()
    for col, val in (("model", model), ("prompt_file", prompt), ("references", refs), ("image_file", image),
                     ("parent_id", parent)):
        if val:
            row[col] = val
    if check:
        row.update(from_check(check))
    if row["prompt_file"] and not (ROOT / row["prompt_file"]).exists():
        raise ArtLogError(f"{row['prompt_file']} doesn't exist in the repo: save the prompt there first")
    _validate(row)
    write(rows, path)
    return row


def set_fields(art_id: str, pairs: list[str], path: Path = LOG) -> dict:
    rows = read(path)
    row = next((r for r in rows if r["id"] == art_id), None)
    if row is None:
        raise ArtLogError(f"{art_id} isn't in the log yet: add it first")
    for pair in pairs:
        key, sep, val = pair.partition("=")
        if not sep or key not in FIELDS:
            raise ArtLogError(f"use name=value with a name from: {', '.join(FIELDS)}")
        row[FIELDS[key]] = val.strip()
    _validate(row)
    write(rows, path)
    return row


def load_check(path: Path | None) -> dict | None:
    return json.loads(Path(path).read_text(encoding="utf-8")) if path else None
