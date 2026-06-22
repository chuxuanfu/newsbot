from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    root: Path
    config_path: Path
    db_path: Path
    config: dict[str, Any]


def load_settings(config_path: str | None = None) -> Settings:
    load_dotenv()
    root = Path(__file__).resolve().parents[1]
    path = Path(
        config_path
        or os.environ.get("NEWSBOT_CONFIG")
        or root / "config.yaml"
    ).expanduser()
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    db_path = Path(
        os.environ.get("NEWSBOT_DB")
        or config.get("database", {}).get("path", "")
        or root / "data" / "newsbot.sqlite3"
    ).expanduser()
    return Settings(root=root, config_path=path, db_path=db_path, config=config)


def env_value(name: str | None, default: str = "") -> str:
    if not name:
        return default
    return os.environ.get(name, default)

