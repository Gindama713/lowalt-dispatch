"""评测 harness 命令行入口。

用法
----
    # 只跑仍是 mock 的动态基线（输出自动加 _MOCK，数字不能当结果）
    python -m eval.run --suite eval/scenarios/v0.yaml --seeds 1,2,3 \\
        --algorithms astar_dynamic --out results/v0.csv

    # 基线 A* 与带备降约束 A* 的对照。必须显式给出机型文件。
    # 示例文件不是真实平台数据，meta 里会写上这句话。
    python -m eval.run --suite eval/scenarios/v0.yaml --seeds 1,2,3 \\
        --algorithms astar_static,astar_diversion \\
        --vehicle scenarios/vehicles/example_not_real.yaml \\
        --out results/example_vehicle_compare.csv

产物
----
1. CSV：逐条结果。真算法是 run_mode=real；mock 算法写到带 `_MOCK` 的另一份文件。
2. `.meta.json`：套件哈希、种子、算法、git commit、机型文件哈希。
3. 真算法另写 `.profiles.json`：沿航线的备降余量采样，给以后画剖面图。

同一条命令里如果又有真算法又有 mock，两份文件都写。
mock 不会混进 real 文件。真实参数没填时不要拿示例结果去写“任务完成率提升”。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import subprocess
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from core.console import ensure_utf8_stdout
from eval import planners
from planner.diversion import APPROXIMATION_NOTE, ScenarioPlan, profile_record
from planner.scene import SCENARIO_DIR
from sim.energy import load_vehicle

REQUIRED_SCENARIO_KEYS = ("id", "cls", "origin", "destination", "payload_kg")

CSV_COLUMNS = [
    "scenario_id",
    "cls",
    "seed",
    "algorithm",
    "run_mode",
    "task_feasible",
    "task_result",
    "hard_violations",
    "negative_margin_samples",
    "min_landing_margin",
    "route_length_m",
    "energy_used_wh",
    "replan_latency_ms",
    "infeasible_reason",
]

_VEHICLE_MISSING = (
    "真实算法需要 --vehicle 指向机型参数文件。\n"
    "  跑通（示例参数，非真实平台数据）：\n"
    "    --vehicle scenarios/vehicles/example_not_real.yaml\n"
    "  真实平台参数仍在 scenarios/vehicles/placeholder.yaml，目前全是 null，不能拿示例文件顶替它。"
)


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_seeds(raw: str | None, defaults: Iterable[int]) -> list[int]:
    if not raw:
        return list(defaults)
    seeds: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        seeds.append(int(part))
    if not seeds:
        raise ValueError("--seeds 解析后为空")
    return seeds


def _mock_suffixed(path: Path) -> Path:
    if path.stem.endswith("_MOCK"):
        return path
    return path.with_name(f"{path.stem}_MOCK{path.suffix}")


def _load_suite(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"找不到场景集：{path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "scenarios" not in data:
        raise ValueError(f"{path} 缺少顶层 scenarios 列表")

    problems: list[str] = []
    for idx, sc in enumerate(data["scenarios"]):
        missing = [k for k in REQUIRED_SCENARIO_KEYS if k not in sc]
        if missing:
            problems.append(f"  第 {idx} 条场景缺字段 {missing}")
        for key in ("origin", "destination"):
            if key in sc and not {"x_m", "y_m"} <= set(sc[key]):
                problems.append(f"  场景 {sc.get('id', idx)} 的 {key} 需要 x_m/y_m")
    if problems:
        raise ValueError("场景集校验失败：\n" + "\n".join(problems))
    return data


def _write_table(
    rows: list[dict[str, Any]],
    out_path: Path,
    meta: dict[str, Any],
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore", restval="")
        writer.writeheader()
        writer.writerows(rows)
    meta_path = out_path.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta_path


def _summarize(rows: list[dict[str, Any]], algo_names: list[str]) -> None:
    print(f"  {'algorithm':<18}{'n':>5}{'feasible':>10}{'returned':>10}{'neg_route':>10}{'P50_len_m':>10}")
    for name in algo_names:
        subset = [r for r in rows if r["algorithm"] == name]
        if not subset:
            continue
        feasible = sum(1 for r in subset if r["task_feasible"] is True or r["task_feasible"] == "True")
        returned = []
        neg = 0
        for row in subset:
            length = float(row["route_length_m"] or 0)
            if length > 0:
                returned.append(length)
            samples = row.get("negative_margin_samples") or 0
            try:
                samples_n = int(samples)
            except (TypeError, ValueError):
                samples_n = 0
            if samples_n > 0:
                neg += 1
        returned.sort()
        length_cell = f"{returned[len(returned) // 2]:>10.0f}" if returned else f"{'-':>10}"
        print(f"  {name:<18}{len(subset):>5}{feasible:>10}{len(returned):>10}{neg:>10}{length_cell}")


def _base_meta(suite_path: Path, suite: dict[str, Any], seeds: list[int], algo_names: list[str], mock: bool) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "run_mode": "mock" if mock else "real",
        "eval_scope": "planning_only_not_flight",
        "is_simulated": True,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "suite_path": str(suite_path).replace("\\", "/"),
        "suite_sha256": _sha256_of(suite_path),
        "scenario_count": len(suite["scenarios"]),
        "seeds": seeds,
        "algorithms": algo_names,
        "git_commit": _git_commit(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "seed_effect": "astar_dynamic 的 mock 随种子变化；astar_static 与 astar_diversion 是确定性的，种子不改变航线",
        "task_result_note": "delivered 在这里只表示规划层硬约束通过，不是飞控送达，也不是实飞",
    }
    if mock:
        meta["warning"] = "MOCK：数值由伪随机数生成，无物理含义，禁止用于任何效果声明。"
    else:
        meta["diversion_approximation"] = APPROXIMATION_NOTE
        for geo in ("obstacles.geojson", "zones.geojson", "landing_sites.geojson"):
            meta[f"sha256_{geo}"] = _sha256_of(SCENARIO_DIR / geo)
    return meta


def _run_planners(
    suite: dict[str, Any],
    seeds: list[int],
    picked: list,
    *,
    mock: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    profiles: list[dict[str, Any]] = []
    seen_profile: set[tuple[str, str]] = set()
    for sc in suite["scenarios"]:
        for seed in seeds:
            for planner in picked:
                result = planner.plan(sc, seed)
                row: dict[str, Any] = {
                    "scenario_id": sc["id"],
                    "cls": sc["cls"],
                    "seed": seed,
                    "algorithm": planner.name,
                    "run_mode": "mock" if planner.is_mock else "real",
                }
                row.update(result.as_row())
                rows.append(row)
                if mock:
                    continue
                key = (sc["id"], planner.name)
                if key in seen_profile:
                    continue
                seen_profile.add(key)
                if result.profile is None and result.route_length_m <= 0:
                    profiles.append(
                        {
                            "scenario_id": sc["id"],
                            "algorithm": planner.name,
                            "found": False,
                            "reason": result.infeasible_reason,
                            "length_m": 0.0,
                            "samples": [],
                            "is_feasible": False,
                        }
                    )
                elif result.profile is not None:
                    holder = ScenarioPlan(
                        algorithm=planner.name,
                        found=result.route_length_m > 0,
                        length_m=result.route_length_m,
                        energy_used_wh=result.energy_used_wh,
                        reason=result.infeasible_reason or None,
                        profile=result.profile,
                        reserve_wh=result.profile.reserve_wh,
                    )
                    profiles.append(profile_record(sc["id"], holder))
    return rows, profiles


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_stdout()
    parser = argparse.ArgumentParser(
        prog="python -m eval.run",
        description="低空项目评测 harness（真算法与 mock 分开落盘）",
    )
    parser.add_argument("--suite", required=True, type=Path, help="场景集 yaml 路径")
    parser.add_argument("--seeds", default=None, help="逗号分隔的种子，默认取套件里的 default_seeds")
    parser.add_argument("--out", default=Path("results/v0.csv"), type=Path, help="CSV 输出路径")
    parser.add_argument(
        "--algorithms",
        default=",".join(planners.ALGORITHMS),
        help="逗号分隔的算法名",
    )
    parser.add_argument(
        "--vehicle",
        default=None,
        type=Path,
        help="机型 yaml。真实算法必填。示例：scenarios/vehicles/example_not_real.yaml",
    )
    args = parser.parse_args(argv)

    suite = _load_suite(args.suite)
    seeds = _parse_seeds(args.seeds, suite.get("default_seeds", [1]))
    algo_names = [a.strip() for a in args.algorithms.split(",") if a.strip()]
    if any(planners.is_mock_name(name) is False and name not in planners.ALGORITHMS for name in algo_names):
        raise KeyError(f"未知算法，可选：{', '.join(planners.ALGORITHMS)}")
    for name in algo_names:
        if name not in planners.ALGORITHMS:
            raise KeyError(f"未知算法 {name!r}，可选：{', '.join(planners.ALGORITHMS)}")

    real_names = [name for name in algo_names if not planners.is_mock_name(name)]
    mock_names = [name for name in algo_names if planners.is_mock_name(name)]
    if real_names and args.vehicle is None:
        print(_VEHICLE_MISSING, file=sys.stderr)
        return 2

    vehicle_profile = None
    if args.vehicle is not None and real_names:
        vehicle_profile = load_vehicle(args.vehicle)

    real_planners = [planners.get(name, vehicle_path=args.vehicle, vehicle=vehicle_profile) for name in real_names]
    mock_planners = [planners.get(name) for name in mock_names]

    wrote = False
    if real_planners:
        rows, profiles = _run_planners(suite, seeds, real_planners, mock=False)
        meta = _base_meta(args.suite, suite, seeds, real_names, mock=False)
        meta["row_count"] = len(rows)
        meta["vehicle_path"] = str(args.vehicle).replace("\\", "/")
        meta["vehicle_sha256"] = _sha256_of(args.vehicle)
        meta["vehicle_key"] = vehicle_profile.vehicle_key
        meta["vehicle_is_example"] = bool(vehicle_profile.is_example)
        meta["vehicle_source"] = vehicle_profile.source
        meta["vehicle_uncertainty_note"] = vehicle_profile.uncertainty_note
        meta["draft_geometry_vehicle_alias"] = vehicle_profile.draft_geometry_vehicle_alias
        if vehicle_profile.is_example:
            meta["warning"] = (
                "示例机型参数，非真实平台数据。能耗、备降余量和可行/不可行只对这组手写数字成立，"
                "不能写成实测能耗、适航结论或任务完成率提升。"
            )
        elif not vehicle_profile.is_example:
            meta["vehicle_claim"] = "机型文件未声明 is_example=true。调用者自行对参数来源负责。"
        meta_path = _write_table(rows, args.out, meta)
        profile_path = args.out.with_suffix(".profiles.json")
        profile_doc = {
            "warning": meta.get("warning"),
            "vehicle_is_example": bool(vehicle_profile.is_example),
            "vehicle_key": vehicle_profile.vehicle_key,
            "sample_step_m": 50,
            "approximation": APPROXIMATION_NOTE,
            "seeds_note": "确定性算法只存每个场景的第一份剖面；种子不改变航线",
            "unreachable_margin_wh": -1.0e6,
            "profiles": profiles,
        }
        profile_path.write_text(json.dumps(profile_doc, ensure_ascii=False, indent=2), encoding="utf-8")
        print("=" * 64)
        if vehicle_profile.is_example:
            print("  示例参数，非真实平台数据 —— 这些数字只对 example_not_real 成立")
        print("  规划评测（不是飞行）。delivered = 规划层硬约束通过")
        print("=" * 64)
        print(f"场景 {meta['scenario_count']} × 种子 {len(seeds)} × 算法 {len(real_names)} = {len(rows)} 行")
        print(f"CSV      → {args.out}")
        print(f"meta     → {meta_path}")
        print(f"profiles → {profile_path}")
        print("\n按算法汇总（feasible=硬约束通过，returned=给出了航线，neg_route=剖面里有负余量）：")
        _summarize(rows, real_names)
        wrote = True

    if mock_planners:
        rows, _profiles = _run_planners(suite, seeds, mock_planners, mock=True)
        out_path = _mock_suffixed(args.out)
        meta = _base_meta(args.suite, suite, seeds, mock_names, mock=True)
        meta["row_count"] = len(rows)
        meta_path = _write_table(rows, out_path, meta)
        print("=" * 64)
        print("  MOCK 运行 —— 这些数字不是结果，只证明管道能跑通")
        print("=" * 64)
        print(f"场景 {meta['scenario_count']} × 种子 {len(seeds)} × 算法 {len(mock_names)} = {len(rows)} 行")
        print(f"CSV  → {out_path}")
        print(f"meta → {meta_path}")
        print("\n按算法汇总：")
        _summarize(rows, mock_names)
        wrote = True

    return 0 if wrote else 2


if __name__ == "__main__":
    sys.exit(main())
