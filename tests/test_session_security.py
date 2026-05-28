import unittest
from unittest.mock import Mock, patch

from auto_checkin.core import session


class SessionSecurityTests(unittest.TestCase):
    def test_auto_login_does_not_persist_cookie_by_default(self):
        fake_session = Mock()
        fake_session.cookies.get_dict.return_value = {
            "ASP.NET_SessionId": "sid",
            ".ASPXAUTH": "auth",
        }
        fake_session.get.return_value = Mock()
        fake_session.post.return_value = Mock(text="ok")

        manager = session.SessionManager()

        with patch("auto_checkin.core.session.requests.Session", return_value=fake_session), patch(
            "auto_checkin.core.session._update_env"
        ) as update_env_mock, patch("auto_checkin.core.session.COOKIE_PERSIST_ENABLED", False), patch(
            "auto_checkin.core.session.WEIXIN_ID", "wx"
        ), patch("auto_checkin.core.session.STUDENT_CODE", "stu"), patch(
            "auto_checkin.core.session.LOGIN_PASSWORD", "pwd"
        ), patch(
            "auto_checkin.core.session.PHOTO_ADDRESS", ""
        ):
            success = session.auto_login(manager)

        self.assertTrue(success)
        self.assertEqual(manager.get_headers_copy()["Cookie"], "ASP.NET_SessionId=sid; .ASPXAUTH=auth")
        update_env_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
