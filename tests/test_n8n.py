"""The exported n8n workflows stay importable and only ever call our read-only commands."""

import json
import re

import pytest

from dbc import config

WORKFLOWS = sorted((config.ROOT / "n8n").glob("*.json"))
COMMAND = re.compile(r"^cd ~/dinner-bell-co && python3 -m dbc --json (draft|printify-check|watch-orders)\b")


def test_there_are_workflows():
    assert {p.name for p in WORKFLOWS} >= {"order-watcher.json", "error-alert.json", "setup-check.json"}


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_is_well_formed(path):
    wf = json.loads(path.read_text(encoding="utf-8"))
    names = [n["name"] for n in wf["nodes"]]
    assert len(names) == len(set(names))
    for src, outputs in wf["connections"].items():
        assert src in names
        for branch in outputs["main"]:
            assert all(link["node"] in names for link in branch)
    assert wf["active"] is False                     # John turns it on after picking credentials
    text = path.read_text(encoding="utf-8")
    assert not re.search(r"(TOKEN|SECRET|API_KEY)=\S", text)
    assert '"credentials"' not in text                # no credential ids from someone else's n8n


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_commands_are_ours_and_read_only(path):
    wf = json.loads(path.read_text(encoding="utf-8"))
    for n in wf["nodes"]:
        if n["type"] == "n8n-nodes-base.executeCommand":
            assert COMMAND.match(n["parameters"]["command"]), n["parameters"]["command"]


def test_watcher_runs_every_30_minutes_in_ohio_time():
    wf = json.loads((config.ROOT / "n8n" / "order-watcher.json").read_text(encoding="utf-8"))
    trigger = next(n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.scheduleTrigger")
    assert trigger["parameters"]["rule"]["interval"][0]["expression"] == "*/30 7-21 * * *"
    assert wf["settings"]["timezone"] == "America/New_York"
