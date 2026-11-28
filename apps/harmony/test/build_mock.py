"""生成 rawfile/mock。payload 用仓库里的模型导出，外层 example 标明这是示例。

在仓库根目录运行：python apps/harmony/test/build_mock.py
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from core.models import DataProvenance, Position, RiskSnapshot, Task
from services.api.envelopes import SceneBindRequest
from services.api.scene_loader import bind_scene, load_scene_document

OUT = ROOT / "apps" / "harmony" / "entry" / "src" / "main" / "resources" / "rawfile" / "mock"
TIME_KEYS = {
    "captured_at",
    "valid_from",
    "valid_until",
    "effective_from",
    "effective_until",
    "available_from",
    "available_until",
}
FROZEN = "2026-11-09T00:00:00Z"


def freeze(value: object) -> object:
    if isinstance(value, dict):
        out: dict[str, object] = {}
        for key, item in value.items():
            if key in TIME_KEYS and isinstance(item, str) and item.startswith("2026-"):
                out[key] = FROZEN
            else:
                out[key] = freeze(item)
        return out
    if isinstance(value, list):
        return [freeze(item) for item in value]
    return value


def wrap(payload: object, note: str) -> dict[str, object]:
    return {
        "example": True,
        "example_note": "示例。" + note,
        "payload": payload,
    }


def dump(name: str, payload: object, note: str) -> None:
    path = OUT / name
    path.write_text(
        json.dumps(wrap(payload, note), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(path.relative_to(ROOT))


def position(x: float, y: float, alt: float) -> dict[str, object]:
    return Position(
        frame="enu_m",
        x_m=x,
        y_m=y,
        alt_m=alt,
        alt_ref="rel_takeoff",
    ).model_dump(mode="json")


def task(task_id: str, origin: tuple[float, float, float], dest: tuple[float, float, float]) -> dict[str, object]:
    body = Task(
        task_id=task_id,
        origin=Position(frame="enu_m", x_m=origin[0], y_m=origin[1], alt_m=origin[2], alt_ref="rel_takeoff"),
        destination=Position(frame="enu_m", x_m=dest[0], y_m=dest[1], alt_m=dest[2], alt_ref="rel_takeoff"),
        payload_kg=1,
        vehicle_type="placeholder",
        initial_energy_wh=100,
        reserve_energy_wh=20,
        time_limit_s=None,
        provenance=DataProvenance(
            source="harmony-mock",
            version="0",
            captured_at=datetime(2026, 11, 9, tzinfo=timezone.utc),
            is_simulated=True,
            uncertainty_note="示例。不是实测任务，坐标来自文档中的示例，不是真实地点。",
        ),
    ).model_dump(mode="json")
    return freeze(body)  # type: ignore[return-value]


def route_record(found: bool) -> dict[str, object]:
    origin = (150.0, 150.0)
    dest = (2650.0, 2750.0)
    mid = ((origin[0] + dest[0]) / 2 + 120.0, (origin[1] + dest[1]) / 2 - 80.0)
    if found:
        waypoints = [
            position(origin[0], origin[1], 0),
            position(mid[0], mid[1], 0),
            position(dest[0], dest[1], 30),
        ]
        length = math.dist(origin, mid) + math.dist(mid, dest)
        reason = None
        altitude = "示例：中间点的 alt_m 与 alt_ref 复制起点，只为凑齐 Position。不是高度剖面，也不是规划器输出。"
        algorithm = "example_polyline"
    else:
        waypoints = []
        length = None
        reason = "终点周围没有可用单元（目的地可能在限制区内）"
        altitude = "示例：没有航点。"
        algorithm = "example_blocked"
    return {
        "task_id": "T-20261109-001",
        "route_id": "v1",
        "plan_version": "v1",
        "snapshot_id": "T-20261109-001-snap-1",
        "algorithm": algorithm,
        "planner_entry": "mock:example_polyline",
        "found": found,
        "reason": reason,
        "length_m": length,
        "elapsed_ms": None,
        "nodes_expanded": None,
        "timing_note": "示例：Mock 没有运行搜索。elapsed_ms 保持 null。真实接口里该字段只表示规划函数内部耗时，不是端到端时延。",
        "waypoints": waypoints,
        "altitude_note": altitude,
        "route": None,
        "route_plan_status": "unavailable",
        "route_plan_detail": "示例：没有 energy_budget_wh，不能构成 RoutePlan。不用任务单上的 initial_energy_wh 填这个字段。",
        "margin_status": "unavailable",
        "margin_detail": "示例：没有备降余量剖面。status=unavailable，剖面和派生数字都是 null，不用 0 代替。",
        "margin_profile": None,
        "limitations": [
            "示例：MockDataSource 不运行 planner.astar，也不读取障碍物做搜索。",
            "示例：只在终点落入已生效限制区多边形时返回 found=false；绕障航线请看真实接口。",
        ],
        "is_simulated": True,
        "simulation_note": "示例。航点是示意折线，坐标系与 scenarios/v0 草稿相同（仿真，不是实测）。Mock 不调用 planner.astar。",
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    health = {
        "status": "ok",
        "schema_version": "0.1.0",
        "service": "lowalt-dispatch-api",
        "git_commit": "example",
        "storage_backend": "memory",
        "storage_note": "示例。字段对齐 GET /health。这里不是正在运行的进程。",
        "planner_entry": "planner.astar:plan_scenario",
        "postgres": {
            "name": "postgresql",
            "configured": False,
            "connected": False,
            "note": "示例。未配置。RDS_DSN 和 DATABASE_URL 都是空的，当前不会连接 PostgreSQL。",
        },
        "redis": {
            "name": "redis",
            "configured": False,
            "connected": False,
            "note": "示例。未配置。DCS_HOST 和 REDIS_URL 都是空的，当前不会连接 Redis。",
        },
        "agent": {
            "status": "not_implemented",
            "entry_configured": False,
            "detail": "示例。M3 未接入。手机端不下发飞控指令。",
        },
    }
    dump("health.json", health, "GET /health 的字段形状，数值是构造的。")

    tasks = [
        task("T-20261109-001", (150, 150, 0), (2650, 2750, 30)),
        task("T-stale-demo", (500, 500, 0), (2500, 2500, 30)),
    ]
    dump("tasks.json", tasks, "GET /tasks 的示例列表，两条都是构造任务。")

    scene = freeze(load_scene_document("v0").model_dump(mode="json"))
    dump("scene_v0.json", scene, "GET /scenes/v0。几何来自 scenarios/v0 草稿，时间被冻成固定值。")

    bound = bind_scene(
        "T-20261109-001",
        SceneBindRequest(scene_id="v0", active_zone_ids=["R01"], occupied_site_ids=["L2"]),
        snapshot_id="T-20261109-001-snap-1",
    )
    fresh = freeze(bound.snapshot.model_dump(mode="json"))
    stale = freeze(
        RiskSnapshot(
            snapshot_id="snap-old",
            captured_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            valid_until=datetime(2020, 1, 2, tzinfo=timezone.utc),
            landing_sites=[],
            events=[],
            note="示例。valid_until 在 2020，用来演示重新规划时的 409。",
        ).model_dump(mode="json")
    )
    dump(
        "snapshots.json",
        [
            {"task_id": "T-20261109-001", "snapshot": fresh},
            {"task_id": "T-stale-demo", "snapshot": stale},
        ],
        "种子快照。第一条来自 bind_scene(v0, R01, L2)，第二条是已过期快照。",
    )

    found = route_record(True)
    missing = route_record(False)
    dump(
        "routes.json",
        [{"task_id": "T-20261109-001", "routes": [found]}],
        "GET /tasks/{id}/routes 的示例。折线不是 A* 输出。",
    )
    agent = {
        "status": "not_implemented",
        "detail": "示例：手机端不调用 M3，也不下发飞控指令。applied 保持 false。",
        "entry": None,
        "applied": False,
    }
    dump("plan_found.json", {"route": found, "agent": agent}, "POST /plan 找到示意折线时的信封。")
    dump("plan_not_found.json", {"route": missing, "agent": agent}, "POST /plan found=false 时的信封，length_m 为 null。")
    dump(
        "margin_v1.json",
        {
            "task_id": "T-20261109-001",
            "route_id": "v1",
            "status": "unavailable",
            "detail": found["margin_detail"],
            "profile": None,
            "min_margin_wh": None,
            "negative_sample_count": None,
            "is_feasible": None,
        },
        "GET /margin。unavailable 时三个派生值必须是 null。",
    )


if __name__ == "__main__":
    main()
