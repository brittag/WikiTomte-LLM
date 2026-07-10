#!/usr/bin/env python3
"""Shared HTTP helpers for Wikimedia Action API clients."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict

import requests

log = logging.getLogger(__name__)

RATE_LIMIT_MESSAGE = "Wikipedia rate limit — try again in a few minutes."

FORBIDDEN_MESSAGE = (
    "403 Forbidden — check User-Agent. See Wikimedia User-Agent policy."
)


class RateLimitError(Exception):
    """Raised when Wikipedia returns 429 after retries are exhausted."""


def _retry_after_seconds(resp: requests.Response) -> float | None:
    header = resp.headers.get("Retry-After")
    if not header:
        return None
    try:
        return max(0.0, float(header))
    except (TypeError, ValueError):
        return None


def get_with_backoff(
    session: requests.Session,
    url: str,
    params: Dict[str, Any],
    *,
    timeout: float = 30,
    max_retries: int = 5,
    base_delay: float = 1.0,
) -> requests.Response:
    """GET with exponential backoff on HTTP 429; respect Retry-After when present."""
    for attempt in range(max_retries + 1):
        resp = session.get(url, params=params, timeout=timeout)
        if resp.status_code == 403:
            raise PermissionError(FORBIDDEN_MESSAGE)
        if resp.status_code != 429:
            resp.raise_for_status()
            return resp
        if attempt >= max_retries:
            raise RateLimitError(RATE_LIMIT_MESSAGE)
        retry_after = _retry_after_seconds(resp)
        delay = retry_after if retry_after is not None else base_delay * (2 ** attempt)
        log.warning(
            "Wikipedia returned 429; retrying in %.1fs (attempt %d/%d)",
            delay,
            attempt + 1,
            max_retries,
        )
        time.sleep(delay)
    raise RateLimitError(RATE_LIMIT_MESSAGE)
