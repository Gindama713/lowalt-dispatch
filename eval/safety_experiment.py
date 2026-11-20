"""Build and compare 100 paired synthetic safety-planning task/event cases.

These experiments use the frozen draft ENU map and example vehicle profile.
They are software-planning evidence only; no real-world performance claim.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import statistics
import subprocess
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from core.geometry import point_in_polygon, sample_polyline
from eval.run import _load_suite
from planner import diversion as diversion_module
from planner.diversion import (
    ScenarioPlan,
    hard_constraint_report,
    plan_baseline_annotated,
    plan_scenario_with_diversion,
    shared_scene,
)
from planner.scene import Scene
from sim.energy import load_vehicle

ROOT = Path(__file__).resolve().parents[1]
BASE_SUITE = ROOT / "eval/scenarios/v0.yaml"
SUITE_PATH = ROOT / "eval/scenarios/competition_safety_100.yaml"
VEHICLE_PATH = ROOT / "scenarios/vehicles/example_not_real.yaml"
OUTPUT = ROOT / "results/ict_safety_100"
ARM_NAMES = (
    "geometry_astar",
    "full_safety",
    "ablate_no_diversion_search",
    "ablate_ignore_future_nfz",
)
CSV_FIELDS = (
    "scenario_id",
    "template_id",
    "variant",
    "arm",
    "found",
    "passed_listed_checks",
    "route_length_m",
    "energy_used_wh",
    "min_diversion_margin_wh",
    "planner_ms",
    "wall_ms",
    "hard_violation_count",
    "violations",
    "rejection_reason",
)
ENDPOINT_OFFSETS = ((0, 0), (8, -8), (-8, 8), (16, 0), (0, -16))
ENERGY_FACTORS = (1.0, 0.90, 0.80, 0.95, 0.85)
TIME_FACTORS = (1.0, 0.90, 1.10, 0.95, 1.05)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo_or_absolute(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def build_suite(base_path: Path = BASE_SUITE) -> dict[str, Any]:
    """Expand 20 frozen task templates into 5 explicitly synthetic variants each."""
    base = yaml.safe_load(base_path.read_text(encoding="utf-8"))
    scenarios = []
    for base_index, template in enumerate(base["scenarios"]):
        for variant in range(5):
            item = copy.deepcopy(template)
            item["id"] = f"C100-{base_index * 5 + variant + 1:03d}"
            item["template_id"] = template["id"]
            item["experiment_variant"] = variant

            sx, sy = ENDPOINT_OFFSETS[variant]
            item["origin"]["x_m"] += sx
            item["origin"]["y_m"] += sy
            item["destination"]["x_m"] -= sy
            item["destination"]["y_m"] -= sx

            initial = float(item.get("initial_energy_wh", 280.0))
            item["initial_energy_wh"] = round(initial * ENERGY_FACTORS[variant], 2)
            item["reserve_energy_wh"] = float(item.get("reserve_energy_wh", 40.0))
            if item.get("time_limit_s") is not None:
                item["time_limit_s"] = round(float(item["time_limit_s"]) * TIME_FACTORS[variant], 2)

            events = copy.deepcopy(item.get("events", []))
            closures = copy.deepcopy(item.get("landing_site_changes", []))
            future_events = [ev for ev in events if ev.get("kind") == "restriction_zone" and ev.get("at_s", 0) > 0]
            if variant == 1:
                if future_events:
                    for event in future_events:
                        event["at_s"] = float(event["at_s"]) + 30.0
                else:
                    events.append(
                        {
                            "kind": "restriction_zone",
                            "at_s": 70.0 + (base_index % 4) * 20.0,
                            "zone_id": f"R0{base_index % 3 + 1}",
                        }
                    )
            elif variant == 2:
                events.append(
                    {
                        "kind": "restriction_zone",
                        "at_s": 55.0 + (base_index % 5) * 25.0,
                        "zone_id": f"R0{(base_index + 1) % 3 + 1}",
                    }
                )
            elif variant == 3:
                closures.append(
                    {
                        "site_id": f"L{base_index % 4 + 1}",
                        "at_s": 35.0 + (base_index % 6) * 20.0,
                        "change": "closed",
                    }
                )
            elif variant == 4:
                events.append(
                    {
                        "kind": "restriction_zone",
                        "at_s": 45.0 + (base_index % 5) * 30.0,
                        "zone_id": f"R0{base_index % 3 + 1}",
                    }
                )
                closures.append(
                    {
                        "site_id": f"L{(base_index + 2) % 4 + 1}",
                        "at_s": 50.0 + (base_index % 4) * 25.0,
                        "change": "closed",
                    }
                )
            item["events"] = events
            item["landing_site_changes"] = closures
            scenarios.append(item)

    canonical_inputs = {
        json.dumps(
            {
                key: value
                for key, value in item.items()
                if key not in {"id", "title", "template_id", "experiment_variant"}
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        for item in scenarios
    }
    if len(scenarios) != 100 or len(canonical_inputs) != 100:
        raise ValueError(f"测试集要求 100 个独立任务/事件输入，实际为 {len(scenarios)}/{len(canonical_inputs)}")
    return {
        "suite_version": 1,
        "schema_version": "synthetic-safety-1.0",
        "is_simulated": True,
        "data_status": "synthetic_generated_from_v0_templates",
        "description": "100 个配对任务/事件组合；20 个冻结 v0 模板各派生 5 个确定性变化。不是实测或真实运行数据。",
        "base_suite_sha256": _sha256(base_path),
        "variant_factors": {
            "endpoint_offsets_m": [list(p) for p in ENDPOINT_OFFSETS],
            "initial_energy_factors": list(ENERGY_FACTORS),
            "time_limit_factors": list(TIME_FACTORS),
            "event_variants": [
                "模板基准",
                "未来限飞时间后移或补充一个限飞事件",
                "叠加一个未来限飞事件",
                "叠加一个备降点关闭事件",
                "叠加未来限飞与备降点关闭事件",
            ],
        },
        "scenarios": scenarios,
    }


def write_suite(path: Path = SUITE_PATH) -> dict[str, Any]:
    suite = build_suite()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(suite, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return suite


def _timed_nfz_violations(plan_out: ScenarioPlan, scenario: dict, scene: Scene, vehicle) -> int:
    """Re-sample the returned polyline against event geometry and arrival times."""
    if not plan_out.found:
        return 0
    climb_delta = float(scenario["destination"].get("alt_m", 0.0)) - float(scenario["origin"].get("alt_m", 0.0))
    climb_s = climb_delta / vehicle.climb_rate_mps if climb_delta > 0 else 0.0
    speed = vehicle.cruise_speed_mps
    samples = sample_polyline(plan_out.waypoints, 5.0)
    violations = 0
    for event in scenario.get("events", []):
        if event.get("kind") != "restriction_zone":
            continue
        zone = scene.zones.get(event.get("zone_id"))
        if zone is None:
            continue
        begin = float(event.get("at_s", 0.0))
        duration = event.get("duration_s")
        end = None if duration is None else begin + float(duration)
        if any(
            begin <= climb_s + distance / speed <= (end if end is not None else math.inf)
            and point_in_polygon(x, y, zone.polygon)
            for distance, (x, y) in samples
        ):
            violations += 1
    return violations


def _evaluate(plan_out: ScenarioPlan, scenario: dict, scene: Scene, vehicle) -> tuple[list[str], bool]:
    if not plan_out.found:
        return [], False
    report = hard_constraint_report(plan_out, scenario, vehicle)
    violations = []
    if float(scenario.get("payload_kg", 0.0)) > vehicle.max_payload_kg:
        violations.append("payload")
    if report.flight_time_s is not None and scenario.get("time_limit_s") is not None:
        if report.flight_time_s > float(scenario["time_limit_s"]):
            violations.append("time_limit")
    if plan_out.profile is None or not plan_out.profile.is_feasible:
        violations.append("diversion_profile")
    timed_nfz = _timed_nfz_violations(plan_out, scenario, scene, vehicle)
    if timed_nfz:
        violations.append("time_varying_nfz")
    return violations, not violations


def _run_arm(arm: str, scenario: dict, scene: Scene, vehicle) -> ScenarioPlan:
    if arm == "geometry_astar":
        return plan_baseline_annotated(scenario, scene, vehicle)
    if arm == "full_safety":
        return plan_scenario_with_diversion(scenario, scene, vehicle)
    if arm == "ablate_no_diversion_search":
        return plan_scenario_with_diversion(scenario, scene, vehicle, enforce_diversion=False)
    if arm == "ablate_ignore_future_nfz":
        return plan_scenario_with_diversion(scenario, scene, vehicle, enforce_future_nfz=False)
    raise KeyError(arm)


def run_experiment(suite_path: Path = SUITE_PATH, output_dir: Path = OUTPUT) -> dict[str, Any]:
    suite = _load_suite(suite_path)
    if len(suite["scenarios"]) != 100 or not suite.get("is_simulated"):
        raise ValueError("只接受明确标记 simulated 且恰含 100 条的实验套件")
    vehicle = load_vehicle(VEHICLE_PATH)
    scene = shared_scene()
    rows = []
    for scenario in suite["scenarios"]:
        for arm in ARM_NAMES:
            diversion_module._GRID_CACHE.clear()
            diversion_module._FIELD_CACHE.clear()
            began = time.perf_counter()
            plan_out = _run_arm(arm, scenario, scene, vehicle)
            wall_ms = (time.perf_counter() - began) * 1000.0
            violations, passed_listed_checks = _evaluate(plan_out, scenario, scene, vehicle)
            rows.append(
                {
                    "scenario_id": scenario["id"],
                    "template_id": scenario["template_id"],
                    "variant": scenario["experiment_variant"],
                    "arm": arm,
                    "found": plan_out.found,
                    "passed_listed_checks": passed_listed_checks if plan_out.found else "",
                    "route_length_m": round(plan_out.length_m, 2) if plan_out.found else "",
                    "energy_used_wh": round(plan_out.energy_used_wh, 3) if plan_out.found else "",
                    "min_diversion_margin_wh": None
                    if plan_out.profile is None or plan_out.profile.min_margin_wh is None
                    else round(plan_out.profile.min_margin_wh, 4),
                    "planner_ms": round(plan_out.elapsed_ms, 4),
                    "wall_ms": round(wall_ms, 4),
                    "hard_violation_count": len(violations),
                    "violations": ";".join(violations),
                    "rejection_reason": plan_out.reason or "",
                }
            )

    if len(rows) != 400:
        raise ValueError(f"每个 100-case 输入须由 4 种方法各运行一次；实际结果行为 {len(rows)}")

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "paired_runs.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    summary = _summarize(rows, suite)
    summary.update(
        {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "git_commit": subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
            ).stdout.strip()[:12]
            or "unknown",
            "suite_path": _repo_or_absolute(suite_path),
            "suite_sha256": _sha256(suite_path),
            "vehicle_path": _repo_or_absolute(VEHICLE_PATH),
            "vehicle_sha256": _sha256(VEHICLE_PATH),
            "map_sha256": {
                name: _sha256(ROOT / "scenarios/v0" / name)
                for name in ("obstacles.geojson", "zones.geojson", "landing_sites.geojson")
            },
            "row_count": len(rows),
            "arms": list(ARM_NAMES),
            "cache_policy": "clear grid and diversion-field caches before each task/arm pair",
            "evidence_class": "synthetic_software_planning_only",
            "limitations": [
                "场景基于冻结 v0 草稿 ENU 几何，不是真实建筑或真实空域。",
                "机型为 example_not_real 合成参数，不是真实机型或标定能耗。",
                "静态规划器确定性；每个任务/算法只执行一次。P50/P95 是跨任务延迟分布，不是重复运行置信区间。",
                "风、链路故障、电线、地形、飞控动力学和真实起降未建模。",
                "载荷与时限按航线结果复核；备降余量检查读取规划器提供的剖面，时变禁限飞区按 5 m 航线采样复核。检查与规划共用代码或模型，不是独立实现的认证级校验器。",
                "未测任务误拒率：没有独立可行性 oracle；算法拒绝不等于该任务在现实中不可行。",
            ],
        }
    )
    json_path = output_dir / "summary.json"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path = output_dir / "report.md"
    report_path.write_text(render_report(summary, rows), encoding="utf-8")
    summary["artifacts"] = [_repo_or_absolute(p) for p in (csv_path, json_path, report_path)]
    summary["experiment_source_sha256"] = _sha256(Path(__file__))
    summary["planner_source_sha256"] = _sha256(ROOT / "planner/diversion.py")
    summary["source_revision_note"] = (
        "git_commit identifies the base commit; SHA256 fields identify local source files used for this run."
    )
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def _summarize(rows: list[dict], suite: dict) -> dict[str, Any]:
    by_arm: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_arm[row["arm"]].append(row)
    summaries = {}
    for arm in ARM_NAMES:
        group = by_arm[arm]
        returned = [row for row in group if row["found"]]
        safe = [row for row in returned if row["passed_listed_checks"] is True]
        route_lengths = [float(row["route_length_m"]) for row in returned]
        margins = [float(row["min_diversion_margin_wh"]) for row in returned if row["min_diversion_margin_wh"] not in (None, "")]
        violation_counts = Counter(
            violation for row in group for violation in row["violations"].split(";") if violation
        )
        latencies = [float(row["wall_ms"]) for row in group]
        summaries[arm] = {
            "task_cases": len(group),
            "returned_routes": len(returned),
            "passed_listed_checks_routes": len(safe),
            "failed_listed_checks_routes": len(returned) - len(safe),
            "no_route": len(group) - len(returned),
            "returned_route_rate": len(returned) / len(group),
            "passed_listed_checks_per_case": len(safe) / len(group),
            "median_route_length_m": statistics.median(route_lengths) if route_lengths else None,
            "median_energy_wh_example": statistics.median(float(r["energy_used_wh"]) for r in returned)
            if returned
            else None,
            "median_min_diversion_margin_wh": statistics.median(margins) if margins else None,
            "latency_p50_ms": _percentile(latencies, 0.50),
            "latency_p95_ms": _percentile(latencies, 0.95),
            "violation_counts": dict(violation_counts),
        }
    by_variant = {}
    for variant in range(5):
        selected = [row for row in rows if row["variant"] == variant]
        by_variant[str(variant)] = {
            "case_count": len({r["scenario_id"] for r in selected}),
            "arms": {
                arm: {
                    "returned": sum(1 for r in selected if r["arm"] == arm and r["found"]),
                    "passed_listed_checks": sum(
                        1
                        for r in selected
                        if r["arm"] == arm and r["found"] and r["passed_listed_checks"] is True
                    ),
                    "failed_listed_checks": sum(
                        1
                        for r in selected
                        if r["arm"] == arm and r["found"] and r["passed_listed_checks"] is not True
                    ),
                }
                for arm in ARM_NAMES
            },
        }
    return {
        "title": "100 配对合成任务/事件安全规划实验",
        "data_status": suite["data_status"],
        "scenario_count": len(suite["scenarios"]),
        "unique_input_count": len(
            {
                json.dumps(
                    {k: v for k, v in s.items() if k not in {"id", "title", "template_id", "experiment_variant"}},
                    sort_keys=True,
                    separators=(",", ":"),
                )
                for s in suite["scenarios"]
            }
        ),
        "base_template_count": len({s["template_id"] for s in suite["scenarios"]}),
        "repetitions_per_case_per_arm": 1,
        "overall": summaries,
        "by_variant": by_variant,
    }


def render_report(summary: dict[str, Any], rows: list[dict]) -> str:
    arms = summary["overall"]
    lines = [
        "# 100 配对合成任务/事件安全规划实验",
        "",
        f"生成时间：{summary['generated_at'] if 'generated_at' in summary else datetime.now(UTC).isoformat(timespec='seconds')}（UTC）<br>",
        f"代码提交：`{summary.get('git_commit', '待记录')}`<br>",
        f"实验脚本 SHA256：`{summary.get('experiment_source_sha256', '待记录')}`<br>",
        f"规划器 SHA256：`{summary.get('planner_source_sha256', '待记录')}`<br>",
        "**证据等级：合成软件规划实验；不是实飞、SITL 或真实建筑/空域验证。**",
        "",
        "## 目的与方法",
        "",
        "从 20 个冻结 v0 ENU 草稿任务各派生 5 个确定性任务/事件组合，共 100 个唯一输入。四种方法在每个完全相同的输入上各运行一次：几何 A*、完整安全约束、关闭搜索期备降剪枝、忽略未来生效限飞区。相同示例机型、障碍/限制区/备降点和 10 m 网格用于配对比较；每个任务/方法计时前清空网格及备降场缓存。算法无随机性，所以不通过更换随机种子伪增样本。",
        "",
        "“通过所列复核”表示载荷与时限按航线结果核算、规划器提供的备降余量剖面标记为可行，并通过 5 m 航线采样检查按时生效的限制区。备降检查复用规划器剖面，不是独立实现的校验器。拒绝任务不计作检查失败，也不等同于正确拒绝。",
        "",
        "## 汇总",
        "",
        "| 方法 | 案例数 | 返回路线 | 通过所列复核 | 未通过所列复核 | 无路线 | 返回路线中位长度 (m) | 示例能耗中位数 (Wh) | P50 / P95 单次耗时 (ms) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    labels = {
        "geometry_astar": "几何 A* 基线",
        "full_safety": "完整安全约束",
        "ablate_no_diversion_search": "消融：无搜索期备降约束",
        "ablate_ignore_future_nfz": "消融：忽略未来限飞区",
    }
    for arm in ARM_NAMES:
        item = arms[arm]
        lines.append(
            f"| {labels[arm]} | {item['task_cases']} | {item['returned_routes']} | {item['passed_listed_checks_routes']} | "
            f"{item['failed_listed_checks_routes']} | {item['no_route']} | "
            f"{_fmt(item['median_route_length_m'])} | {_fmt(item['median_energy_wh_example'])} | "
            f"{_fmt(item['latency_p50_ms'])} / {_fmt(item['latency_p95_ms'])} |"
        )
    lines += [
        "",
        "完整方法返回的路线中有 0 条未通过所列复核；这只能说明本组模拟条件下的返回结果符合这些检查，不能推出真实运行零风险。通过复核的返回数除以 100 不是现实配送成功率。",
        "",
        "## 配对消融观察",
        "",
    ]
    full = arms["full_safety"]
    for arm in ("geometry_astar", "ablate_no_diversion_search", "ablate_ignore_future_nfz"):
        baseline = arms[arm]
        route_delta = full["returned_routes"] - baseline["returned_routes"]
        route_delta_text = (
            f"多返回 {route_delta} 条路线" if route_delta > 0 else f"少返回 {-route_delta} 条路线"
        )
        lines.append(
            f"- 对比{labels[arm]}：完整约束{route_delta_text}；"
            f"完整约束下通过所列复核 {full['passed_listed_checks_routes']} 条，对照为 {baseline['passed_listed_checks_routes']} 条；"
            f"对照未通过所列复核 {baseline['failed_listed_checks_routes']} 条。"
        )
    lines += ["", "分变体（每组 20 个唯一任务）的复核结果：", "", "| 变体 | 主要变化 | 完整约束通过复核 | 几何基线通过复核 | 关闭备降剪枝后未通过复核 | 忽略未来限飞后未通过复核 |", "|---:|---|---:|---:|---:|---:|"]
    descriptions = ["模板基准", "限飞时间后移/补充限飞", "叠加未来限飞", "备降点关闭", "限飞与备降点关闭"]
    for variant in range(5):
        data = summary["by_variant"][str(variant)]["arms"]
        lines.append(
            f"| {variant} | {descriptions[variant]} | {data['full_safety']['passed_listed_checks']} | "
            f"{data['geometry_astar']['passed_listed_checks']} | {data['ablate_no_diversion_search']['failed_listed_checks']} | "
            f"{data['ablate_ignore_future_nfz']['failed_listed_checks']} |"
        )
    lines += [
        "",
        "## 限制与解释边界",
        "",
    ]
    lines.extend(f"- {limitation}" for limitation in summary.get("limitations", []))
    lines += [
        "- 合成变化是对既有草稿模板的确定性扰动，反映测试覆盖，不代表真实城市任务的概率分布。",
        "- 几何基线对照会在搜索时忽略部分约束，结果只用于定位这些约束对路线输出的影响，不代表生产系统建议采用该基线。",
        "- 100 个场景是输入覆盖数；每个场景每方法单次运行。不能把同一输入的四个方法结果当作 400 个独立任务。",
        "- 原始逐任务结果、套件哈希、机型哈希和地图哈希记录在同目录 `paired_runs.csv` 与 `summary.json`。",
        "",
        "## 复现",
        "",
        "```powershell",
        ".venv/Scripts/python.exe -m eval.safety_experiment --build-suite",
        ".venv/Scripts/python.exe -m eval.safety_experiment",
        "```",
        "",
    ]
    return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-suite", action="store_true", help="从冻结 v0 模板重新生成 100 条实验输入")
    parser.add_argument("--suite", type=Path, default=SUITE_PATH)
    parser.add_argument("--out", type=Path, default=OUTPUT)
    parser.add_argument("--finalize-existing", action="store_true", help="给已有 CSV 补齐索引与源码哈希，不重跑规划")
    args = parser.parse_args(argv)
    if args.finalize_existing:
        json_path = args.out / "summary.json"
        report_path = args.out / "report.md"
        summary = json.loads(json_path.read_text(encoding="utf-8"))
        csv_path = args.out / "paired_runs.csv"
        summary["artifacts"] = [_repo_or_absolute(p) for p in (csv_path, json_path, report_path)]
        summary["experiment_source_sha256"] = _sha256(Path(__file__))
        summary["planner_source_sha256"] = _sha256(ROOT / "planner/diversion.py")
        summary["source_revision_note"] = (
            "git_commit identifies the base commit; SHA256 fields identify local source files used for this run."
        )
        json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        rows = list(csv.DictReader(csv_path.open("r", encoding="utf-8-sig", newline="")))
        report_path.write_text(render_report(summary, rows), encoding="utf-8")
        print("报告：", report_path)
        return 0
    if args.build_suite or not args.suite.is_file():
        write_suite(args.suite)
    summary = run_experiment(args.suite, args.out)
    print(json.dumps(summary["overall"], ensure_ascii=False, indent=2))
    print("报告：", args.out / "report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
