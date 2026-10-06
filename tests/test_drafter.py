import copy
import datetime as dt
import json
from pathlib import Path

import pytest

from dbc import banned, checks, cli, config, drafter

TODAY = dt.date(2026, 10, 6)
SHOP = config.shop()
PRODUCTS = config.products()
TERMS = banned.load(config.BANNED_TERMS)
PAPA = config.load_toml(config.ROOT / "ideas" / "papas-keepers-mug.toml")


def run(idea, today=TODAY):
    d = drafter.draft(idea, PRODUCTS, SHOP, today)
    return d, checks.run(d, SHOP, TERMS, drafter.holiday_active(SHOP, today))


def errors(issues):
    return [i for i in issues if i.level == "error"]


def messages(issues):
    return " | ".join(str(i) for i in issues)


def test_approved_template_passes_and_matches_setup_kit():
    d, issues = run(PAPA)
    assert errors(issues) == []
    assert d["title"] == "Personalized Papa Mug with Grandkids Names on Fish, Custom Fishing Mug for Grandpa, 11oz"
    assert len(d["tags"]) == 13
    assert d["description"].endswith(SHOP["disclosure"]["line"])
    assert "Order by Tuesday, December 8 for Christmas." in d["description"]
    assert [f["max_chars"] for f in d["personalization"]] == [9, 7, 7, 7, 7]
    assert d["settings"]["production_partner"] == "Printify"
    assert d["price"] == 19.99 and d["price_status"] == "approved"


def test_generated_title_and_tags_fit_limits():
    idea = config.load_toml(config.ROOT / "ideas" / "nana-est-crewneck.toml")
    d, issues = run(idea)
    assert errors(issues) == []
    assert len(d["title"].split()) < 15 and len(d["title"]) <= 140
    assert len(d["tags"]) == 13 and all(len(t) <= 20 for t in d["tags"])
    assert any(i.field == "price" for i in issues)   # tee/crewneck prices still pending


@pytest.mark.parametrize("title,expect", [
    ("One two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen", "15 words"),
    ("x" * 141, "141 characters"),
    ('Personalized "Papa" Mug', "quotation marks"),
    ("Personalized Papa Mug ", "trailing space"),
    ("Papa Mug: Fishing: Grandpa", "':' can only be used once"),
    ("Papa Mug 🎣 Fishing", "characters Etsy rejects"),
])
def test_title_errors(title, expect):
    idea = {**PAPA, "title": title}
    _, issues = run(idea)
    assert expect in messages(errors(issues))


def test_holiday_in_title_is_a_warning():
    _, issues = run({**PAPA, "title": "Personalized Papa Christmas Mug with Grandkids Names"})
    assert errors(issues) == []
    assert "holiday word" in messages(issues)


def test_tag_errors():
    idea = {**PAPA, "keywords": PAPA["keywords"][:12] + ["grandpa fishing coffee mug"]}
    _, issues = run(idea)
    assert "is 26 characters" in messages(errors(issues))
    idea = {**PAPA, "keywords": PAPA["keywords"][:12] + ["papa fishing mug"]}
    d, issues = run(idea)
    assert len(d["tags"]) == 13   # duplicate is dropped, a fallback fills the slot
    assert errors(issues) == []
    bad = {**PAPA, "keywords": PAPA["keywords"][:12] + ["papa_mug!"]}
    assert "characters Etsy rejects in tags" in messages(errors(run(bad)[1]))


@pytest.mark.parametrize("field,value", [
    ("title", "Personalized Papa's Fishing Gang Mug with Grandkids Names"),
    ("design_text", ["Grandpa's Gang"]),
    ("keywords", PAPA["keywords"][:12] + ["fishing gangs"]),
    ("opening", "A mug for the whole gang. Every grandkid's name on a fish."),
])
def test_gang_is_never_allowed(field, value):
    _, issues = run({**PAPA, field: value})
    assert "say crew or buddies" in messages(errors(issues))


def test_crew_and_buddies_are_fine():
    idea = {**PAPA, "design_text": ["Papa's Fishing Crew", "Papa's Buddies"]}
    assert errors(run(idea)[1]) == []


def test_banned_terms_respect_product():
    on_mug = {**PAPA, "design_text": ["Reel Cool Papa"]}
    assert "reel cool" in messages(errors(run(on_mug)[1])).lower()
    on_tee = {**on_mug, "product": "tee"}
    issues = run(on_tee)[1]
    assert not any("reel cool" in str(i).lower() for i in errors(issues))
    assert any("reel cool" in str(i).lower() for i in issues)
    keepers_tee = {**PAPA, "product": "tee", "title": "Personalized Papa Shirt with Grandkids Names",
                   "design_text": ["Papa's Keepers"]}
    assert "'keepers'" in messages(run(keepers_tee)[1])


@pytest.mark.parametrize("phrase", ["Peterbilt", "Mama Bears", "Trucker's Daughter", "truckers daughter",
                                    "Mimi & Me", "MAGA", "Keep On Truckin'", "Grammy's"])
def test_banned_phrases_caught_in_any_spelling(phrase):
    idea = {**PAPA, "product": "tee", "design_text": [phrase]}
    assert errors(run(idea)[1]), phrase


def test_banned_terms_do_not_hit_inside_words():
    hits = banned.scan(TERMS, "mug", {"t": "Afford a deer-free welder shirt for himself and Fordham"})
    assert [h.term.phrase for h in hits] == []


@pytest.mark.parametrize("phrase", ["with the help of digital and AI tools", "production partner, Printify"])
def test_missing_disclosure_fails(phrase):
    d, _ = run(PAPA)
    d["description"] = d["description"].replace(phrase, "")
    issues = checks.run(d, SHOP, TERMS, True)
    assert "disclosure missing" in messages(errors(issues))


def test_wrong_partner_fails():
    d, _ = run(PAPA)
    d["settings"]["production_partner"] = "Made by seller"
    assert "production partner" in messages(errors(checks.run(d, SHOP, TERMS, True)))


def test_personalization_limits():
    idea = copy.deepcopy(PAPA)
    idea["personalization"][1]["repeat"] = 5
    assert "6 fields" in messages(errors(run(idea)[1]))
    idea = copy.deepcopy(PAPA)
    idea["personalization"][0]["instructions"] = "x" * 121
    assert "instructions are 121 characters" in messages(errors(run(idea)[1]))
    idea = copy.deepcopy(PAPA)
    idea["personalization"][0]["question"] = "q" * 46
    assert "question is 46 characters" in messages(errors(run(idea)[1]))


def test_after_order_by_date_drops_christmas_line():
    d, issues = run(PAPA, today=dt.date(2026, 12, 9))
    assert "December 8" not in d["description"]
    assert errors(issues) == []


def test_missing_idea_fields_raise():
    with pytest.raises(drafter.IdeaError):
        drafter.draft({"id": "x", "product": "mug11"}, PRODUCTS, SHOP, TODAY)


def test_cli_writes_draft_and_check_reruns(tmp_path):
    out = tmp_path / "drafts"
    code = cli.main(["--today", "2026-10-06", "draft", str(config.ROOT / "ideas" / "papas-keepers-mug.toml"),
                     "--out", str(out)])
    assert code == 0
    path = out / "papas-keepers-mug.json"
    assert (out / "papas-keepers-mug.md").exists()
    d = json.loads(path.read_text())
    d["title"] += " Gang"
    path.write_text(json.dumps(d))
    assert cli.main(["--today", "2026-10-06", "check", str(path)]) == 1


def test_banned_file_parses_and_rejects_bad_lines(tmp_path):
    assert len(TERMS) > 50
    bad = tmp_path / "b.txt"
    bad.write_text("peterbilt | maybe | all | x\n")
    with pytest.raises(ValueError):
        banned.load(bad)


def test_repo_copy_of_banned_terms_matches_project_master():
    project = Path("/mnt/project-files/training/keywords/banned_terms.txt")
    if not project.exists():
        pytest.skip("project folder not mounted here")
    assert project.read_text() == config.BANNED_TERMS.read_text(), "sync data/banned_terms.txt with the project copy"


def test_json_output_for_n8n(tmp_path, capsys):
    code = cli.main(["--json", "--today", "2026-10-06", "draft",
                     str(config.ROOT / "ideas" / "nana-est-crewneck.toml"), "--out", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["ok"] is True and out["errors"] == []
    assert out["id"] == "nana-est-crewneck" and out["draft"].endswith("nana-est-crewneck.json")
    assert any(w["field"] == "price" for w in out["warnings"])
