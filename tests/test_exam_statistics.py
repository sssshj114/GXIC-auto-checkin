import unittest
from unittest.mock import patch

from auto_checkin.core import exam


class ExamStatisticsTests(unittest.TestCase):
    def test_get_answer_id_does_not_double_count_deepseek_calls(self):
        with patch("auto_checkin.core.exam.call_deepseek", return_value="opt-1") as call_mock, patch.object(
            exam.statistics, "record_deepseek_call"
        ) as record_call_mock:
            answer_id = exam._get_answer_id(
                "题干：测试题", [{"ID": "opt-1"}], "测试课程", "测试试卷", "task-1"
            )

        self.assertEqual(answer_id, "opt-1")
        call_mock.assert_called_once()
        record_call_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
