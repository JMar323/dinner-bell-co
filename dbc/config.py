"""Loads config/*.toml, idea files and the secrets file."""

from __future__ import annotations

import os
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:          # Python 3.10 (John's server); same code as 3.11's tomllib
    from ._vendor import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
BANNED_TERMS = ROOT / "data" / "banned_terms.txt"
# Secrets live on the VPS, never in the repo (docs/keys.md). The first file that exists wins;
# DBC_ENV_FILE overrides both. The home-folder one is for servers without sudo (xCloud).
ENV_FILES = (Path.home() / ".config" / "dinnerbellco" / ".env", Path("/etc/dinnerbellco/.env"))


def env_file() -> Path:
    if os.environ.get("DBC_ENV_FILE"):
        return Path(os.environ["DBC_ENV_FILE"])
    for p in ENV_FILES:
        try:
            if p.exists():
                return p
        except PermissionError:
            continue
    return ENV_FILES[0]


def load_env(path: str | Path | None = None) -> None:
    """Read KEY=VALUE lines into os.environ. Variables already set win; a missing file is fine."""
    path = Path(path) if path else env_file()
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
