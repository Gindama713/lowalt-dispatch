"""Deterministic checks on environment replies. The prompt is not the only guard."""

from __future__ import annotations

import re

FORBIDDEN_PHRASES = (
    "已充分考虑",
    "万无一失",
    "基本安全",
    "应该没问题",
    "符合所有要求",
    "绝对安全",
    "可以放心飞",
    "已通过所有检查",
    "现实中没有禁飞区",
    "已经获准飞行",
    "已获准飞行",
    "空域已批准",
)
_NUMBER = re.compile(r"(-?\d+(?:\.\d+)?)\s*(mm/h|m/s|Wh|mm|kg)")
_RECOMMEND = re.compile(r"建议.{0,12}(起飞|出发)")
_LAW = re.compile(r"第\s*\d+\s*条")


def _numbers(value, found: set[float]):
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        found.add(float(value))
    elif isinstance(value, dict):
        for item in value.values():
            _numbers(item, found)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _numbers(item, found)


def verify_response_honesty(reply: str, results: dict, *, asked_flight_feasibility: bool) -> list[str]:
    violations = []
    env = results.get("assess_route_environment") if isinstance(results, dict) else None
    if isinstance(env, dict) and env.get("verdict") and env.get("verdict") != "pass":
        if env["verdict"] not in reply:
            violations.append("reply_missing_verdict_word")
    if isinstance(env, dict):
        if "未判定" not in reply and "gaps" not in reply and not re.search(r"\d+\s*项", reply):
            violations.append("reply_missing_gaps")
    if asked_flight_feasibility and re.search(r"(可以飞|没问题|安全)$", reply.strip().split("\n")[-1]):
        violations.append("feasibility_claim")
    for phrase in FORBIDDEN_PHRASES:
        if phrase in reply:
            violations.append(f"forbidden:{phrase}")
    if _RECOMMEND.search(reply):
        violations.append("recommended_departure")
    if _LAW.search(reply) and "search_project_docs" not in results:
        violations.append("unsourced_legal_article")
    known: set[float] = set()
    _numbers(results, known)
    for match in _NUMBER.finditer(reply):
        number = float(match.group(1))
        if not any(abs(number - item) <= 1e-6 or abs(number - round(item, 1)) <= 1e-6 for item in known):
            violations.append(f"unsourced_number:{match.group(0)}")
    if re.search(r"\d+\.\d{4,}", reply):
        violations.append("false_precision")
    return violations


def forced_disclosure(results: dict) -> str:
    env = results.get("assess_route_environment") if isinstance(results, dict) else None
    verdict = env.get("verdict") if isinstance(env, dict) else "unknown"
    gaps = env.get("gaps") if isinstance(env, dict) else []
    count = len(gaps or [])
    first = (gaps or [{}])[0].get("factor", "未列出")
    word = {"unknown": "未知", "blocked": "blocked", "degraded": "degraded", "pass": "pass"}.get(
        verdict, verdict
    )
    return f"补充：本轮环境判定为 `{word}`，另有 {count} 项未完全判定（首项 {first}）。本回复不构成飞行批准。"
