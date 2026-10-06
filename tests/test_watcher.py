import datetime as dt
import inspect
import json
import os

import pytest

from dbc import cli, config, printify, watcher

SHOP_CFG = config.shop()
SETTINGS = SHOP_CFG["orders"]
NOW = dt.datetime(2026, 11, 20, 15, 0, tzinfo=dt.timezone.utc)
TOKEN = "secret-token-value"
ETSY_SHOP = {"id": 5432, "title": "DinnerBellCo", "sales_channel": "etsy"}


def order(oid, status="on-hold", hours_ago=1.0, receipt=3712345678, items=None):
    created = NOW - dt.timedelta(hours=hours_ago)
    return {
        "id": oid,
        "status": status,
        "created_at": created.strftime("%Y-%m-%d %H:%M:%S+00:00"),   # Printify's format
        "metadata": {"order_type": "external", "shop_order_id": receipt, "shop_order_label": str(receipt)},
        "line_items": items or [{
            "product_id": "p1", "quantity": 1, "variant_id": 1, "status": status,
            "metadata": {"title": "Personalized Papa Mug", "variant_label": "11oz", "price": 1999},
        }],
    }


class FakePrintify:
    """Stands in for api.printify.com. Records every request."""

    def __init__(self, shops=(ETSY_SHOP,), orders=(), page_size=10, fail=None):
        self.shops = list(shops)
        self.orders = list(orders)
        self.page_size = page_size
        self.fail = list(fail or [])     # statuses to return before succeeding
        self.calls = []

    def __call__(self, method, url, headers):
        self.calls.append((method, url, headers))
        if self.fail:
            status = self.fail.pop(0)
            return status, {"Retry-After": "0"}, json.dumps({"message": "nope"}).encode()
        if url.endswith("/shops.json"):
            return 200, {}, json.dumps(self.shops).encode()
        if "page=" not in url:                                   # one order by id
            oid = url.rsplit("/", 1)[1].removesuffix(".json")
            return 200, {}, json.dumps(next(o for o in self.orders if o["id"] == oid)).encode()
        page = int(url.split("page=")[1].split("&")[0])
        last = max(1, -(-len(self.orders) // self.page_size))
        data = self.orders[(page - 1) * self.page_size: page * self.page_size]
        return 200, {}, json.dumps({"current_page": page, "last_page": last, "data": data}).encode()

    def client(self, token=TOKEN):
        return printify.Client(token, transport=self, sleep=lambda s: None)


def run(fake, tmp_path, now=NOW, env=None, dry_run=False):
    env = {"PRINTIFY_TOKEN": TOKEN, "ALERT_EMAIL_TO": "john@example.com", **(env or {})}
    factory = lambda token: printify.Client(token, transport=fake, sleep=lambda s: None)
    return watcher.run(factory, SHOP_CFG, tmp_path / "state.json", now, env=env, dry_run=dry_run)


# ---------------------------------------------------------------- client

def test_client_only_ever_sends_get_with_auth_and_user_agent():
    fake = FakePrintify(orders=[order("a")])
    c = fake.client()
    c.shops()
    c.orders(5432)
    c.order(5432, "a")
    assert {m for m, _, _ in fake.calls} == {"GET"}
    for _, url, headers in fake.calls:
        assert url.startswith("https://api.printify.com/v1/")
        assert headers["Authorization"] == f"Bearer {TOKEN}"
        assert headers["User-Agent"]


def test_client_has_no_way_to_change_orders():
    names = {n for n in dir(printify.Client) if not n.startswith("__")}
    assert not names & {"send_to_production", "cancel", "create_order", "post", "put", "delete"}
    source = inspect.getsource(printify) + inspect.getsource(watcher)
    assert '"POST"' not in source and "send_to_production.json" not in source


def test_missing_token_and_bad_token_messages_never_show_the_token():
    with pytest.raises(printify.PrintifyError, match="PRINTIFY_TOKEN is not set"):
        printify.Client("")
    fake = FakePrintify(fail=[401])
    with pytest.raises(printify.PrintifyError, match="401") as e:
        fake.client().shops()
    assert TOKEN not in str(e.value)


def test_retries_rate_limit_then_succeeds():
    fake = FakePrintify(fail=[429, 503])
    assert fake.client().shops() == [ETSY_SHOP]
    assert len(fake.calls) == 3


def test_gives_up_after_retries():
    fake = FakePrintify(fail=[500, 500, 500])
    with pytest.raises(printify.PrintifyError, match="500"):
        fake.client().shops()


@pytest.mark.parametrize("shops,shop_id,expect", [
    ([ETSY_SHOP, {"id": 1, "title": "x", "sales_channel": "disconnected"}], None, 5432),
    ([{"id": 1, "title": "My new store", "sales_channel": "custom_integration"}], None, None),
    ([], None, None),
    ([ETSY_SHOP, {"id": 7, "title": "Two", "sales_channel": "etsy"}], "7", 7),
])
def test_pick_shop(shops, shop_id, expect):
    shop, note = printify.pick_shop(shops, shop_id)
    assert (shop and shop["id"]) == expect
    assert bool(note) == (expect is None)


def test_pick_shop_refuses_to_guess_between_two_etsy_shops():
    with pytest.raises(printify.PrintifyError, match="PRINTIFY_SHOP_ID"):
        printify.pick_shop([ETSY_SHOP, {"id": 7, "title": "Two", "sales_channel": "etsy"}])


# ---------------------------------------------------------------- reading orders

def test_collect_orders_pages_and_stops_at_old_orders():
    recent = [order(f"r{i}", "fulfilled", hours_ago=i) for i in range(15)]
    old = [order(f"o{i}", "fulfilled", hours_ago=24 * 60 + i) for i in range(30)]
    fake = FakePrintify(orders=recent + old)
    got = watcher.collect_orders(fake.client(), 5432, NOW, lookback_days=30, max_pages=10)
    assert [o["id"] for o in got] == [o["id"] for o in recent]
    assert len(fake.calls) == 3          # page 3 is all old, so it stops there


def test_collect_orders_handles_oldest_first_lists():
    old = [order(f"o{i}", "fulfilled", hours_ago=24 * 60 - i) for i in range(30)]   # oldest first
    recent = [order(f"r{i}", "fulfilled", hours_ago=15 - i) for i in range(15)]
    fake = FakePrintify(orders=old + recent)
    got = watcher.collect_orders(fake.client(), 5432, NOW, lookback_days=30, max_pages=10)
    assert sorted(o["id"] for o in got) == sorted(o["id"] for o in recent)
    assert [c[1].split("page=")[1].split("&")[0] for c in fake.calls] == ["1", "5", "4", "3"]


def test_collect_orders_respects_max_pages():
    fake = FakePrintify(orders=[order(f"r{i}", hours_ago=1) for i in range(50)])
    got = watcher.collect_orders(fake.client(), 5432, NOW, lookback_days=30, max_pages=2)
    assert len(got) == 20


# ---------------------------------------------------------------- what gets alerted

def kinds(alerts):
    return [(a["kind"], a["order_id"]) for a in alerts]


def test_new_held_order_alerts_once():
    alerts, state = watcher.evaluate([order("a")], {}, NOW, SETTINGS)
    assert kinds(alerts) == [("held", "a")]
    a = alerts[0]
    assert a["receipt"] == "3712345678" and a["items"][0]["title"] == "Personalized Papa Mug"
    again, _ = watcher.evaluate([order("a")], state, NOW + dt.timedelta(minutes=30), SETTINGS)
    assert again == []


def test_reminder_after_18_hours_once():
    _, state = watcher.evaluate([order("a", hours_ago=1)], {}, NOW, SETTINGS)
    later = NOW + dt.timedelta(hours=17)                      # order is now 18h old
    alerts, state = watcher.evaluate([order("a", hours_ago=1)], state, later, SETTINGS)
    assert kinds(alerts) == [("reminder", "a")]
    alerts, _ = watcher.evaluate([order("a", hours_ago=1)], state, later + dt.timedelta(hours=3), SETTINGS)
    assert alerts == []


def test_not_yet_18_hours_no_reminder():
    _, state = watcher.evaluate([order("a", hours_ago=1)], {}, NOW, SETTINGS)
    alerts, _ = watcher.evaluate([order("a", hours_ago=1)], state, NOW + dt.timedelta(hours=16.9), SETTINGS)
    assert alerts == []


def test_held_order_first_seen_late_sends_one_alert_not_two():
    alerts, state = watcher.evaluate([order("a", hours_ago=20)], {}, NOW, SETTINGS)
    assert kinds(alerts) == [("held", "a")]
    alerts, _ = watcher.evaluate([order("a", hours_ago=20)], state, NOW + dt.timedelta(hours=1), SETTINGS)
    assert alerts == []


def test_approved_order_stops_reminders():
    _, state = watcher.evaluate([order("a")], {}, NOW, SETTINGS)
    alerts, _ = watcher.evaluate([order("a", "in-production")], state, NOW + dt.timedelta(hours=20), SETTINGS)
    assert alerts == []


@pytest.mark.parametrize("status", ["has-issues", "unfulfillable", "payment-not-received", "canceled"])
def test_problem_statuses_alert_once(status):
    alerts, state = watcher.evaluate([order("a", status)], {}, NOW, SETTINGS)
    assert kinds(alerts) == [("problem", "a")] and alerts[0]["problems"] == [status]
    again, _ = watcher.evaluate([order("a", status)], state, NOW + dt.timedelta(hours=1), SETTINGS)
    assert again == []


def test_problem_that_changes_alerts_again():
    _, state = watcher.evaluate([order("a", "has-issues")], {}, NOW, SETTINGS)
    alerts, _ = watcher.evaluate([order("a", "unfulfillable")], state, NOW + dt.timedelta(hours=1), SETTINGS)
    assert kinds(alerts) == [("problem", "a")]


def test_problem_that_clears_and_comes_back_alerts_again():
    _, state = watcher.evaluate([order("a", "has-issues")], {}, NOW, SETTINGS)
    _, state = watcher.evaluate([order("a", "in-production")], state, NOW + dt.timedelta(hours=1), SETTINGS)
    alerts, _ = watcher.evaluate([order("a", "has-issues")], state, NOW + dt.timedelta(hours=2), SETTINGS)
    assert kinds(alerts) == [("problem", "a")]


def test_line_item_problem_on_an_otherwise_fine_order():
    items = [
        {"quantity": 1, "status": "in-production", "metadata": {"title": "Mug"}},
        {"quantity": 1, "status": "Has Issues", "metadata": {"title": "Tee"}},
    ]
    alerts, _ = watcher.evaluate([order("a", "in-production", items=items)], {}, NOW, SETTINGS)
    assert kinds(alerts) == [("problem", "a")] and alerts[0]["problems"] == ["has-issues"]


def test_normal_orders_are_quiet():
    orders = [order("a", s) for s in ("pending", "sending-to-production", "in-production", "fulfilled")]
    alerts, _ = watcher.evaluate(orders, {}, NOW, SETTINGS)
    assert alerts == []


def test_old_state_is_pruned():
    state = {"orders": {"gone": {"last_seen": "2026-08-01T00:00:00+00:00", "held_alerted": "x"}}}
    _, state = watcher.evaluate([], state, NOW, SETTINGS)
    assert state["orders"] == {}


# ---------------------------------------------------------------- the email

def test_email_lists_each_order_and_says_nothing_was_sent():
    alerts, _ = watcher.evaluate([order("a"), order("b", "has-issues", receipt=999)], {}, NOW, SETTINGS)
    email = watcher.render_email(alerts, SETTINGS, "Dinner Bell Co")
    assert email["send"]
    assert email["subject"] == "Dinner Bell Co: 1 new order to review, 1 order problem"
    assert "Etsy order #3712345678" in email["text"] and "Etsy order #999" in email["text"]
    assert "1 × Personalized Papa Mug (11oz)" in email["text"]
    assert "Nothing was approved, sent to production or changed." in email["text"]
    assert "Fri Nov 20, 9:00 AM EST" in email["text"]          # NOW minus 1h, in Ohio time


def test_no_alerts_no_email():
    assert watcher.render_email([], SETTINGS, "Dinner Bell Co")["send"] is False


# ---------------------------------------------------------------- whole runs

def test_run_end_to_end_remembers_between_runs(tmp_path):
    fake = FakePrintify(orders=[order("a"), order("b", "fulfilled")])
    first = run(fake, tmp_path)
    assert first["ok"] and first["shop"]["id"] == 5432
    assert first["orders_checked"] == 2 and first["on_hold"] == 1
    assert first["email"]["send"] and first["email"]["to"] == "john@example.com"
    second = run(fake, tmp_path, now=NOW + dt.timedelta(minutes=30))
    assert second["alerts"] == [] and second["email"]["send"] is False


def test_dry_run_writes_no_state(tmp_path):
    fake = FakePrintify(orders=[order("a")])
    assert run(fake, tmp_path, dry_run=True)["email"]["send"]
    assert not (tmp_path / "state.json").exists()
    assert run(fake, tmp_path)["email"]["send"]


def test_no_connected_shop_yet_is_quiet(tmp_path):
    fake = FakePrintify(shops=[])
    result = run(fake, tmp_path)
    assert result["ok"] and result["email"]["send"] is False
    assert "no Etsy-connected shop" in result["notes"][0]


def test_printify_errors_email_once_then_every_6_hours(tmp_path):
    fake = FakePrintify(fail=[401] * 10)
    first = run(fake, tmp_path)
    assert not first["ok"] and "401" in first["error"] and first["email"]["send"]
    assert TOKEN not in json.dumps(first)
    assert run(fake, tmp_path, now=NOW + dt.timedelta(hours=1))["email"]["send"] is False
    assert run(fake, tmp_path, now=NOW + dt.timedelta(hours=6))["email"]["send"] is True
    fake.fail = []
    back = run(fake, tmp_path, now=NOW + dt.timedelta(hours=7))
    assert back["ok"] and "Printify is reachable again" in back["notes"]


def test_corrupt_state_file_resets_instead_of_crashing(tmp_path):
    (tmp_path / "state.json").write_text("{not json")
    result = run(FakePrintify(orders=[order("a")]), tmp_path)
    assert result["ok"] and "reset" in result["notes"][0]


# ---------------------------------------------------------------- command line and .env

REAL_CLIENT = printify.Client


def real_client(token, fake):
    return REAL_CLIENT(token, transport=fake, sleep=lambda s: None)


@pytest.fixture
def no_env_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DBC_ENV_FILE", str(tmp_path / "missing.env"))
    for k in ("PRINTIFY_TOKEN", "ALERT_EMAIL_TO", "ALERT_EMAIL_FROM", "PRINTIFY_SHOP_ID"):
        monkeypatch.delenv(k, raising=False)


def test_cli_watch_orders_json(no_env_file, tmp_path, monkeypatch, capsys):
    fake = FakePrintify(orders=[order("a")])
    monkeypatch.setattr(printify, "Client", lambda token: real_client(token, fake))
    monkeypatch.setenv("PRINTIFY_TOKEN", TOKEN)
    monkeypatch.setenv("ALERT_EMAIL_TO", "john@example.com")
    code = cli.main(["--json", "watch-orders", "--state", str(tmp_path / "s.json"), "--now", NOW.isoformat()])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["ok"] and out["email"]["send"]
    assert kinds(out["alerts"]) == [("held", "a")]


def test_cli_watch_orders_without_alert_address_exits_2(no_env_file, capsys):
    assert cli.main(["--json", "watch-orders"]) == 2
    assert "ALERT_EMAIL_TO" in capsys.readouterr().err


def test_cli_printify_check(no_env_file, monkeypatch, capsys):
    fake = FakePrintify()
    monkeypatch.setattr(printify, "Client", lambda token: real_client(token, fake))
    monkeypatch.setenv("PRINTIFY_TOKEN", TOKEN)
    assert cli.main(["--json", "printify-check"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["watching"]["id"] == 5432


def test_cli_printify_check_without_token(no_env_file, capsys):
    assert cli.main(["printify-check"]) == 1
    assert "PRINTIFY_TOKEN is not set" in capsys.readouterr().out


def test_env_file_is_read_without_overriding(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nDBC_T1=one\nexport DBC_T2='two words'\nDBC_T3=\"q\"\nDBC_T4=from-file\nnot a line\n")
    monkeypatch.setenv("DBC_T4", "already-set")
    for k in ("DBC_T1", "DBC_T2", "DBC_T3"):
        monkeypatch.delenv(k, raising=False)
    config.load_env(env)
    assert (os.environ["DBC_T1"], os.environ["DBC_T2"], os.environ["DBC_T3"]) == ("one", "two words", "q")
    assert os.environ["DBC_T4"] == "already-set"
    for k in ("DBC_T1", "DBC_T2", "DBC_T3"):
        monkeypatch.delenv(k)


def test_vendored_toml_reader_matches_tomllib():
    from dbc._vendor import tomli
    raw = (config.CONFIG_DIR / "shop.toml").read_text(encoding="utf-8")
    assert tomli.loads(raw) == config.tomllib.loads(raw)


def test_env_file_prefers_dbc_env_file_then_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DBC_ENV_FILE", str(tmp_path / "x.env"))
    assert config.env_file() == tmp_path / "x.env"
    monkeypatch.delenv("DBC_ENV_FILE")
    home_env = tmp_path / ".config" / "dinnerbellco" / ".env"
    monkeypatch.setattr(config, "ENV_FILES", (home_env, tmp_path / "etc.env"))
    (tmp_path / "etc.env").write_text("")
    assert config.env_file() == tmp_path / "etc.env"
    home_env.parent.mkdir(parents=True)
    home_env.write_text("")
    assert config.env_file() == home_env
