"""Versioned UI blocks built from tool evidence. No model-generated executable UI."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import Field

from services.assistant.models import Contract
from services.assistant.task_evidence import TaskEvidence


class Block(Contract):
    title: str = Field(max_length=80)
    source: str = Field(max_length=240)
    as_of: str | None = Field(default=None, max_length=80)
    note: str = Field(default="", max_length=600)


class Metric(Contract):
    label: str = Field(max_length=60)
    value: float | None
    unit: str = Field(default="", max_length=24)


class MetricsBlock(Block):
    type: Literal["metrics"] = "metrics"
    items: list[Metric] = Field(min_length=1, max_length=8)


class Datum(Contract):
    label: str = Field(max_length=80)
    value: float


class ChartSpec(Contract):
    type: Literal["bar", "pie", "line"]
    title: str = Field(max_length=80)
    unit: str = Field(default="", max_length=24)
    data: list[Datum] = Field(min_length=1, max_length=12)


class ChartBlock(Block):
    type: Literal["chart"] = "chart"
    chart: ChartSpec


class TableBlock(Block):
    type: Literal["table"] = "table"
    columns: list[str] = Field(min_length=1, max_length=6)
    rows: list[list[str | float | None]] = Field(max_length=20)


class TimelineItem(Contract):
    time: str = Field(max_length=80)
    title: str = Field(max_length=200)
    detail: str = Field(default="", max_length=1000)
    level: Literal["info", "warning", "success"] = "info"


class TimelineBlock(Block):
    type: Literal["timeline"] = "timeline"
    items: list[TimelineItem] = Field(max_length=30)


class RouteBlock(Block):
    type: Literal["route"] = "route"
    route_id: str = Field(max_length=160)
    draft_digest: str = Field(max_length=160)
    length_m: float = Field(ge=0)
    waypoints: list[tuple[float, float]] = Field(min_length=2, max_length=5000)


class TaskEvidenceBlock(Block):
    type: Literal["task_evidence"] = "task_evidence"
    evidence: TaskEvidence


class EnvFactor(Contract):
    id: str = Field(max_length=64)
    name: str = Field(max_length=40)
    status: Literal["modeled", "threshold_only", "not_evaluated", "unavailable"]
    value: float | str | None = None
    unit: str = Field(default="", max_length=16)
    threshold: float | None = None
    threshold_source: str | None = Field(default=None, max_length=200)
    effect: Literal["hard", "soft", "info"] = "info"
    segment_index: int | None = Field(default=None, ge=0)
    reason: str = Field(default="", max_length=300)


class EnvMatrixBlock(Block):
    type: Literal["env_matrix"] = "env_matrix"
    verdict: Literal["pass", "degraded", "blocked", "unknown"]
    verdict_reason: str = Field(max_length=400)
    factors: list[EnvFactor] = Field(min_length=1, max_length=40)
    coverage_statement: str = Field(max_length=400)
    evidence_id: str = Field(max_length=32)


class GapItem(Contract):
    factor: str = Field(max_length=64)
    why: str = Field(max_length=300)
    to_close: str = Field(max_length=300)


class GapsBlock(Block):
    type: Literal["gaps"] = "gaps"
    items: list[GapItem] = Field(min_length=1, max_length=20)
    total: int = Field(ge=0)


class TimeWindowOption(Contract):
    scheduled_for: str = Field(max_length=64)
    verdict: Literal["pass", "degraded", "blocked", "unknown"]
    reason: str = Field(default="", max_length=200)


class TimeWindowBlock(Block):
    type: Literal["time_window"] = "time_window"
    options: list[TimeWindowOption] = Field(min_length=2, max_length=24)
    caveat: str = Field(max_length=400)


UIBlock = Annotated[
    MetricsBlock
    | ChartBlock
    | TableBlock
    | TimelineBlock
    | RouteBlock
    | TaskEvidenceBlock
    | EnvMatrixBlock
    | GapsBlock
    | TimeWindowBlock,
    Field(discriminator="type"),
]


class Presentation(Contract):
    version: Literal[1, 2] = 1
    blocks: list[UIBlock] = Field(max_length=6)


def number(value) -> float | None:
    return (
        float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        else None
    )


def build_presentation(question: str, results: dict[str, dict]) -> Presentation:
    blocks: list[UIBlock] = []
    mission = results.get("inspect_mission_plan")
    if mission and mission.get("status") == "ok":
        results = {
            **results,
            "assess_route_environment": mission["environment"],
            "inspect_airspace_constraints": mission["airspace"],
        }
        blocks.append(
            TableBlock(
                title="任务规划与备降依据",
                source=mission["source"],
                as_of=mission.get("computed_at"),
                columns=["因素", "计算与缺口"],
                rows=mission["rows"],
                note="沿当前工单实际折线的保存结果；不是新气象观测，旧数据需重算。",
            )
        )
    task = results.get("get_task_evidence")
    if task and task.get("status") == "ok":
        blocks.append(
            TaskEvidenceBlock(
                title="任务证据卡",
                source=task["source"],
                as_of=task["evidence"]["generated_at"],
                evidence=TaskEvidence.model_validate(task["evidence"]),
            )
        )
    flight = results.get("get_flight_status")
    if flight and flight.get("telemetry_mode") == "planning":
        route = flight.get("route") or {}
        blocks.append(
            MetricsBlock(
                title="当前规划路线",
                source=flight["source"],
                note=flight["reason"],
                items=[
                    Metric(
                        label="航点",
                        value=len(route["waypoints"]) if route.get("waypoints") else None,
                        unit="个",
                    )
                ],
            )
        )
    if flight and flight.get("telemetry_mode") != "planning":
        sample = flight.get("telemetry") or {}
        blocks.append(
            MetricsBlock(
                title="飞行状态",
                source=flight["source"],
                as_of=flight.get("sampled_at"),
                note="快照已过期，请核对最新遥测。" if flight.get("stale") else "",
                items=[
                    Metric(label=label, value=number(sample.get(key)), unit=unit)
                    for key, label, unit in (
                        ("battery", "电量", "%"),
                        ("altitude", "高度", "m"),
                        ("speed", "速度", "m/s"),
                        ("energyWh", "剩余电量", "Wh"),
                    )
                ],
            )
        )
    weather = results.get("get_weather_forecast")
    if weather and weather.get("status") == "ok":
        values = weather.get("values") or {}
        blocks.append(
            MetricsBlock(
                title="时段天气",
                source=weather["source"],
                as_of=weather.get("valid_for"),
                note="离地 10 米模型预报，航高风况需另外核验。",
                items=[
                    Metric(label=label, value=number(values.get(key)), unit=unit)
                    for key, label, unit in (
                        ("temperature_2m", "气温", "°C"),
                        ("wind_speed_10m", "风速", "m/s"),
                        ("wind_gusts_10m", "阵风", "m/s"),
                        ("precipitation", "降水", "mm"),
                    )
                ],
            )
        )
    overview = results.get("get_intake_overview")
    if overview:
        source = overview.get("source", "logs/intakes 本机工单文件")
        counts = overview.get("status_counts", [])
        blocks.append(
            MetricsBlock(
                title="工单概览",
                source=source,
                note=f"最近 {overview['count']} 张工单，按航线生成状态统计。",
                items=[
                    Metric(label="本次统计", value=overview["count"], unit="单"),
                    *[Metric(label=row["label"], value=row["value"], unit="单") for row in counts[:3]],
                ],
            )
        )
        if "折线图" in question:
            data = (overview.get("latest_route") or {}).get("profile", [])
            kind, title, unit = "line", "航线累计距离", "km"
        elif "柱状图" in question:
            data = overview.get("payloads", [])
            kind, title, unit = "bar", "工单载荷", "kg"
        else:
            data = counts if any(row["value"] > 0 for row in counts) else []
            kind, title, unit = "pie", "航线状态分布", "单"
        if data and "表格" not in question:
            blocks.append(
                ChartBlock(
                    title=title,
                    source=source,
                    note=f"来自最近 {overview['count']} 张工单。",
                    chart=ChartSpec(type=kind, title=title, unit=unit, data=data[:12]),
                )
            )
        if "饼图" not in question and "柱状图" not in question and "折线图" not in question:
            blocks.append(
                TableBlock(
                    title="工单载荷",
                    source=source,
                    columns=["任务", "载荷 / kg"],
                    rows=[[row["label"], row["value"]] for row in overview.get("payloads", [])[:12]],
                    note="当前没有载荷记录。" if not overview.get("payloads") else "",
                )
            )
    events = results.get("list_events")
    if events:
        blocks.append(
            TimelineBlock(
                title="最近事件",
                source=events["source"],
                items=[
                    TimelineItem(
                        time=item["time"],
                        title=item["title"],
                        detail=item.get("detail", ""),
                        level=item.get("type", "info"),
                    )
                    for item in events.get("events", [])[:30]
                ],
                note="当前没有事件记录。" if not events.get("events") else "",
            )
        )
    route = results.get("plan_task_preview")
    if route and route.get("status") == "geometry_only":
        blocks.append(
            RouteBlock(
                title="路线预览",
                source=route["source"],
                route_id=route["route_id"],
                draft_digest=route["draft_digest"],
                length_m=route["length_m"],
                waypoints=route["waypoints"],
                note="本地 ENU 坐标下的几何预览，完整校验见任务流程。",
            )
        )
    airspace_audit = results.get("inspect_airspace_constraints")
    if isinstance(airspace_audit, dict) and airspace_audit.get("status") == "ok":
        snap = airspace_audit.get("constraint_snapshot") or {}
        check = airspace_audit.get("airspace_check") or {}
        rows: list[list[str | float | None]] = [
            ["快照 ID", snap.get("snapshot_id") or "无（历史建筑避障记录）"],
            ["快照摘要", (snap.get("digest") or "—")[:27]],
            ["纳入避让区域", f"{snap.get('enforced_zone_count', 0)} / {snap.get('total_zone_count', 0)} 个"],
            [
                "数据来源",
                "大疆 FlySafe 厂商地理围栏参考"
                if snap.get("source_status") == "manufacturer_reference"
                else (snap.get("source_status") or "—"),
            ],
            ["核查结论", check.get("verdict_label") or check.get("status") or "—"],
        ]
        prev = airspace_audit.get("previous_version")
        if isinstance(prev, dict):
            prev_check = prev.get("rechecked_airspace_check") or {}
            segs = prev_check.get("conflicting_segment_indices") or []
            if segs:
                rows.append(
                    [
                        f"原路线 {prev.get('version_label', 'v1')} 冲突航段",
                        "、".join(f"第 {idx + 1} 段" for idx in segs[:6]),
                    ]
                )
        blocks.append(
            TableBlock(
                title="空域约束与航段核查",
                source=airspace_audit.get("source", "inspect_airspace_constraints"),
                columns=["核查项", "当前记录"],
                rows=rows,
                note="仅针对本次绑定的已知区域快照；未接入官方 UOM/NOTAM，不构成飞行批准。",
            )
        )
    env = results.get("assess_route_environment")
    priority: list[UIBlock] = []
    if isinstance(env, dict) and env.get("factors"):
        priority.append(
            EnvMatrixBlock(
                title="航线环境",
                source="assess_route_environment",
                verdict=env["verdict"],
                verdict_reason=env.get("verdict_reason") or "",
                factors=[
                    EnvFactor(
                        id=factor["id"],
                        name=factor["name"],
                        status=factor["status"],
                        value=factor.get("value")
                        if isinstance(factor.get("value"), (int, float, str)) or factor.get("value") is None
                        else str(factor.get("value")),
                        unit=factor.get("unit") or "",
                        threshold=factor.get("threshold")
                        if isinstance(factor.get("threshold"), (int, float))
                        else None,
                        threshold_source=factor.get("threshold_source"),
                        effect=factor.get("effect") or "info",
                        segment_index=factor.get("segment_index"),
                        reason=factor.get("reason") or "",
                    )
                    for factor in env["factors"][:40]
                ],
                coverage_statement=(env.get("coverage") or {}).get("statement")
                or env.get("verdict_reason")
                or "",
                evidence_id=env["evidence_id"],
                note=(env.get("geometry_note") or "") + "；unknown、not_evaluated、unavailable 不是通过。",
            )
        )
        gap_items = [
            GapItem(factor=gap["factor"], why=gap.get("why") or "", to_close=gap.get("to_close") or "")
            for gap in (env.get("gaps") or [])[:20]
        ]
        if gap_items:
            priority.append(
                GapsBlock(
                    title="未判定项",
                    source="assess_route_environment",
                    items=gap_items,
                    total=len(env.get("gaps") or []),
                    note="缺口不是通过。",
                )
            )
    window = results.get("compare_departure_times")
    if isinstance(window, dict) and len(window.get("options") or []) >= 2:
        priority.append(
            TimeWindowBlock(
                title="起飞时刻对比",
                source="compare_departure_times",
                options=[
                    TimeWindowOption(
                        scheduled_for=option["scheduled_for"],
                        verdict=option["verdict"],
                        reason=option.get("reason") or "",
                    )
                    for option in window["options"][:24]
                ],
                caveat=window.get("caveat") or "",
                note="不推荐最佳起飞时间。",
            )
        )
    ordered = [
        *priority,
        *[block for block in blocks if block.type not in {"env_matrix", "gaps", "time_window"}],
    ]
    version = 2 if any(block.type in {"env_matrix", "gaps", "time_window"} for block in ordered) else 1
    return Presentation(version=version, blocks=ordered[:6])
