import datetime as dt
import json

import pytest

from dbc import artlog, cli

DAY = dt.date(2026, 10, 7)


def test_ids_split_into_design_round_and_variant():
    assert artlog.parse_id("limit-r02-B") == {"design": "limit", "round": "2", "variant": "B", "parent_id": ""}
    assert artlog.parse_id("nana-recipe-r01-C3")["parent_id"] == "nana-recipe-r01-C2"
    assert artlog.parse_id("limit-r02-B2")["parent_id"] == "limit-r02-B"
    for bad in ("limit-r2-B", "Limit-r02-B", "limit-r02-b", "limit-r02-B1", "limit_r02_B"):
        with pytest.raises(artlog.ArtLogError):
            artlog.parse_id(bad)


def test_add_then_fill_in_the_image_and_score(tmp_path):
    log = tmp_path / "log.csv"
    artlog.add("style-r01-A", prompt="art/prompts/style-r01-A.md", today=DAY, path=log)
    check = {"width": 1536, "height": 1024, "has_alpha_channel": True, "corners_transparent": True,
             "touches_edge": False, "stray_specks": 0, "pct_light_fringe": 4.0,
             "verdict": ["clean: transparent, no specks, no fringe flagged"]}
    artlog.add("style-r01-A", image="designs/style-test/round-01/style-r01-A.png", check=check,
               today=dt.date(2026, 10, 9), path=log)
    row = artlog.set_fields("style-r01-A", ["score=4", "notes=love the colors", "decision=keep"], path=log)
    rows = artlog.read(log)
    assert len(rows) == 1 and rows[0] == row
    assert row["date"] == "2026-10-07" and row["width"] == "1536" and row["transparent"] == "yes"
    assert row["edges_ok"] == "yes" and row["check_notes"] == "" and row["john_score"] == "4"
    assert log.read_text(encoding="utf-8").splitlines()[0] == ",".join(artlog.COLUMNS)


def test_a_painted_checkerboard_fails_the_edge_check():
    check = {"has_alpha_channel": False, "corners_transparent": False, "stray_specks": 0,
             "verdict": ["background NOT transparent (checkerboard painted in)"]}
    cols = artlog.from_check(check)
    assert cols["transparent"] == "no" and cols["edges_ok"] == "no" and "checkerboard" in cols["check_notes"]


def test_bad_values_are_refused(tmp_path):
    log = tmp_path / "log.csv"
    artlog.add("limit-r02-B", today=DAY, path=log)
    with pytest.raises(artlog.ArtLogError, match="score"):
        artlog.set_fields("limit-r02-B", ["score=9"], path=log)
    with pytest.raises(artlog.ArtLogError, match="decision"):
        artlog.set_fields("limit-r02-B", ["decision=maybe"], path=log)
    with pytest.raises(artlog.ArtLogError, match="name=value"):
        artlog.set_fields("limit-r02-B", ["colour=red"], path=log)
    with pytest.raises(artlog.ArtLogError, match="add it first"):
        artlog.set_fields("limit-r02-C", ["score=3"], path=log)
    with pytest.raises(artlog.ArtLogError, match="doesn't exist"):
        artlog.add("limit-r02-B", prompt="art/prompts/nope.md", path=log)
    assert artlog.read(log)[0]["john_score"] == ""


def test_every_logged_prompt_file_exists_and_ids_are_unique():
    rows = artlog.read()
    assert len({r["id"] for r in rows}) == len(rows)
    for r in rows:
        artlog.parse_id(r["id"])
        assert r["decision"] in artlog.DECISIONS
        assert not r["prompt_file"] or (artlog.ROOT / r["prompt_file"]).exists()
        assert not r["image_file"].startswith("art/"), "images stay out of the public repo"


def test_cli_show_prints_json(capsys):
    assert cli.main(["--json", "art-log", "show"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert {r["id"] for r in rows} >= {"style-r01-A", "style-r01-B", "style-r01-C"}
