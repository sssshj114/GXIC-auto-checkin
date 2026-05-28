import unittest
from unittest.mock import Mock, patch

from auto_checkin.core import scheduler


class SchedulerCheckinCodeTests(unittest.TestCase):
    def test_run_scan_submits_stolen_code(self):
        fake_courses = {"ic-1": {"checked": False, "name": "测试课程"}}
        submit_mock = Mock()

        with patch.object(scheduler.course_registry, "get_snapshot", return_value=fake_courses), patch(
            "auto_checkin.core.scheduler.scan_and_reply_material", return_value=None
        ), patch("auto_checkin.core.scheduler.scan_checkin", return_value="check-1"), patch.object(
            scheduler.checkin_state, "claim", return_value=True
        ), patch(
            "auto_checkin.core.scheduler.steal_code", return_value="real-code"
        ), patch(
            "auto_checkin.core.scheduler.submit_checkin_task", submit_mock
        ), patch(
            "auto_checkin.core.scheduler.log", return_value=None
        ):
            scheduler._run_scan(is_fast=True)

        submit_mock.assert_called_once_with("real-code", "check-1", "ic-1", "测试课程", True)


if __name__ == "__main__":
    unittest.main()
