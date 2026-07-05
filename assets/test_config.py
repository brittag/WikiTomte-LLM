#!/usr/bin/env python3
"""Unit tests for shared config loader."""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from config import PLACEHOLDER_USER_AGENT, USER_AGENT_ENV, get_user_agent, load_config


class TestConfig(unittest.TestCase):
    def test_load_config_missing_returns_empty(self):
        self.assertEqual(load_config(Path("/nonexistent/config.json")), {})

    def test_missing_config_file_raises(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(config, "CONFIG_PATH", Path("/nonexistent/config.json")):
            with self.assertRaises(ValueError) as ctx:
                get_user_agent()
            self.assertIn("config.json not found", str(ctx.exception))

    def test_empty_user_agent_raises(self):
        fake = mock.MagicMock(spec=Path)
        fake.is_file.return_value = True
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(config, "CONFIG_PATH", fake), \
             mock.patch.object(config, "load_config", return_value={}):
            with self.assertRaises(ValueError) as ctx:
                get_user_agent()
            self.assertIn("not set", str(ctx.exception))

    def test_placeholder_user_agent_raises(self):
        fake = mock.MagicMock(spec=Path)
        fake.is_file.return_value = True
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(config, "CONFIG_PATH", fake), \
             mock.patch.object(config, "load_config", return_value={"user_agent": PLACEHOLDER_USER_AGENT}):
            with self.assertRaises(ValueError) as ctx:
                get_user_agent()
            self.assertIn("placeholder", str(ctx.exception))

    def test_valid_user_agent(self):
        fake = mock.MagicMock(spec=Path)
        fake.is_file.return_value = True
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(config, "CONFIG_PATH", fake), \
             mock.patch.object(config, "load_config", return_value={"user_agent": "MyBot/1.0 (me@example.com)"}):
            self.assertEqual(get_user_agent(), "MyBot/1.0 (me@example.com)")

    def test_env_var_takes_precedence(self):
        fake = mock.MagicMock(spec=Path)
        fake.is_file.return_value = True
        env = {USER_AGENT_ENV: "CodespacesBot/1.0 (user@example.com)"}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(config, "CONFIG_PATH", fake), \
             mock.patch.object(config, "load_config", return_value={"user_agent": "FileBot/1.0"}):
            self.assertEqual(get_user_agent(), "CodespacesBot/1.0 (user@example.com)")


if __name__ == "__main__":
    unittest.main()
