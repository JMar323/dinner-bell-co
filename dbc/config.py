"""Loads config/*.toml and idea files."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
BANNED_TERMS = ROOT / "data" / "banned_terms.txt"


def load_toml(path: str | Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def shop(config_dir: Path = CONFIG_DIR) -> dict:
    return load_toml(config_dir / "shop.toml")


def products(config_dir: Path = CONFIG_DIR) -> dict:
    return load_toml(config_dir / "products.toml")
