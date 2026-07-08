#!/usr/bin/env python3
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parent


class SecurityDefaultsTest(unittest.TestCase):
    def test_reverse_ws_defaults_to_loopback(self):
        source = (ROOT / "napcat_adapter.py").read_text(encoding="utf-8")

        self.assertIn('附加配置.get("reverse_host", "127.0.0.1")', source)

    def test_public_reverse_ws_requires_access_token(self):
        source = (ROOT / "napcat_adapter.py").read_text(encoding="utf-8")

        self.assertIn("_is_loopback_host", source)
        self.assertIn("反向 WebSocket 公开监听时必须配置 access_token", source)


if __name__ == "__main__":
    unittest.main()
