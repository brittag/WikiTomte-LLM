#!/usr/bin/env python3
"""Shared configuration loader for ai-cleanup tools."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config.json"
USER_AGENT_ENV = "WIKITOMTE_USER_AGENT"

PLACEHOLDER_USER_AGENT = (
    "AICleanupBot/1.0 (Your Name, you@example.com) AICleanup/1.0"
)

_SETUP_MESSAGE = (
    "Set WIKITOMTE_USER_AGENT (Toolforge: toolforge env set; "
    "GitHub Codespaces: repository secret) or copy config.example.json "
    "to config.json and set user_agent to your contact info.\n"
    "See: https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy"
)


def load_config(path: Path = CONFIG_PATH) -> Dict[str, Any]:
    """Load config.json if present; return empty dict otherwise."""
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _validate_user_agent(ua: str) -> str:
    if not ua:
        raise ValueError(f"user_agent is not set. {_SETUP_MESSAGE}")

    if ua == PLACEHOLDER_USER_AGENT:
        raise ValueError(
            "user_agent is still the placeholder. "
            f"Edit it with your real contact info. {_SETUP_MESSAGE}"
        )

    return ua


def get_user_agent() -> str:
    """Return User-Agent from env or config.json. Raises ValueError if not configured."""
    env_ua = os.environ.get(USER_AGENT_ENV, "").strip()
    if env_ua:
        return _validate_user_agent(env_ua)

    if not CONFIG_PATH.is_file():
        raise ValueError(f"config.json not found. {_SETUP_MESSAGE}")

    config = load_config()
    ua = str(config.get("user_agent", "")).strip()
    return _validate_user_agent(ua)
