#!/usr/bin/env python3
"""Unit tests for wikimedia_http backoff (no network)."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wikimedia_http import (
    FORBIDDEN_MESSAGE,
    RATE_LIMIT_MESSAGE,
    RateLimitError,
    get_with_backoff,
)


def _mock_response(status_code: int, *, retry_after: str | None = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.headers = {"Retry-After": retry_after} if retry_after else {}
    if status_code >= 400 and status_code != 429:
        resp.raise_for_status.side_effect = mock.Mock(
            side_effect=__import__("requests").HTTPError(response=resp)
        )
    return resp


class TestGetWithBackoff(unittest.TestCase):
    def test_retries_429_then_succeeds(self):
        session = mock.MagicMock()
        session.get.side_effect = [
            _mock_response(429),
            _mock_response(200),
        ]
        with mock.patch("wikimedia_http.time.sleep") as sleep_mock:
            resp = get_with_backoff(session, "https://example.test/api", {"action": "query"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(session.get.call_count, 2)
        sleep_mock.assert_called_once_with(1.0)

    def test_respects_retry_after_header(self):
        session = mock.MagicMock()
        session.get.side_effect = [
            _mock_response(429, retry_after="3"),
            _mock_response(200),
        ]
        with mock.patch("wikimedia_http.time.sleep") as sleep_mock:
            get_with_backoff(session, "https://example.test/api", {"action": "query"})
        sleep_mock.assert_called_once_with(3.0)

    def test_raises_rate_limit_error_after_max_retries(self):
        session = mock.MagicMock()
        session.get.return_value = _mock_response(429)
        with mock.patch("wikimedia_http.time.sleep"):
            with self.assertRaises(RateLimitError) as ctx:
                get_with_backoff(
                    session,
                    "https://example.test/api",
                    {"action": "query"},
                    max_retries=2,
                )
        self.assertEqual(str(ctx.exception), RATE_LIMIT_MESSAGE)
        self.assertEqual(session.get.call_count, 3)

    def test_403_raises_permission_error_without_retry(self):
        session = mock.MagicMock()
        session.get.return_value = _mock_response(403)
        with self.assertRaises(PermissionError) as ctx:
            get_with_backoff(session, "https://example.test/api", {"action": "query"})
        self.assertEqual(str(ctx.exception), FORBIDDEN_MESSAGE)
        session.get.assert_called_once()


if __name__ == "__main__":
    unittest.main()
