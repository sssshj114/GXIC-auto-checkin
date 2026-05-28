import unittest

from auto_checkin.web import _is_request_authorized


class WebAuthTests(unittest.TestCase):
    def test_empty_token_allows_only_loopback(self):
        self.assertTrue(_is_request_authorized("", "", "127.0.0.1"))
        self.assertTrue(_is_request_authorized("", "", "::1"))
        self.assertFalse(_is_request_authorized("", "", "192.168.1.10"))

    def test_configured_token_requires_matching_bearer(self):
        token = "abc123"
        self.assertTrue(_is_request_authorized(token, "Bearer abc123", "192.168.1.10"))
        self.assertFalse(_is_request_authorized(token, "", "127.0.0.1"))
        self.assertFalse(_is_request_authorized(token, "Bearer wrong", "127.0.0.1"))


if __name__ == "__main__":
    unittest.main()
