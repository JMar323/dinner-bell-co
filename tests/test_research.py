"""Weekly idea research: brief, answer checks, report, and the Anthropic API engine (faked)."""

import datetime as dt
import json
from types import SimpleNamespace as NS

import pytest

from dbc import cli, config, research
from dbc.config import tomllib

TODAY = dt.date(2026, 10, 12)


@pytest.fixture
def inp(tmp_path):
    return research.Inputs(config.ROOT, TODAY, tmp_path / "inbox")


def idea(**over):
    base = {
        "id": "deer-camp-crew-mug", "name": "Deer Camp Crew mug", "line": "hunting-deer-camp",
        "product": "mug11", "occasion": "Christmas",
        "concept": "A cabin at dawn with each hunting buddy's name on a tree.",
        "why": "Deer camp gifts sell before rifle season and Christmas.",
        "demand": 4, "demand_evidence": "Bestseller badges on similar mugs",
        "competition": 3, "competition_evidence": "About 40 listings for the angle",
        "gift_fit": 5, "ip_check": "Deer Camp is generic; no live marks found",
        "sources": [{"url": "https://example.com/deer", "title": "Deer camp gifts"}],
    }
    base.update(over)
    return base


LISTING = {
    "recipient": "Grandpa", "recipient_alt": "Papa", "theme": "hunting", "motif": "Hunting Buddies Names",
    "design_text": ["Deer Camp Crew"], "title": "Personalized Grandpa Hunting Mug with Hunting Buddies Names, 11oz",
    "primary_keyword": "personalized grandpa mug",
    "keywords": ["grandpa hunting mug", "deer camp mug", "hunting gift", "custom hunting mug", "hunter gift",
                 "deer hunter mug", "grandpa gift", "papa hunting mug", "hunting buddies", "gift for hunter",
                 "camo coffee mug", "deer season gift", "hunting mug"],
    "opening": "A deer camp mug with every hunting buddy's name on it. For the grandpa who's up before dawn.",
    "how_to_order": ["Type each buddy's name, one per box."], "order_emoji": "🦌",
    "personalization": [{"question": "Buddy's name {n}", "instructions": "One name per box.", "max_chars": 9, "repeat": 4}],
    "holiday": "Christmas", "occasion": "Birthday", "recipient_attribute": "Grandparents, Men",
}


def test_themes_sheet_keeps_only_active_rows():
    rows = research.parse_themes("Active,Theme,Products\nyes,Grandma / Nana,mug11; crewneck\nno,Space,tee\n,Dogs,\n")
    assert [r["id"] for r in rows] == ["grandma-nana"]
    assert rows[0]["products"] == ["mug11", "crewneck"]


def test_repo_themes_file_has_the_five_lines_on():
    themes, where = research.load_themes(config.ROOT, {"themes": {"file": "config/themes.csv"}})
    assert where == "config/themes.csv"
    assert {t["id"] for t in themes} == {"grandma-nana", "hunting-deer-camp", "blue-collar-trades", "fishing", "dogs"}


def test_brief_follows_johns_answers(inp):
    assert "Find 15 new product ideas" in inp.brief
    assert "Christmas" in inp.brief and "don't all have to be Christmas-themed" in inp.brief
    assert "papas-keepers-mug" in inp.brief                     # kept ideas aren't repeated
    assert "star wars" in inp.brief                             # franchise names are listed as banned
    assert 'Leave out "listing"' in inp.brief                   # John picks before anything is drafted
    assert inp.schema["properties"]["ideas"]["items"]["properties"]["line"]["enum"][0] == "grandma-nana"


def test_ingest_scores_screens_and_writes_the_week(inp):
    data = {"summary": "Deer camp is hot.", "ideas": [
        idea(),
        idea(id="jedi-grandpa", name="Jedi Grandpa mug", concept="Grandpa as a Jedi"),
        idea(id="x", name="Mystery", line="space", demand=5),
    ]}
    out = research.ingest(data, inp, "claude-routine")
    assert out["ideas"] == 3 and out["blocked"] == 2
    ideas = json.loads((inp.out_dir / "ideas.json").read_text())["ideas"]
    by_id = {i["id"]: i for i in ideas}
    assert by_id["deer-camp-crew-mug"]["score"] == 80          # (0.4*4 + 0.3*3 + 0.3*5) / 5
    assert by_id["jedi-grandpa"]["blocked"]
    assert "isn't an active row" in by_id["x"]["problems"][0]
    report = (inp.out_dir / "report.md").read_text()
    assert "1. Deer Camp Crew mug  80/100" in report and "⛔ BLOCKED" in report
    assert "Tell Claude in the Etsy project" in report


def test_ingest_drafts_when_asked_and_skips_products_without_a_template(inp):
    inp.cfg["run"]["drafted"] = 2
    data = {"summary": "", "ideas": [idea(listing=LISTING),
                                     idea(id="buck-hat", product="hat", demand=5, listing=LISTING)]}
    out = research.ingest(data, inp, "test")
    assert out["drafted"] == ["deer-camp-crew-mug"]
    toml_text = (inp.out_dir / "deer-camp-crew-mug.toml").read_text()
    parsed = tomllib.loads(toml_text)                            # what we write is valid TOML
    assert parsed["personalization"][0]["repeat"] == 4 and parsed["section"] == "Hunting"
    draft = json.loads((inp.out_dir / "drafts" / "deer-camp-crew-mug.json").read_text())
    assert draft["title"] == LISTING["title"] and len(draft["tags"]) == 13
    hat = next(i for i in json.loads((inp.out_dir / "ideas.json").read_text())["ideas"] if i["id"] == "buck-hat")
    assert "no listing template for hat" in hat["problems"][0]


# ---------------------------------------------------------------- the API engine, faked

class FakeStream:
    def __init__(self, msg):
        self.msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.msg


class FakeClient:
    def __init__(self, messages):
        self.queue = list(messages)
        self.calls = []
        self.beta = NS(messages=NS(stream=self.stream))

    def stream(self, **kw):
        self.calls.append({**kw, "messages": list(kw["messages"])})
        return FakeStream(self.queue.pop(0))


def block(type_, **kw):
    return NS(type=type_, to_dict=lambda: {"type": type_, **{k: v for k, v in kw.items() if k != "input"}}, **kw)


def message(stop, *blocks, searches=0):
    usage = NS(input_tokens=1000, output_tokens=500, cache_read_input_tokens=0, cache_creation_input_tokens=0,
               server_tool_use=NS(web_search_requests=searches))
    return NS(stop_reason=stop, content=list(blocks), usage=usage)


def test_api_engine_resumes_paused_searches_and_emails_the_report(inp):
    results = block("web_search_tool_result", content=[{"type": "web_search_result", "url": "https://example.com/deer"}])
    client = FakeClient([
        message("pause_turn", block("server_tool_use", name="web_search"), results, searches=5),
        message("tool_use", block("tool_use", name="submit_ideas",
                                  input={"summary": "ok", "ideas": [idea(sources=[
                                      {"url": "https://example.com/deer/", "title": "seen"},
                                      {"url": "https://made.up/page", "title": "unseen"}])]}), searches=3),
    ])
    out = research.run(lambda: client, inp, "john@example.com", "")
    assert out["ok"] and out["ideas"] == 1 and out["email"]["send"]
    assert out["usage"]["web_search_requests"] == 8
    assert out["cost_usd"] == pytest.approx(2 * (1000 * 4 + 500 * 20) / 1e6 + 8 * 0.01, abs=0.01)
    first = client.calls[0]
    assert first["model"] == "claude-opus-5-5" and first["fallbacks"] == "default"
    assert first["tools"][0]["type"] == "web_search_20260209" and first["tools"][0]["max_uses"] == 20
    assert first["thinking"] == {"type": "adaptive"}
    assert client.calls[1]["messages"][-1]["role"] == "assistant"   # resumed, no extra "continue" message
    assert "(not in the search results: check it)" in out["email"]["text"]
    assert "example.com/deer/" in out["email"]["text"].split("unseen")[0]
    # a second run the same week doesn't spend money again
    assert research.run(lambda: FakeClient([]), inp, "john@example.com", "")["skipped"]


def test_api_engine_refusal_sends_an_error_email_and_writes_nothing(inp):
    out = research.run(lambda: FakeClient([message("refusal")]), inp, "john@example.com", "")
    assert not out["ok"] and "declined" in out["error"]
    assert out["email"]["subject"].endswith("didn't finish")
    assert not inp.out_dir.exists()


def test_api_engine_nudges_once_then_gives_up(inp):
    client = FakeClient([message("end_turn", block("text", text="done")), message("end_turn", block("text", text="?"))])
    out = research.run(lambda: client, inp, "john@example.com", "")
    assert not out["ok"] and "without handing in" in out["error"]
    assert "submit_ideas" in client.calls[1]["messages"][-1]["content"]


def test_missing_key_is_reported_without_crashing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = research.check(research.make_client, "claude-opus-5-5")
    assert not out["ok"] and ("ANTHROPIC_API_KEY" in out["error"] or "anthropic package" in out["error"])


def test_cli_brief_and_ingest(tmp_path, capsys):
    inbox = str(tmp_path / "inbox")
    assert cli.main(["--json", "--today", "2026-10-12", "research-brief", "--inbox", inbox]) == 0
    brief = json.loads(capsys.readouterr().out)
    assert brief["week"] == "2026-W42" and "Find 15" in brief["brief"]
    answer = tmp_path / "answer.json"
    answer.write_text(json.dumps({"summary": "s", "ideas": [idea()]}))
    assert cli.main(["--json", "--today", "2026-10-12", "research-ingest", str(answer), "--inbox", inbox]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ideas"] == 1 and (tmp_path / "inbox" / "2026-W42" / "report.md").exists()


def test_a_themes_file_from_the_sheet_overrides_the_repo_copy(tmp_path):
    sheet = tmp_path / "themes.csv"
    sheet.write_text("active,theme,products\nyes,Space and sci-fi fans,mug11\n")
    inp = research.Inputs(config.ROOT, TODAY, tmp_path / "inbox", themes_file=sheet)
    assert [t["id"] for t in inp.themes] == ["space-and-sci-fi-fans"] and inp.themes_from == str(sheet)


def test_a_normal_sheet_link_becomes_its_csv_download_link():
    sheet = "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
    assert research.sheet_csv_url(sheet + "/edit?usp=sharing") == sheet + "/export?format=csv"
    assert research.sheet_csv_url(sheet + "/edit?gid=42#gid=42") == sheet + "/export?format=csv&gid=42"
    published = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSabc/pub?output=csv"
    assert research.sheet_csv_url(published) == published
    assert research.sheet_csv_url(sheet + "/export?format=csv&gid=7") == sheet + "/export?format=csv&gid=7"


def test_a_sheet_without_a_theme_column_says_so():
    with pytest.raises(research.ResearchError, match="'theme' column"):
        research.parse_themes("Here are the first rows of the sheet:\nGrandma, Hunting\n")


def test_an_unreachable_sheet_falls_back_to_the_repo_file_and_says_so():
    cfg = {"themes": {"file": "config/themes.csv", "sheet_csv_url": "http://127.0.0.1:9/sheet.csv"}}
    themes, where = research.load_themes(config.ROOT, cfg)
    assert len(themes) == 5 and where == "config/themes.csv (couldn't read the Google Sheet)"


def test_themes_lists_what_the_sheet_changed(tmp_path, capsys):
    rows = (config.ROOT / "config" / "themes.csv").read_text(encoding="utf-8").splitlines()
    rows = [r for r in rows if not r.startswith("yes,Dogs")]
    rows = [r.replace("yes,Fishing,Fishing,", "yes,Fishing,Fishing on the lake,") for r in rows]
    rows = [r.replace("no,Space and sci-fi fans", "yes,Space and sci-fi fans") for r in rows]
    sheet = tmp_path / "themes.csv"
    sheet.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert cli.main(["--json", "themes", "--themes", str(sheet)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["from"] == str(sheet) and len(out["themes"]) == 5
    assert out["changes"] == ["new: Space and sci-fi fans", "off: Dogs", "changed: Fishing (section)"]


# ---------------------------------------------------------------- niche lingo (John 2026-10-07)

@pytest.fixture
def repo_inp(tmp_path):
    """The repo's config/themes.csv, not John's live sheet (CI can reach the sheet, which may differ)."""
    return research.Inputs(config.ROOT, TODAY, tmp_path / "inbox", themes_file=config.ROOT / "config" / "themes.csv")


def test_lingo_cell_reads_and_writes_back():
    terms = research.parse_lingo("hawg (a big bass); honey hole ;skunked (caught nothing, all day);; ")
    assert terms == [{"term": "hawg", "meaning": "a big bass"}, {"term": "honey hole", "meaning": ""},
                     {"term": "skunked", "meaning": "caught nothing, all day"}]
    assert research.lingo_cell(terms) == "hawg (a big bass); honey hole; skunked (caught nothing, all day)"


def test_lingo_screen_drops_blocked_terms(inp):
    kept, dropped = research.screen_lingo(research.parse_lingo(
        "lunker; Googan Squad (newbies); fishing gang; reel cool; keepers"), inp.terms)
    assert [t["term"] for t in kept] == ["lunker", "keepers"]      # keepers is only a caution
    assert len(dropped) == 3 and dropped[0].startswith("Googan Squad: GOOGAN SQUAD")


def test_repo_fishing_row_has_bass_lingo_and_it_is_clean(repo_inp):
    fishing = next(t for t in repo_inp.themes if t["id"] == "fishing")
    terms = research.parse_lingo(fishing["lingo"])
    assert len(terms) >= 15 and {"hawg", "bucketmouth", "limit", "honey hole"} <= {t["term"] for t in terms}
    assert not {"crankbait", "jig", "lipping", "cull"} & {t["term"] for t in terms}   # family words, not gear talk
    assert research.screen_lingo(terms, repo_inp.terms)[1] == []


def test_brief_uses_lingo_and_asks_for_it_where_thin(repo_inp):
    assert "Lingo: limit (" in repo_inp.brief
    assert "Never copy the lingo list into a design or a listing" in repo_inp.brief
    ask = repo_inp.brief.split("Lingo research: for ")[1].split(" also find")[0]
    assert "dogs" in ask and "fishing" not in ask              # fishing already has enough
    assert repo_inp.schema["properties"]["lingo"]["items"]["properties"]["line"]["enum"] == [t["id"] for t in repo_inp.themes]
    assert "lingo" not in repo_inp.schema["required"]


def test_ingest_merges_new_lingo_into_a_cell(repo_inp):
    data = {"summary": "s", "ideas": [idea()], "lingo": [
        {"line": "hunting-deer-camp", "sources": [{"url": "https://example.com/deer", "title": "Deer talk"}],
         "terms": [{"term": "buck fever", "meaning": "nerves when a big one shows up"},
                   {"term": "Buck Fever", "meaning": "dupe"},
                   {"term": "hunting gang", "meaning": "crew"}]},
        {"line": "fishing", "sources": [], "terms": [{"term": "hawg", "meaning": "already there"},
                                                     {"term": "early bite", "meaning": "fish feed at sunup"}]},
        {"line": "space", "sources": [], "terms": [{"term": "x", "meaning": "y"}]},
    ]}
    out = research.ingest(data, repo_inp, "claude-routine")
    assert out["lingo"] == ["hunting-deer-camp", "fishing"]
    lingo = {lg["line"]: lg for lg in json.loads((repo_inp.out_dir / "ideas.json").read_text())["lingo"]}
    assert lingo["hunting-deer-camp"]["cell"] == "buck fever (nerves when a big one shows up)"
    assert lingo["hunting-deer-camp"]["dropped"][0].startswith("hunting gang")
    assert [t["term"] for t in lingo["fishing"]["new"]] == ["early bite"]
    assert lingo["fishing"]["cell"].endswith("; early bite (fish feed at sunup)")
    assert "not an active theme" in lingo[""]["dropped"][0]
    report = (repo_inp.out_dir / "report.md").read_text()
    assert "LINGO FOR THE THEMES SHEET" in report and "Cell: buck fever" in report


def test_theme_changes_notice_lingo():
    old = research.parse_themes("theme,lingo\nFishing,hawg\n")
    new = research.parse_themes("theme,lingo\nFishing,hawg; dink\n")
    assert research.theme_changes(new, old) == ["changed: Fishing (lingo)"]
    assert research.theme_changes(research.parse_themes("theme\nFishing\n"), research.parse_themes("theme,lingo\nFishing,\n")) == []
