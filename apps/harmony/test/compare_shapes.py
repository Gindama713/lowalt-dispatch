"""对照正在运行的 FastAPI，检查 mock payload 的字段形状。

在仓库根目录、服务已监听后运行：

    python apps/harmony/test/compare_shapes.py
    python apps/harmony/test/compare_shapes.py http://127.0.0.1:8000
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

MOCK = Path(__file__).resolve().parents[1] / "entry" / "src" / "main" / "resources" / "rawfile" / "mock"


def load(name: str) -> object:
    body = json.loads((MOCK / name).read_text(encoding="utf-8"))
    if body.get("example") is not True or "示例" not in str(body.get("example_note", "")):
        raise SystemExit(f"{name} 没有标成示例")
    return body["payload"]


def request(base: str, method: str, path: str, payload: object | None = None) -> tuple[int, object]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def same_keys(left: object, right: object, path: str) -> None:
    if isinstance(left, dict) and isinstance(right, dict):
        if set(left) != set(right):
            missing = sorted(set(left) - set(right))
            extra = sorted(set(right) - set(left))
            raise SystemExit(f"{path} 字段不一致 missing={missing} extra={extra}")
        for key, value in left.items():
            if key == "coordinates":
                continue
            same_keys(value, right[key], f"{path}.{key}")
        return
    if isinstance(left, list) and isinstance(right, list):
        if left and right and isinstance(left[0], dict) and isinstance(right[0], dict):
            same_keys(left[0], right[0], path + "[]")


def main() -> None:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    health_mock = load("health.json")
    status, health = request(base, "GET", "/health")
    if status != 200:
        raise SystemExit(f"/health {status}")
    same_keys(health_mock, health, "health")
    if health["status"] not in {"ok", "degraded"}:
        raise SystemExit("health.status 不在枚举内")
    if health["storage_backend"] not in {"memory", "sqlite"}:
        raise SystemExit("storage_backend 不在枚举内")

    tasks = load("tasks.json")
    assert isinstance(tasks, list)
    status, created = request(base, "POST", "/tasks", tasks[0])
    if status != 201:
        raise SystemExit(f"POST /tasks {status} {created}")
    same_keys(tasks[0], created, "task")
    status, again = request(base, "POST", "/tasks", tasks[0])
    if status != 409 or not isinstance(again.get("detail"), str):
        raise SystemExit(f"重复任务应 409 字符串 detail，实际 {status} {again}")

    status, invalid = request(base, "POST", "/tasks", {"task_id": "x", "extra": 1})
    if status != 422 or not isinstance(invalid.get("detail"), list):
        raise SystemExit(f"多余字段应 422 数组 detail，实际 {status}")

    phone_body = {
        "task_id": "T-phone-shape",
        "origin": {"frame": "enu_m", "x_m": 150, "y_m": 150, "alt_m": 0, "alt_ref": "rel_takeoff"},
        "destination": {"frame": "enu_m", "x_m": 2650, "y_m": 2750, "alt_m": 30, "alt_ref": "rel_takeoff"},
        "payload_kg": 1,
        "vehicle_type": "placeholder",
        "initial_energy_wh": 100,
        "reserve_energy_wh": 20,
        "time_limit_s": None,
        "provenance": {
            "source": "harmony:phone",
            "version": "0",
            "captured_at": "2026-11-13T00:00:00Z",
            "is_simulated": True,
            "uncertainty_note": "示例。手机端请求体，不带经纬度。",
        },
    }
    status, phone = request(base, "POST", "/tasks", phone_body)
    if status != 201:
        raise SystemExit(f"手机端任务体被拒绝 {status} {phone}")

    scene_mock = load("scene_v0.json")
    status, scene = request(base, "GET", "/scenes/v0")
    if status != 200:
        raise SystemExit(f"/scenes/v0 {status}")
    same_keys(scene_mock, scene, "scene")
    if scene["counts"] != scene_mock["counts"]:
        raise SystemExit(f"counts 不一致 {scene['counts']}")
    mock_zones = sorted(item["properties"]["id"] for item in scene_mock["restriction_zones"])
    live_zones = sorted(item["properties"]["id"] for item in scene["restriction_zones"])
    if mock_zones != live_zones:
        raise SystemExit(f"限制区 id 不一致 {mock_zones} {live_zones}")

    status, created_stale = request(base, "POST", "/tasks", tasks[1])
    if status != 201:
        raise SystemExit(f"过期示例任务 {status} {created_stale}")
    snapshots = load("snapshots.json")
    stale = next(item["snapshot"] for item in snapshots if item["task_id"] == "T-stale-demo")
    status, posted_snap = request(base, "POST", "/tasks/T-stale-demo/snapshots", stale)
    if status != 201:
        raise SystemExit(f"过期快照未被接受 {status} {posted_snap}")
    status, stale_plan = request(base, "POST", "/tasks/T-stale-demo/plan", {})
    if status != 409 or not isinstance(stale_plan.get("detail"), str) or "valid_until" not in stale_plan["detail"]:
        raise SystemExit(f"过期快照规划应 409，实际 {status} {stale_plan}")

    status, bound = request(
        base,
        "POST",
        "/tasks/T-20261109-001/snapshots/from-scene",
        {"scene_id": "v0", "active_zone_ids": ["R01"], "occupied_site_ids": ["L2"]},
    )
    if status != 201:
        raise SystemExit(f"from-scene {status} {bound}")
    fresh = next(item["snapshot"] for item in snapshots if item["task_id"] == "T-20261109-001")
    same_keys(fresh, bound["snapshot"], "snapshot")
    occupied = {site["site_id"]: site["occupied"] for site in bound["snapshot"]["landing_sites"]}
    if occupied.get("L2") is not True or bound["snapshot"]["events"][0]["geometry"]["zone_id"] != "R01":
        raise SystemExit("from-scene 没有按 R01 / L2 生效")

    status, plan = request(base, "POST", "/tasks/T-20261109-001/plan", {})
    if status != 200:
        raise SystemExit(f"plan {status} {plan}")
    route_mock = load("routes.json")[0]["routes"][0]
    same_keys(route_mock, plan["route"], "route")
    same_keys(load("plan_found.json")["agent"], plan["agent"], "agent")
    if plan["route"]["found"] is not True:
        raise SystemExit("默认真规划应找到航线，形状对照仍以字段为准")
    if plan["agent"]["applied"] is not False:
        raise SystemExit("agent.applied 必须为 false")

    status, margin = request(base, "GET", "/tasks/T-20261109-001/routes/v1/margin")
    if status != 200:
        raise SystemExit(f"margin {status}")
    same_keys(load("margin_v1.json"), margin, "margin")
    if margin["status"] != "unavailable" or any(margin[key] is not None for key in ("profile", "min_margin_wh", "negative_sample_count", "is_feasible")):
        raise SystemExit(f"真实余量不是 unavailable/null：{margin}")
    print("shape compare passed against", base)


if __name__ == "__main__":
    main()
