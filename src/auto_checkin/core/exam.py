# -*- coding: utf-8 -*-
"""
答题模块 - AI自动答题
"""

from __future__ import annotations

import re
import time
import random
import requests
from auto_checkin.logger import log
from auto_checkin.network import validate_json_response, ApiResponseError, with_retry, call_deepseek
from auto_checkin.config import SCAN_CONFIG, BASE_URL
from auto_checkin.core.session import session_manager
from auto_checkin.core.state import exam_state, course_registry
from auto_checkin.core.statistics import statistics


def process_exam(icid: str, course_element_id: str, cname: str, exam_name: str):
    """处理试卷"""
    log(f"[AI答题] 开始处理 {cname} 的试卷：{exam_name}")
    headers = session_manager.get_headers_copy()
    headers["Content-Type"] = "application/json"

    statistics.record_exam_attempt()

    ch_id = _get_ch_id(course_element_id, headers)
    if not ch_id:
        log("   [失败] 获取准考证失败")
        exam_state.release(course_element_id)
        statistics.record_exam_failed()
        statistics.record_error("获取准考证失败")
        statistics.log_operation("exam", cname, f"答题失败: {exam_name} - 获取准考证失败", False)
        return

    questions = _get_questions(ch_id, headers)
    if not questions:
        log("   [失败] 试卷无题目")
        exam_state.release(course_element_id)
        statistics.record_exam_failed()
        statistics.log_operation("exam", cname, f"答题失败: {exam_name} - 试卷无题目", False)
        return

    log(f"   [信息] 获取试卷成功，共 {len(questions)} 道题目")
    submit_ches = _solve_questions(questions, cname, exam_name)

    _submit_exam(
        ch_id, submit_ches, headers, icid, course_element_id, cname, exam_name, len(questions)
    )


def process_exam_manual(icid: str, course_element_id: str, cname: str, exam_name: str) -> dict:
    """手动补做作业/测验，绕过 exam_state 去重。返回 {"success", "detail", "questions"}。"""
    log(f"[补做] 用户手动触发 {cname} 的试卷：{exam_name}")
    headers = session_manager.get_headers_copy()
    headers["Content-Type"] = "application/json"

    statistics.record_exam_attempt()

    ch_id = _get_ch_id(course_element_id, headers)
    if not ch_id:
        # 不是考试（粘贴板/一句话问答等），尝试用评论接口回复
        log(f"   [信息] 无准考证，尝试用评论方式回复...")
        try:
            text = call_deepseek(f"请简短回答这个问题（不超过100字）：{exam_name}")
            text = text.strip()[:300]
            log(f"   [文字回答] {exam_name[:30]}... → {text[:50]}...")
        except Exception as e:
            log(f"   [异常] AI 生成回答失败: {e}")
            text = ""

        if not text:
            statistics.record_exam_failed()
            return {"success": False, "detail": "AI 无法生成回答", "questions": 0}

        url = f"{BASE_URL}/webios/addComment"
        try:
            res = requests.post(url, headers=headers, json={"id": course_element_id, "content": text, "Type": 2}, timeout=5)
            validate_json_response(res, f"reply({exam_name})",
                validator=lambda d: (d.get("code") == 1 or d.get("status") == 1 or d.get("success") is True, f"code={d.get('code')}"))
            log(f"   [成功] 评论回复成功")
            statistics.record_exam_success(0)
            statistics.log_operation("exam", cname, f"回复: {exam_name}", True)
            return {"success": True, "detail": "文字回复成功", "questions": 0}
        except Exception as e:
            log(f"   [失败] 评论回复失败: {e}")
            statistics.record_exam_failed()
            statistics.log_operation("exam", cname, f"回复失败: {exam_name} - {e}", False)
            return {"success": False, "detail": f"回复失败: {e}", "questions": 0}

    questions = _get_questions(ch_id, headers)
    if not questions:
        statistics.record_exam_failed()
        statistics.log_operation("exam", cname, f"补做失败: {exam_name} - 试卷无题目", False)
        return {"success": False, "detail": "试卷无题目", "questions": 0}

    log(f"   [信息] 补做试卷，共 {len(questions)} 道题目")
    submit_ches = _solve_questions(questions, cname, exam_name)

    log("   [信息] 答题完成，正在交卷...")
    try:
        _save_answer(ch_id, submit_ches, headers)
        log("   [信息] 保存答案成功")
    except (ApiResponseError, requests.RequestException) as e:
        log(f"   [警告] 保存答案被服务器拒绝: {e}")

    try:
        log("   [信息] 正在调用交卷接口...")
        _submit_assignment(ch_id, submit_ches, headers)
        log(f"   [成功] 交卷接口返回成功")
        course_registry.increment_counter(icid, "exam_count")
        statistics.record_exam_success(len(questions))
        statistics.log_operation("exam", cname, f"补做完成: {exam_name}，共 {len(questions)} 题", True)
        return {"success": True, "detail": f"补做完成，共 {len(questions)} 题", "questions": len(questions)}
    except ApiResponseError as e:
        log(f"   [失败] 交卷被服务器拒绝: {e}")
        statistics.record_exam_failed()
        statistics.log_operation("exam", cname, f"补做交卷失败: {exam_name} - {e}", False)
        return {"success": False, "detail": f"交卷失败: {e}", "questions": len(questions)}
    except Exception as e:
        log(f"   [失败] 交卷异常: {e}")
        statistics.record_exam_failed()
        statistics.log_operation("exam", cname, f"补做异常: {exam_name} - {e}", False)
        return {"success": False, "detail": f"异常: {e}", "questions": len(questions)}


def _get_ch_id(course_element_id: str, headers: dict) -> str:
    """获取准考证ID"""
    try:
        res = requests.post(
            f"{BASE_URL}/webios/partStudentTestByCHID",
            headers=headers,
            json={"courseElmentId": course_element_id},
            timeout=5,
        )
        data = validate_json_response(
            res,
            f"get_ch_id({course_element_id})",
            validator=lambda d: (
                bool(d.get("CH_ID")),
                d.get("msg") or "缺少 CH_ID",
            ),
        )
        return data.get("CH_ID")
    except (requests.RequestException, ApiResponseError, TypeError, ValueError) as e:
        log(f"   [异常] 获取准考证失败: {e}")
        return None


def _get_questions(ch_id: str, headers: dict) -> list:
    """获取题目列表"""
    try:
        res = requests.post(
            f"{BASE_URL}/webios/getTestQuestionList",
            headers=headers,
            json={"CH_ID": ch_id},
            timeout=5,
        )
        data = validate_json_response(
            res,
            f"get_questions({ch_id})",
            validator=lambda d: (
                isinstance(d.get("list", []), list) and len(d.get("list", [])) > 0,
                d.get("msg") or "题目列表为空",
            ),
        )
        return data.get("list", [])
    except (requests.RequestException, ApiResponseError, TypeError, ValueError) as e:
        log(f"   [异常] 获取题目失败: {e}")
        return []


def _solve_questions(questions: list, cname: str, exam_name: str) -> list:
    """AI 解题：选择题选选项，文字题生成文字回答"""
    results = []

    for q in questions:
        think_time = random.randint(
            SCAN_CONFIG["exam_think_time_min"],
            SCAN_CONFIG["exam_think_time_max"],
        )
        time.sleep(think_time)

        qb_type = q.get("QB_Type", 1)
        task_id = q.get("TaskContent_ID")
        q_html = q.get("QB_Content", "")
        q_text = re.sub(r"<[^>]+>", "", q_html).replace("&nbsp;", "").strip()
        options = q.get("QPerContent", [])

        if not options:
            # 无选项 → 文字题，先让 AI 判断是否需要上传图片
            judge_prompt = f"以下题目是否需要上传图片/拍照/截图？如果是，只回答\"SKIP\"；如果不是，只回答\"TEXT\"。\n题目：{q_text}"
            try:
                judge = call_deepseek(judge_prompt).strip().upper()
            except Exception as e:
                log(f"   [异常] AI 判断题目类型失败: {e}")
                judge = "TEXT"

            if "SKIP" in judge:
                log(f"   [跳过] 需要上传图片：{q_text[:30]}...")
                results.append(
                    {"content": "", "QB_Type": qb_type, "taskContent_ID": task_id}
                )
                continue

            # 不需要图片 → AI 生成文字回答
            prompt = f"请直接回答以下问题（简短准确，不超过200字）：\n{q_text}"
            try:
                text_answer = call_deepseek(prompt)
                text_answer = text_answer.strip()[:500]
                log(f"   [文字回答] {q_text[:30]}... → {text_answer[:50]}...")
            except Exception as e:
                log(f"   [异常] AI 生成文字回答失败: {e}")
                text_answer = ""
            results.append(
                {"content": text_answer, "QB_Type": qb_type, "taskContent_ID": task_id}
            )
            continue

        # 有选项 → 选择题，用 AI 选选项
        prompt = f"题干：{q_text}\n"
        for opt in options:
            opt_text = (
                re.sub(r"<[^>]+>", "", opt.get("Content", ""))
                .replace("&nbsp;", "")
                .strip()
            )
            prompt += f"选项ID[{opt['ID']}]: {opt_text}\n"
        prompt += "请告诉我哪个选项正确，只输出选项ID。"

        ans_id = _get_answer_id(prompt, options, cname, exam_name, task_id)
        time.sleep(0.5)

        results.append(
            {"content": ans_id, "QB_Type": qb_type, "taskContent_ID": task_id}
        )

    return results


def _get_answer_id(
    prompt: str, options: list, cname: str, exam_name: str, task_id: str
) -> str:
    """获取答案ID"""
    option_ids = [str(opt.get("ID", "")).strip() for opt in options if opt.get("ID")]
    if not option_ids:
        return ""

    try:
        raw_answer = call_deepseek(prompt)
        answer_id = _extract_valid_option_id(raw_answer, option_ids)

        if answer_id:
            return answer_id

        log(f"   [警告] AI 首次返回无效选项，重试中...")
        retry_prompt = prompt + f"\n请从以下ID中选择: {', '.join(option_ids)}"
        retry_answer = call_deepseek(retry_prompt)
        answer_id = _extract_valid_option_id(retry_answer, option_ids)

        if answer_id:
            return answer_id

        fallback_id = random.choice(option_ids)
        log(f"   [警告] AI 返回无效，随机选择: {fallback_id}")
        return fallback_id

    except Exception as e:
        statistics.record_deepseek_error()
        log(f"   [异常] AI 调用失败: {e}")
        return random.choice(option_ids) if option_ids else ""


def _extract_valid_option_id(raw_answer: str, option_ids: list) -> str:
    """提取有效选项ID"""
    if not raw_answer:
        return None

    answer = str(raw_answer).strip()
    if answer in option_ids:
        return answer

    matched_ids = [
        option_id for option_id in option_ids if option_id and option_id in answer
    ]
    if len(matched_ids) == 1:
        return matched_ids[0]

    return None


@with_retry(max_attempts=3, delay=1.0, backoff=2.0)
def _save_answer(ch_id: str, submit_ches: list, headers: dict):
    """保存答案"""
    response = requests.post(
        f"{BASE_URL}/webios/SaveStudentAnswer",
        headers=headers,
        json={"CH_ID": ch_id, "SubmitCHes": submit_ches},
        timeout=10,
    )
    return validate_json_response(
        response,
        f"save_answer({ch_id})",
        validator=lambda data: (
            data.get("code") == 1
            or data.get("status") == 1
            or data.get("success") is True,
            f"code={data.get('code')}, msg={data.get('msg') or '无'}",
        ),
    )


@with_retry(max_attempts=3, delay=1.0, backoff=2.0)
def _submit_assignment(ch_id: str, submit_ches: list, headers: dict):
    """交卷"""
    response = requests.post(
        f"{BASE_URL}/webios/StudentSubmitAssignment",
        headers=headers,
        json={"CH_ID": ch_id, "SubmitCHes": submit_ches},
        timeout=10,
    )
    return validate_json_response(
        response,
        f"submit_assignment({ch_id})",
        validator=lambda data: (
            data.get("code") == 1
            or data.get("status") == 1
            or data.get("success") is True,
            f"code={data.get('code')}, msg={data.get('msg') or '无'}",
        ),
    )


def _submit_exam(
    ch_id: str,
    submit_ches: list,
    headers: dict,
    icid: str,
    course_element_id: str,
    cname: str,
    exam_name: str,
    questions_count: int,
):
    """提交试卷"""
    log("   [信息] 答题完成，正在交卷...")

    save_ok = False
    try:
        _save_answer(ch_id, submit_ches, headers)
        save_ok = True
    except ApiResponseError as e:
        log(f"   [警告] 保存答案被服务器拒绝（可能已提交或CH_ID失效）: {e}")
    except Exception as e:
        log(f"   [失败] 保存答案网络异常，稍后重试: {e}")
        exam_state.release(course_element_id)
        statistics.record_exam_failed()
        statistics.record_error(f"保存答案网络异常: {e}")
        statistics.log_operation("exam", cname, f"保存答案失败: {exam_name} - {e}", False)
        return

    try:
        _submit_assignment(ch_id, submit_ches, headers)
        if save_ok:
            log(f"   [成功] 试卷提交成功：{exam_name}")
        else:
            log(f"   [成功] 已交卷（保存答案步骤被服务器拒绝，但交卷成功）：{exam_name}")
        course_registry.increment_counter(icid, "exam_count")
        exam_state.finish(course_element_id)
        statistics.record_exam_success(questions_count)
        statistics.log_operation("exam", cname, f"提交试卷: {exam_name}，共 {questions_count} 题", True)

    except ApiResponseError as e:
        log(f"   [失败] 交卷被服务器拒绝，标记完成不再重试: {e}")
        exam_state.finish(course_element_id)
        statistics.record_exam_failed()
        statistics.record_error(f"交卷业务失败: {e}")
        statistics.log_operation("exam", cname, f"交卷失败: {exam_name} - {e}", False)

    except Exception as e:
        log(f"   [失败] 交卷网络异常，稍后重试: {e}")
        exam_state.release(course_element_id)
        statistics.record_exam_failed()
        statistics.record_error(f"交卷网络异常: {e}")
        statistics.log_operation("exam", cname, f"交卷失败: {exam_name} - {e}", False)
