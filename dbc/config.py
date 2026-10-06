"""Loads config/*.toml, idea files and the secrets file."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
BANNED_TERMS = ROOT / "data" / "banned_terms.txt"
# Secrets live on the VPS, never in the repo (docs/keys.md). DBC_ENV_FILE overrides the path.
ENV_FILE = Path("/etc/dinnerbellco/.env")


def load_env(path: str | Path | None = None) -> None:
    """Read KEY=VALUE lines into os.environ. Variables already set win; a missing file is fine."""
    path = Path(path or os.environ.get("DBC_ENV_FILE") or ENV_FILE)
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError):
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def state_dir() -> Path:
    """Where routines remember what they already alerted on. Must be writable by the n8n user."""
    return Path(os.environ.get("DBC_STATE_DIR") or ROOT / "state")


def load_toml(path: str | Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def shop(config_dir: Path = CONFIG_DIR) -> dict:
    return load_toml(config_dir / "shop.toml")


def products(config_dir: Path = CONFIG_DIR) -> dict:
    return load_toml(config_dir / "products.toml")
