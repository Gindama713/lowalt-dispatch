"""C-STATIC-TEST@1 —— 低空配送控制台的静态契约与表述红线检查（pytest）。

为什么存在
----------
控制台的数据与结构契约（`C-CRS@1` / `C-SCENE-GEO@1` / `C-SCENE-DATA@1` /
`C-MARGIN-INVARIANT@1` / `C-COPY@1` / `C-PAGE-ANCHORS@1`）只写在计划里，
靠人眼比对会漏。本文件把"契约是否被真实实现"变成可复跑的门禁，
失败信息一律带"契约 ID + 字段路径 + 实际值"，便于对应 owner 单点修复。

边界（不要误读结论）
--------------------
* 只读产品文件（`apps/web/**`、`scenarios/v0/**`、`core/models.py`、
  `eval/scenarios/v0.yaml`），不写入仓库内任何文件、不产生临时文件。
* 不依赖网络、不依赖浏览器、不依赖 node：只用 Python 标准库 + pytest；
  `pyyaml` / `pydantic` 缺失时对应断言 `pytest.skip` 并注明原因。
* 通过只说明"静态数据与结构合规"，不证明运行期渲染 / 交互正确——
  后者由 T4（浏览器验收）与 T5（独立终验）承担。

运行
----
    pytest tests/test_web_console_static.py -q
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "apps" / "web"
INDEX_HTML = WEB_DIR / "index.html"
SCENE_JS = WEB_DIR / "assets" / "scene.js"
WEB_README = WEB_DIR / "README.md"
SCENARIO_DIR = REPO_ROOT / "scenarios" / "v0"
EVAL_SCENARIO_YAML = REPO_ROOT / "eval" / "scenarios" / "v0.yaml"

# 演示时钟基准时刻：`at_s` / `effective_from` 的换算是相对它进行的
# （见 C-SCENE-DATA@1.4 与 eval/scenarios/v0.yaml 的坐标约定）。
BASE_TIME = datetime(2026, 11, 10, 0, 0, 0, tzinfo=UTC)

# C-SCENE-DATA@1.1：必须存在的 5 个 task_id 与其来源场景（eval/scenarios/v0.yaml）
EXPECTED_TASKS = {
    "T-S1-01": "S1-01",
    "T-S2-01": "S2-01",
    "T-S2-04": "S2-04",
    "T-S3-03": "S3-03",
    "T-S4-01": "S4-01",
}

# C-SCENE-DATA@1.2：必须存在的 5 条候选路线及其固定元数据
EXPECTED_ROUTES = {
    "RT-S2-01-A": {
        "task_id": "T-S2-01",
        "plan_version": "v1",
        "algorithm": "astar_static",
        "diversion_site_id": "L2",
    },
    "RT-S2-01-B": {
        "task_id": "T-S2-01",
        "plan_version": "v2",
        "algorithm": "astar_diversion_aware",
        "diversion_site_id": "L2",
    },
    "RT-S1-01-A": {
        "task_id": "T-S1-01",
        "plan_version": "v1",
        "algorithm": "astar_static",
        "diversion_site_id": "L4",
    },
    "RT-S2-04-A": {
        "task_id": "T-S2-04",
        "plan_version": "v1",
        "algorithm": "astar_static",
        "diversion_site_id": "L2",
    },
    "RT-S3-03-A": {
        "task_id": "T-S3-03",
        "plan_version": "v1",
        "algorithm": "astar_static",
        "diversion_site_id": "L2",
    },
}

# C-SCENE-DATA@1.3：必须存在的 4 条剖面
PROFILE_ROUTE_IDS = ("RT-S2-01-A", "RT-S2-01-B", "RT-S1-01-A", "RT-S2-04-A")

# C-SCENE-GEO@1：三份内联 FeatureCollection 的要素数量与仓库基线文件
GEOJSON_BASELINES = (
    ("landing_sites", 4, "landing_sites.geojson"),
    ("zones", 4, "zones.geojson"),
    ("obstacles", 20, "obstacles.geojson"),
)

# C-STATIC-TEST@1「CDN 锁版本」：五个固定版本串（禁止浮动版本）
CDN_LOCKED = (
    ("maplibre-gl", "4.7.1"),
    ("deck.gl", "9.1.0"),
    ("@deck.gl/mapbox", "9.1.0"),
    ("@deck.gl/layers", "9.1.0"),
    ("@deck.gl/geo-layers", "9.1.0"),
)

# C-SCENE-DATA@1.4：RiskEvent.kind 的五个合法取值（plan_version_change 不是第六种）
RISK_EVENT_KINDS = (
    "restriction_zone",
    "wind",
    "link_degradation",
    "landing_site_change",
    "battery_anomaly",
)
PLAN_VERSION_CHANGE_KIND = "plan_version_change"

# C-COPY@1：文件级禁用词（含注释、不区分大小写；用整词/整短语匹配，
# 保证页脚"视觉语言参考 HALOFLUX by Ryder191"这类合法引用不会误报）。
FORBIDDEN_PHRASES = (
    ("实飞", "仓库红线：仿真不得称为实飞"),
    ("真实飞行", "仓库红线：仿真不得称为真实飞行"),
    ("实测数据", "无实测数据：本项目只有仿真/构造数据"),
    ("实测飞行", "无实测数据：本项目只有仿真/构造数据"),
    ("边缘实时重规划", "仓库红线：本地备用方案切换 ≠ 边缘实时重规划"),
    ("Agent 自主决策", "仓库红线：固定顺序调用工具，不是自主决策"),
    ("自主决策", "仓库红线：固定顺序调用工具，不是自主决策"),
    ("生产环境", "与前端原型定位冲突"),
    ("已上线", "与前端原型定位冲突"),
    ("移植自", "版权：仅借鉴视觉语言，不得声称移植源码"),
    ("forked from", "版权：仅借鉴视觉语言，不得声称 fork 源码"),
    ("HALOFLUX 源码", "版权：仅借鉴视觉语言，不得声称使用其源码"),
)

# C-COPY@1「必须出现的文案」中可由静态扫描客观判定的两条：
REQUIRED_COPY_IN_HTML = (
    ("仿真数据", "页头/状态区必须常驻仿真标注（R10.1）"),
    ("SITL", "页头/状态区必须常驻 SITL 软件在环仿真标注（R10.1）"),
    ("无实机飞行", "页头/状态区必须声明无实机飞行（R10.1）"),
    ("HALOFLUX by Ryder191", "页脚必须注明视觉语言来源（R10.4）"),
    ("原创实现", "页脚必须声明页面为原创实现（R10.4）"),
)

# C-PAGE-ANCHORS@1：必需 DOM 锚点（id 必须存在且唯一）
REQUIRED_ANCHOR_IDS = (
    "app",
    "kpi-strip",
    "stage",
    "stage-overlay",
    "mode-toggle",
    "play-toggle",
    "degradation-banner",
    "margin-profile",
    "task-list",
    "task-detail",
    "route-list",
    "event-timeline",
    "legend",
    "footer-copyright",
)

# C5：以 core/models.py 的 pydantic 模型字段为基准；模块不可用时退化为显式常量。
# 退化常量的值与 core/models.py 当前字段逐字一致，改动 models.py 时需同步本节。
_FALLBACK_FIELDS = {
    "Task": {
        "task_id",
        "origin",
        "destination",
        "payload_kg",
        "vehicle_type",
        "initial_energy_wh",
        "reserve_energy_wh",
        "time_limit_s",
        "provenance",
    },
    "RoutePlan": {
        "route_id",
        "plan_version",
        "snapshot_id",
        "algorithm",
        "waypoints",
        "energy_budget_wh",
        "diversion_site_id",
        "valid_until",
        "checks",
    },
    "DiversionMarginProfile": {"route_id", "plan_version", "reserve_wh", "samples"},
    "DiversionMarginSample": {"s_m", "t_s", "margin_wh", "nearest_site_id", "energy_need_wh"},
}

# 静态控制台采样写于该字段加入之前。模型默认 None，缺省即未提供，不改写 apps/web/assets/scene.js。
OPTIONAL_SAMPLE_FIELDS = {"energy_need_wh"}

# C-SCENE-DATA@1 允许的"新增展示字段"（除模型字段之外只允许这些键）
ALLOWED_EXTRA_TASK_FIELDS = {"scenario_ref", "title", "status", "is_simulated"}
ALLOWED_EXTRA_ROUTE_FIELDS = {"task_id", "is_simulated"}
ALLOWED_EXTRA_PROFILE_FIELDS = {"task_id", "is_simulated"}
ALLOWED_EXTRA_SAMPLE_FIELDS = {"e_left_wh", "e_need_wh"}

# 浮点判定容差
EPS = 1e-9
ROUNDTRIP_TOL_M = 1e-6  # C-CRS@1 往返误差
MARGIN_IDENTITY_TOL_WH = 0.05  # C-MARGIN-INVARIANT@1 I6
MARGIN_ABS_LIMIT_WH = 500.0  # C-MARGIN-INVARIANT@1 I7
SAMPLE_STEP_MAX_M = 20.0  # C-SCENE-DATA@1.3 采样步长上限


# --------------------------------------------------------------------------- #
# 通用工具
# --------------------------------------------------------------------------- #
def _rel(path: Path) -> str:
    """把绝对路径转成相对仓库根的展示路径。"""
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _fail(message: str) -> NoReturn:
    """失败即带诊断直出，不打印无关的断言回溯栈。"""
    pytest.fail(message, pytrace=False)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _is_number(value: Any) -> bool:
    """真正的数值（排除 bool，排除 NaN/Infinity）。"""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _num(value: Any, digits: int = 6) -> str:
    """稳定格式化的数值/取值，用于失败信息里的"实际值"。"""
    if _is_number(value):
        return f"{float(value):.{digits}f}"
    return repr(value)


def _require_file(path: Path, owner: str) -> None:
    """文件存在性门禁：缺失时给出 owner 与"待联调"提示，而不是笼统报错。"""
    if not path.exists():
        _fail(
            f"[文件存在] {_rel(path)} 不存在（owner={owner}）。"
            f"该断言属于 C-STATIC-TEST@1 文件存在组：产物未交付时项为「待联调」，"
            f"待 {owner} 交付后复跑即可。"
        )
    if path.stat().st_size == 0:
        _fail(f"[文件存在] {_rel(path)} 存在但内容为空（owner={owner}）。")


def _parse_iso_utc(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


class SceneDataError(RuntimeError):
    """`scene.js` 数据块提取或解析失败，携带定位诊断（C1 要求，不是裸异常）。"""


def _reject_json_constant(name: str) -> NoReturn:
    """JSON 标准不允许 NaN/Infinity；json.loads 默认接受，必须显式拒绝。"""
    raise ValueError(f"数据块内出现非法 JSON 常量 {name}（C-STATIC-TEST@1 明确禁止）")


def _match_brace(text: str, open_index: int) -> int:
    """从 `open_index` 处的 `{` 起按括号配平，返回配对的 `}` 下标（-1 表示未闭合）。

    需要识别 JSON 字符串与转义，避免把字符串里的 `{`/`}` 计入深度。
    """
    depth = 0
    in_string = False
    escaped = False
    for index in range(open_index, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _block_snippet(text: str, open_index: int, end_index: int, error_line: int) -> str:
    """截取错误附近的源码片段（带行号），便于 owner 直接定位。"""
    start_line = max(1, error_line - 2)
    stop_line = error_line + 2
    lines = text.splitlines()
    return "\n".join(
        f"  {line_no:>5} | {lines[line_no - 1]}"
        for line_no in range(start_line, min(stop_line, len(lines)) + 1)
    )


def extract_scene_data(scene_js: Path = SCENE_JS) -> dict[str, Any]:
    """从 `scene.js` 中提取 `window.LOWALT_SCENE_DATA = {...};` 并 json.loads。

    C-STATIC-TEST@1 的提取规则：定位赋值号后的第一个 `{`，按括号配平找到闭合
    `}`，再整体 `json.loads`。任何失败都以 `SceneDataError` 报告契约 ID、
    行号与错误片段，调用方据此转成可读的 pytest 失败信息（C1）。
    """
    text = _read_text(scene_js)
    marker = "window.LOWALT_SCENE_DATA"
    marker_index = text.find(marker)
    if marker_index < 0:
        raise SceneDataError(
            f"[C1] {_rel(scene_js)} 中找不到 `{marker}` 赋值语句。"
            "C-STATIC-TEST@1 要求 scene.js 以 `window.LOWALT_SCENE_DATA = {...};` 形式导出数据。"
        )

    equals_index = text.find("=", marker_index + len(marker))
    if equals_index < 0:
        raise SceneDataError(
            f"[C1] {_rel(scene_js)} 第 {text.count(chr(10), 0, marker_index) + 1} 行出现 `{marker}`，"
            "但其后没有赋值号 `=`，无法提取数据块。"
        )

    open_index = text.find("{", equals_index)
    if open_index < 0:
        raise SceneDataError(
            f"[C1] {_rel(scene_js)} 中 `{marker}` 的赋值号之后找不到 `{{`，"
            "数据块必须是 JSON 对象字面量（不允许先出现变量/函数调用）。"
        )

    end_index = _match_brace(text, open_index)
    first_line = text.count("\n", 0, open_index) + 1
    if end_index < 0:
        raise SceneDataError(
            f"[C1] {_rel(scene_js)} 第 {first_line} 行起的 `{marker}` 数据块括号未配平（缺少 `}}`）。"
        )

    after = text[end_index + 1 :].lstrip()
    if not after.startswith(";"):
        raise SceneDataError(
            f"[C1] {_rel(scene_js)} 数据块闭合 `}}` 之后未紧跟 `;`（实际后随字符：{after[:24]!r}）。"
            "C-STATIC-TEST@1 要求数据块独占一个赋值表达式并以分号结束。"
        )

    block = text[open_index : end_index + 1]
    try:
        data = json.loads(block, parse_constant=_reject_json_constant)
    except json.JSONDecodeError as exc:
        error_line = first_line + exc.lineno - 1
        raise SceneDataError(
            f"[C1] {_rel(scene_js)} 第 {first_line} 行起的 `{marker}` 数据块不是合法 JSON：\n"
            f"  {exc.msg}（数据块内第 {exc.lineno} 行、第 {exc.colno} 列 → 文件第 {error_line} 行）\n"
            "  —— 数据块内不得含注释、函数、单引号、尾逗号、undefined、NaN、Infinity。\n"
            + _block_snippet(text, open_index, end_index, error_line)
        ) from exc
    except ValueError as exc:
        raise SceneDataError(
            f"[C1] {_rel(scene_js)} 第 {first_line} 行起的 `{marker}` 数据块不是合法 JSON：{exc}"
        ) from exc

    if not isinstance(data, dict):
        raise SceneDataError(
            f"[C1] {_rel(scene_js)} 中 `{marker}` 解析结果类型为 {type(data).__name__}，"
            "期望 JSON 对象（dict）。"
        )
    return data


# --------------------------------------------------------------------------- #
# C5：字段集合以 core/models.py 的 pydantic 模型为准（不可用时退化常量）
# --------------------------------------------------------------------------- #
try:  # pragma: no cover - 依赖环境，两条分支都要能跑
    from core.models import DiversionMarginProfile as _ProfileModel
    from core.models import DiversionMarginSample as _SampleModel
    from core.models import RoutePlan as _RouteModel
    from core.models import Task as _TaskModel
except Exception:  # pydantic 或 core.models 不可用：退化为显式常量（见 _FALLBACK_FIELDS）
    _TaskModel = _RouteModel = _ProfileModel = _SampleModel = None


def _model_field_names(model: Any, model_name: str) -> tuple[set[str], str]:
    """返回 (字段集合, 基准来源说明)。优先 pydantic model_fields，否则退化常量。"""
    fields = getattr(model, "model_fields", None) if model is not None else None
    if isinstance(fields, dict) and fields:
        return set(fields), "core.models.py/pydantic model_fields"
    return set(_FALLBACK_FIELDS[model_name]), (
        "显式常量回退（pydantic 或 core.models 不可用，见 C5 注释；"
        "常量与 core/models.py 当前字段逐字一致）"
    )


# --------------------------------------------------------------------------- #
# 几何工具：点在多边形内（射线法）与线段相交
# --------------------------------------------------------------------------- #
def _ring(polygon: Sequence[Sequence[float]]) -> list[tuple[float, float]]:
    """规范化环：去掉闭合环末尾的重复点，便于按边遍历。"""
    points = [(float(point[0]), float(point[1])) for point in polygon]
    if len(points) >= 2 and points[0] == points[-1]:
        points = points[:-1]
    return points


def point_in_polygon(x: float, y: float, polygon: Sequence[Sequence[float]]) -> bool:
    """射线法：从 (x, y) 向东发射射线，统计与多边形边的交点数量奇偶性。"""
    points = _ring(polygon)
    if len(points) < 3:
        return False
    inside = False
    count = len(points)
    for index in range(count):
        x_i, y_i = points[index]
        x_j, y_j = points[index - 1]
        if (y_i > y) != (y_j > y):
            x_cross = (x_j - x_i) * (y - y_i) / (y_j - y_i) + x_i
            if x < x_cross:
                inside = not inside
    return inside


def _orientation(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> float:
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def _on_segment(
    ax: float, ay: float, bx: float, by: float, cx: float, cy: float
) -> bool:
    return (
        min(ax, bx) - EPS <= cx <= max(ax, bx) + EPS
        and min(ay, by) - EPS <= cy <= max(ay, by) + EPS
    )


def segments_intersect(
    p1: Sequence[float], p2: Sequence[float], p3: Sequence[float], p4: Sequence[float]
) -> bool:
    """线段 p1p2 与 p3p4 是否相交（含共线重叠、端点接触）。"""
    ax, ay = float(p1[0]), float(p1[1])
    bx, by = float(p2[0]), float(p2[1])
    cx, cy = float(p3[0]), float(p3[1])
    dx, dy = float(p4[0]), float(p4[1])

    d1 = _orientation(cx, cy, dx, dy, ax, ay)
    d2 = _orientation(cx, cy, dx, dy, bx, by)
    d3 = _orientation(ax, ay, bx, by, cx, cy)
    d4 = _orientation(ax, ay, bx, by, dx, dy)

    if (
        ((d1 > EPS and d2 < -EPS) or (d1 < -EPS and d2 > EPS))
        and ((d3 > EPS and d4 < -EPS) or (d3 < -EPS and d4 > EPS))
    ):
        return True
    if abs(d1) <= EPS and _on_segment(cx, cy, dx, dy, ax, ay):
        return True
    if abs(d2) <= EPS and _on_segment(cx, cy, dx, dy, bx, by):
        return True
    if abs(d3) <= EPS and _on_segment(ax, ay, bx, by, cx, cy):
        return True
    if abs(d4) <= EPS and _on_segment(ax, ay, bx, by, dx, dy):
        return True
    return False


def polyline_hits_polygon(
    points: Sequence[Sequence[float]], polygon: Sequence[Sequence[float]]
) -> bool:
    """折线是否与多边形相交：顶点落在多边形内，或任一段与任一边相交。"""
    ring = _ring(polygon)
    if len(ring) < 3:
        return False
    for point in points:
        if point_in_polygon(float(point[0]), float(point[1]), ring):
            return True
    edge_count = len(ring)
    for index in range(len(points) - 1):
        segment_start = points[index]
        segment_end = points[index + 1]
        for edge_index in range(edge_count):
            edge_start = ring[edge_index]
            edge_end = ring[(edge_index + 1) % edge_count]
            if segments_intersect(segment_start, segment_end, edge_start, edge_end):
                return True
    return False


def polyline_length(points: Sequence[Sequence[float]]) -> float:
    """折线的 ENU 平面长度总和（m）。"""
    total = 0.0
    for index in range(len(points) - 1):
        dx = float(points[index + 1][0]) - float(points[index][0])
        dy = float(points[index + 1][1]) - float(points[index][1])
        total += math.hypot(dx, dy)
    return total


# --------------------------------------------------------------------------- #
# 数据访问工具
# --------------------------------------------------------------------------- #
def _index_by(items: Any, key: str) -> dict[str, dict[str, Any]]:
    """把对象数组按某个键索引；非数组或元素非对象时返回空表（由断言报违例）。"""
    if not isinstance(items, list):
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for item in items:
        if isinstance(item, dict) and isinstance(item.get(key), str):
            indexed.setdefault(item[key], item)
    return indexed


def _require(mapping: Any, path: str, violations: list[str], contract: str) -> Any:
    """按点路径取值；缺失时记录违例并返回 None。"""
    current: Any = mapping
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            violations.append(f"{contract} 缺少字段 `{path}`（实际类型：{type(current).__name__}）")
            return None
        current = current[part]
    return current


def _report(contract: str, title: str, violations: Sequence[str]) -> None:
    """把累积的违例一次性报告，避免只暴露第一条。"""
    if not violations:
        return
    details = "\n".join(f"  - {item}" for item in violations)
    _fail(f"{contract} {title}：{len(violations)} 条违例\n{details}")


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def scene() -> dict[str, Any]:
    """解析后的 `LOWALT_SCENE_DATA`。

    产物未交付 → skip（"待联调"，不是测试失败）；数据块不可解析 → skip，
    真正失败由 test_c1_scene_data_block_extractable 单点报告，避免重复刷屏。
    """
    if not SCENE_JS.exists() or SCENE_JS.stat().st_size == 0:
        pytest.skip(
            "SKIP [待联调] apps/web/assets/scene.js 尚未交付（owner=T1）；"
            "数据类断言待产物到位后复跑"
        )
    try:
        return extract_scene_data(SCENE_JS)
    except SceneDataError as exc:
        pytest.skip(
            "SKIP [阻塞] scene.js 数据块不可解析，诊断见 test_c1_scene_data_block_extractable："
            f"{exc}"
        )


@pytest.fixture(scope="module")
def scene_text() -> str:
    _require_file(SCENE_JS, "T1")
    return _read_text(SCENE_JS)


@pytest.fixture(scope="module")
def html() -> str:
    _require_file(INDEX_HTML, "T2")
    return _read_text(INDEX_HTML)


def _crs(scene_data: dict[str, Any]) -> dict[str, Any]:
    crs = scene_data.get("crs")
    if not isinstance(crs, dict):
        _fail(f"C-CRS@1 LOWALT_SCENE_DATA.crs 缺失或类型不是对象（实际：{type(crs).__name__}）")
    return crs


def _crs_numbers(crs: dict[str, Any]) -> tuple[float, float, float, float]:
    """返回 (origin_lat_deg, origin_lon_deg, meters_per_deg_lat, meters_per_deg_lon)。"""
    values = []
    for key in ("origin_lat_deg", "origin_lon_deg", "meters_per_deg_lat", "meters_per_deg_lon"):
        value = crs.get(key)
        if not _is_number(value):
            _fail(f"C-CRS@1 crs.{key} 缺失或不是有限数值（实际：{value!r}）")
        values.append(float(value))
    return values[0], values[1], values[2], values[3]


def _enu_to_lnglat(crs: dict[str, Any], x_m: float, y_m: float) -> tuple[float, float]:
    lat0, lon0, m_per_lat, m_per_lon = _crs_numbers(crs)
    return lon0 + x_m / m_per_lon, lat0 + y_m / m_per_lat


def _lnglat_to_enu(crs: dict[str, Any], lng: float, lat: float) -> tuple[float, float]:
    lat0, lon0, m_per_lat, m_per_lon = _crs_numbers(crs)
    return (lng - lon0) * m_per_lon, (lat - lat0) * m_per_lat


def _coverage(scene_data: dict[str, Any]) -> dict[str, Any] | None:
    """取覆盖范围对象：C-CRS@1 规定其内容，但未强制挂载层级。

    允许 `LOWALT_SCENE_DATA.coverage` 与 `LOWALT_SCENE_DATA.crs.coverage` 两种位置，
    避免把"位置不同"当成数值违约。
    """
    coverage = scene_data.get("coverage")
    if isinstance(coverage, dict):
        return coverage
    crs = scene_data.get("crs")
    if isinstance(crs, dict):
        nested = crs.get("coverage")
        if isinstance(nested, dict):
            return nested
    return None


def _zones(scene_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _index_by(scene_data.get("zones"), "zone_id")


def _routes(scene_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _index_by(scene_data.get("routes"), "route_id")


def _tasks(scene_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _index_by(scene_data.get("tasks"), "task_id")


def _profiles(scene_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _index_by(scene_data.get("margin_profiles"), "route_id")


def _route_points(route: dict[str, Any]) -> list[tuple[float, float]]:
    """把 waypoints 转成 ENU 平面点列（忽略高度）。"""
    points: list[tuple[float, float]] = []
    waypoints = route.get("waypoints")
    if not isinstance(waypoints, list):
        return points
    for waypoint in waypoints:
        if not isinstance(waypoint, dict):
            continue
        x_m = waypoint.get("x_m")
        y_m = waypoint.get("y_m")
        if _is_number(x_m) and _is_number(y_m):
            points.append((float(x_m), float(y_m)))
    return points


def _zone_polygon(zone: dict[str, Any]) -> list[tuple[float, float]] | None:
    polygon = zone.get("polygon_enu")
    if not isinstance(polygon, list) or len(polygon) < 3:
        return None
    ring: list[tuple[float, float]] = []
    for point in polygon:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            return None
        if not (_is_number(point[0]) and _is_number(point[1])):
            return None
        ring.append((float(point[0]), float(point[1])))
    return ring


# --------------------------------------------------------------------------- #
# 组 1：C1 —— 数据块可提取 + 必需文件存在
# --------------------------------------------------------------------------- #
def test_c1_scene_data_block_extractable() -> None:
    """C1：scene.js 必须能按括号配平提取数据块并 json.loads 成功。"""
    _require_file(SCENE_JS, "T1")
    try:
        data = extract_scene_data(SCENE_JS)
    except SceneDataError as exc:  # 明确诊断，而不是裸异常
        _fail(str(exc))
    assert isinstance(data, dict)
    # 顶层必备键（缺任一都说明数据契约未实现，先在 C1 就暴露）
    missing = [
        key
        for key in ("schema_version", "crs", "geojson", "sites", "zones", "obstacles", "tasks", "routes")
        if key not in data
    ]
    if missing:
        _fail(f"[C1] LOWALT_SCENE_DATA 缺少顶层键：{', '.join(missing)}")


@pytest.mark.parametrize(
    ("path", "owner"),
    ((INDEX_HTML, "T2"), (SCENE_JS, "T1"), (WEB_README, "T4")),
    ids=("index.html", "assets/scene.js", "README.md"),
)
def test_required_files_exist(path: Path, owner: str) -> None:
    """C-STATIC-TEST@1「文件存在」组：三个交付文件均存在且非空。"""
    _require_file(path, owner)


# --------------------------------------------------------------------------- #
# 组 2：无构建痕迹（index.html 必须能 file:// 双击打开，无构建依赖）
# --------------------------------------------------------------------------- #
def _strip_absolute_urls(text: str) -> str:
    """去掉绝对 URL，再做"本地构建痕迹"扫描。

    目的：CDN 资源里出现 `.../dist/dist.min.js` 属于正常（不是本地构建产物），
    必须先剔除，否则会误报"引用 dist/"。
    """
    return re.sub(r"(?:https?:)?//[^\s\"'<>)]+", "", text)


def test_no_build_traces(html: str) -> None:
    """C-STATIC-TEST@1「无构建痕迹」：不引用 node_modules/dist/.ts，无 module/require/import。"""
    local_html = _strip_absolute_urls(html)
    patterns = (
        (re.compile(r"node_modules"), "引用了 node_modules（构建依赖）"),
        (re.compile(r"(?<![\w.-])dist/"), "引用了本地 dist/ 构建目录"),
        (re.compile(r"\.tsx?\b"), "引用了 TypeScript 源文件（.ts/.tsx）"),
        (re.compile(r"(?:^|[\s;{}(=])import\s+[\w{*\"']", re.M), "出现 ES module `import`"),
        (re.compile(r"\brequire\s*\("), "出现 `require(`（CommonJS/构建痕迹）"),
        (re.compile(r"""type\s*=\s*["']module["']"""), "出现 type=\"module\"（file:// 下会被浏览器拒绝）"),
    )
    violations: list[str] = []
    for pattern, reason in patterns:
        for match in pattern.finditer(local_html):
            line_no = local_html.count("\n", 0, match.start()) + 1
            violations.append(
                f"index.html:{line_no} {reason}，命中片段：{match.group(0)[:60]!r}"
            )
    _report(
        "C-STATIC-TEST@1[无构建痕迹]",
        "index.html（剔除绝对 URL 后）不得含构建痕迹",
        violations,
    )


# --------------------------------------------------------------------------- #
# 组 3：CDN 锁版本
# --------------------------------------------------------------------------- #
def _package_url_versions(html_text: str, package: str) -> list[str | None]:
    """返回 html 中每个「URL 路径段级」`package` 引用处的版本段（含 `@`），无版本为 None。

    必须按 `(?:^|/)包名@版本(?=/|$)` 匹配，原因有二：
    * `@deck.gl/layers@9.1.0` 中出现的 `deck.gl` 不能算作 `deck.gl` 主包的引用
      （前置字符是 `@`，不被 `(?:^|/)` 接受）；
    * `.../dist/maplibre-gl.js` 这类资源文件名不是包引用
      （包名后紧跟 `.js`，不被终止符集合 `/ $ ? # 引号 空白 >` 接受）；
    * `<script src=".../maplibre-gl@4.7.1">` 这种省略子路径的 UMD 引用必须被接受
      （版本段后紧跟 HTML 引号，因此终止符集合包含引号/空白/`>`）。
    """
    pattern = re.compile(
        r"(?:^|/)"
        + re.escape(package)
        + r"(?P<version>@[^/\s\"'<>?#]*)?(?=/|$|\?|#|[\"'\s>])"
    )
    return [match.group("version") for match in pattern.finditer(html_text)]


def test_cdn_versions_locked(html: str) -> None:
    """C-STATIC-TEST@1「CDN 锁版本」：五个固定版本串存在，且无浮动/省略版本。"""
    violations: list[str] = []
    for package, version in CDN_LOCKED:
        locked = f"{package}@{version}"
        if locked not in html:
            violations.append(f"index.html 未出现锁定版本串 `{locked}`")
        found = _package_url_versions(html, package)
        if not found:
            violations.append(f"index.html 未引用 `{package}`（找不到任何版本引用）")
        for version_segment in found:
            if version_segment != f"@{version}":
                violations.append(
                    f"index.html 中 `{package}` 的版本段为 {version_segment!r}，"
                    f"期望 `@{version}`（禁止浮动版本/省略版本）"
                )
    if re.search(r"@latest", html, re.IGNORECASE):
        violations.append("index.html 出现 `@latest`（禁止浮动版本）")
    _report("C-STATIC-TEST@1[CDN 锁版本]", "CDN 依赖必须锁定固定版本", violations)


# --------------------------------------------------------------------------- #
# 组 4：C-CRS@1 —— 常量、往返误差、覆盖范围、派生值经纬度顺序
# --------------------------------------------------------------------------- #
def test_crs_constants(scene: dict[str, Any]) -> None:
    """C-CRS@1：frame/原点/每度米数/近似标识/免责声明。"""
    crs = _crs(scene)
    violations: list[str] = []

    if crs.get("frame") != "enu_m":
        violations.append(f"crs.frame={crs.get('frame')!r}，期望 'enu_m'")
    if crs.get("approximation") != "equirectangular_demo":
        violations.append(
            f"crs.approximation={crs.get('approximation')!r}，期望 'equirectangular_demo'"
        )
    if crs.get("is_demo_approximation") is not True:
        violations.append(
            f"crs.is_demo_approximation={crs.get('is_demo_approximation')!r}，期望 True（机读标识）"
        )

    lat0, lon0, m_per_lat, m_per_lon = _crs_numbers(crs)
    if abs(lat0 - 31.2304) > 1e-9:
        violations.append(f"crs.origin_lat_deg={_num(lat0)}，期望 31.2304")
    if abs(lon0 - 121.4737) > 1e-9:
        violations.append(f"crs.origin_lon_deg={_num(lon0)}，期望 121.4737")
    if abs(m_per_lat - 111320.0) > 1e-6:
        violations.append(f"crs.meters_per_deg_lat={_num(m_per_lat)}，期望 111320")

    expected_lon = 111320.0 * math.cos(math.radians(lat0))
    if abs(m_per_lon - expected_lon) > 1.0:
        violations.append(
            f"crs.meters_per_deg_lon={_num(m_per_lon, 4)}，"
            f"期望 111320*cos({_num(lat0, 4)})={_num(expected_lon, 4)}（容差 ±1.0）"
        )

    disclaimer = crs.get("disclaimer")
    if not isinstance(disclaimer, str) or not disclaimer.strip():
        violations.append(f"crs.disclaimer={disclaimer!r}，期望非空字符串（性质声明全文）")
    else:
        for keyword in ("ENU", "WGS84", "演示"):
            if keyword not in disclaimer:
                violations.append(
                    f"crs.disclaimer 缺少关键词 `{keyword}`（应声明为 ENU→WGS84 演示近似）"
                )

    coverage = _coverage(scene)
    if coverage is None:
        violations.append(
            "coverage 缺失：`LOWALT_SCENE_DATA.coverage` 与 `LOWALT_SCENE_DATA.crs.coverage` "
            "均未提供（C-CRS@1 覆盖范围对象）"
        )
    else:
        for key, expected in (
            ("min_x_m", 0.0),
            ("max_x_m", 3000.0),
            ("min_y_m", 0.0),
            ("max_y_m", 3000.0),
        ):
            actual = coverage.get(key)
            if not _is_number(actual) or abs(float(actual) - expected) > EPS:
                violations.append(f"coverage.{key}={actual!r}，期望 {_num(expected, 1)}")

    _report("C-CRS@1", "坐标常量与覆盖范围", violations)


def test_crs_roundtrip_and_center(scene: dict[str, Any]) -> None:
    """C-CRS@1：往返误差 < 1e-6 m；中心点 lnglat 由 enuToLngLat(1500,1500) 复算。"""
    crs = _crs(scene)
    violations: list[str] = []
    for x_m in (0.0, 750.0, 1500.0, 2250.0, 3000.0):
        for y_m in (0.0, 750.0, 1500.0, 2250.0, 3000.0):
            lng, lat = _enu_to_lnglat(crs, x_m, y_m)
            x_back, y_back = _lnglat_to_enu(crs, lng, lat)
            error = math.hypot(x_back - x_m, y_back - y_m)
            if error >= ROUNDTRIP_TOL_M:
                violations.append(
                    f"ENU({_num(x_m, 1)}, {_num(y_m, 1)}) 往返误差 {error:.3e} m ≥ 1e-6 m"
                )

    coverage = _coverage(scene)
    if coverage is not None:
        center = coverage.get("center_lnglat")
        expected_lng, expected_lat = _enu_to_lnglat(crs, 1500.0, 1500.0)
        if not isinstance(center, (list, tuple)) or len(center) < 2:
            violations.append(f"coverage.center_lnglat={center!r}，期望 [lng, lat] 两元素数组")
        elif not (_is_number(center[0]) and _is_number(center[1])):
            violations.append(f"coverage.center_lnglat={center!r}，期望两个有限数值")
        else:
            d_lng = abs(float(center[0]) - expected_lng)
            d_lat = abs(float(center[1]) - expected_lat)
            if d_lng > 1e-5 or d_lat > 1e-5:
                violations.append(
                    f"coverage.center_lnglat={_num(center[0])},{_num(center[1])}，"
                    f"与 enuToLngLat(1500,1500)={_num(expected_lng)},{_num(expected_lat)} "
                    f"相差 ({d_lng:.2e}, {d_lat:.2e}) 度 > 1e-5"
                )

    _report("C-CRS@1", "坐标往返与覆盖中心", violations)


def test_crs_derived_lnglat_order(scene: dict[str, Any]) -> None:
    """C-CRS@1：所有派生的 `*_lnglat` 反算回 ENU 必须落在 coverage±50 m 内（防经纬度写反）。"""
    crs = _crs(scene)
    violations: list[str] = []
    low, high = -50.0, 3050.0

    def check_point(path: str, lng: Any, lat: Any) -> None:
        if not (_is_number(lng) and _is_number(lat)):
            violations.append(f"{path}=[{lng!r}, {lat!r}] 不是两个有限数值")
            return
        x_m, y_m = _lnglat_to_enu(crs, float(lng), float(lat))
        if not (low <= x_m <= high):
            violations.append(f"{path} 反算 x_m={_num(x_m, 1)} 超出 [{low:g}, {high:g}] m（经纬度顺序疑似写反）")
        if not (low <= y_m <= high):
            violations.append(f"{path} 反算 y_m={_num(y_m, 1)} 超出 [{low:g}, {high:g}] m（经纬度顺序疑似写反）")

    for index, site in enumerate(scene.get("sites") or []):
        if isinstance(site, dict):
            check_point(f"sites[i={index}].lnglat", *(site.get("lnglat") or [None, None])[:2])

    for index, zone in enumerate(scene.get("zones") or []):
        if not isinstance(zone, dict):
            continue
        centroid = zone.get("centroid_lnglat") or [None, None]
        check_point(f"zones[i={index}].centroid_lnglat", *centroid[:2])
        for point_index, point in enumerate(zone.get("polygon_lnglat") or []):
            if isinstance(point, (list, tuple)) and len(point) >= 2:
                check_point(f"zones[i={index}].polygon_lnglat[{point_index}]", point[0], point[1])

    for index, obstacle in enumerate(scene.get("obstacles") or []):
        if not isinstance(obstacle, dict):
            continue
        centroid = obstacle.get("centroid_lnglat") or [None, None]
        check_point(f"obstacles[i={index}].centroid_lnglat", *centroid[:2])
        for point_index, point in enumerate(obstacle.get("polygon_lnglat") or []):
            if isinstance(point, (list, tuple)) and len(point) >= 2:
                check_point(
                    f"obstacles[i={index}].polygon_lnglat[{point_index}]", point[0], point[1]
                )

    _report("C-CRS@1", "派生经纬度顺序与覆盖范围", violations)


# --------------------------------------------------------------------------- #
# 组 5：C-SCENE-GEO@1 —— 内联几何与三维派生
# --------------------------------------------------------------------------- #
def _load_baseline_geojson(filename: str) -> dict[str, Any]:
    path = SCENARIO_DIR / filename
    if not path.exists():
        pytest.skip(f"SKIP [基线缺失] scenarios/v0/{filename} 不存在，无法比对内联几何")
    try:
        return json.loads(_read_text(path))
    except json.JSONDecodeError as exc:  # pragma: no cover - 基线损坏属仓库问题
        pytest.skip(f"SKIP [基线损坏] scenarios/v0/{filename} 不是合法 JSON：{exc}")


def test_geojson_counts_and_crs_note(scene: dict[str, Any]) -> None:
    """C-SCENE-GEO@1：三键要素数 4/4/20，`crs_note` 原样保留。"""
    geojson = scene.get("geojson")
    if not isinstance(geojson, dict):
        _fail(f"C-SCENE-GEO@1 LOWALT_SCENE_DATA.geojson 缺失或类型错误（实际：{type(geojson).__name__}）")

    violations: list[str] = []
    for key, expected_count, filename in GEOJSON_BASELINES:
        collection = geojson.get(key)
        baseline = _load_baseline_geojson(filename)
        if not isinstance(collection, dict):
            violations.append(f"geojson.{key} 缺失或不是对象（实际：{type(collection).__name__}）")
            continue
        if collection.get("type") != "FeatureCollection":
            violations.append(f"geojson.{key}.type={collection.get('type')!r}，期望 'FeatureCollection'")
        features = collection.get("features")
        actual_count = len(features) if isinstance(features, list) else -1
        if actual_count != expected_count:
            violations.append(
                f"geojson.{key}.features 数量={actual_count}，期望 {expected_count}（基线 {filename}）"
            )
        if collection.get("crs_note") != baseline.get("crs_note"):
            violations.append(
                f"geojson.{key}.crs_note 与 scenarios/v0/{filename} 不一致（必须原样保留）"
            )
    _report("C-SCENE-GEO@1", "内联 FeatureCollection 数量与坐标说明", violations)


def test_geojson_properties_match_baseline(scene: dict[str, Any]) -> None:
    """C-SCENE-GEO@1：内联要素须与 scenarios/v0 文件逐字段同源（id 顺序、geometry、properties）。"""
    geojson = scene.get("geojson") or {}
    violations: list[str] = []
    for key, _count, filename in GEOJSON_BASELINES:
        collection = geojson.get(key)
        baseline = _load_baseline_geojson(filename)
        if not isinstance(collection, dict):
            violations.append(f"geojson.{key} 缺失，无法与 {filename} 比对")
            continue
        inline_features = collection.get("features") or []
        baseline_features = baseline.get("features") or []
        inline_ids = [
            feature.get("properties", {}).get("id")
            for feature in inline_features
            if isinstance(feature, dict)
        ]
        baseline_ids = [
            feature.get("properties", {}).get("id")
            for feature in baseline_features
            if isinstance(feature, dict)
        ]
        if inline_ids != baseline_ids:
            violations.append(
                f"geojson.{key} 要素 id 顺序={inline_ids!r}，期望（文件内顺序）={baseline_ids!r}"
            )
            continue
        for position, (inline, original) in enumerate(zip(inline_features, baseline_features, strict=False)):
            if inline.get("geometry") != original.get("geometry"):
                violations.append(
                    f"geojson.{key}.features[{position}]({inline_ids[position]}) "
                    f"geometry 与 scenarios/v0/{filename} 不一致（必须原样内联，不得换算）"
                )
            if inline.get("properties") != original.get("properties"):
                violations.append(
                    f"geojson.{key}.features[{position}]({inline_ids[position]}) "
                    f"properties 与 scenarios/v0/{filename} 不一致（必须逐字段原样）"
                )
    _report("C-SCENE-GEO@1", "内联几何与仓库基线同源", violations)


def test_sites_derived(scene: dict[str, Any]) -> None:
    """C-SCENE-GEO@1：sites 4 条、L1–L4 顺序、radius_m=30、Position 对齐、不含 alt_min_m。"""
    sites = scene.get("sites")
    if not isinstance(sites, list):
        _fail(f"C-SCENE-GEO@1 LOWALT_SCENE_DATA.sites 缺失或不是数组（实际：{type(sites).__name__}）")

    violations: list[str] = []
    site_ids = [site.get("site_id") for site in sites if isinstance(site, dict)]
    if site_ids != ["L1", "L2", "L3", "L4"]:
        violations.append(f"sites[*].site_id={site_ids!r}，期望 ['L1','L2','L3','L4']（按文件顺序）")

    for index, site in enumerate(sites):
        path = f"sites[i={index}]"
        if not isinstance(site, dict):
            violations.append(f"{path} 不是对象（实际：{type(site).__name__}）")
            continue
        if not _is_number(site.get("radius_m")) or abs(float(site["radius_m"]) - 30.0) > EPS:
            violations.append(f"{path}({site.get('site_id')}).radius_m={site.get('radius_m')!r}，期望 30")
        if site.get("kind") != "landing_site":
            violations.append(f"{path}({site.get('site_id')}).kind={site.get('kind')!r}，期望 'landing_site'")
        if site.get("is_simulated") is not True:
            violations.append(f"{path}({site.get('site_id')}).is_simulated={site.get('is_simulated')!r}，期望 True")
        if "alt_min_m" in site:
            violations.append(f"{path}({site.get('site_id')}) 不应含 alt_min_m（radius_m 只属于 sites，高度带只属于 zones）")

        position = site.get("position")
        if not isinstance(position, dict):
            violations.append(f"{path}({site.get('site_id')}).position 缺失或不是对象")
            continue
        if position.get("frame") != "enu_m":
            violations.append(f"{path}.position.frame={position.get('frame')!r}，期望 'enu_m'")
        if position.get("alt_ref") != "agl":
            violations.append(f"{path}.position.alt_ref={position.get('alt_ref')!r}，期望 'agl'")
        if not _is_number(position.get("alt_m")) or abs(float(position["alt_m"])) > EPS:
            violations.append(f"{path}.position.alt_m={position.get('alt_m')!r}，期望 0")
        for axis in ("x_m", "y_m"):
            if not _is_number(position.get(axis)):
                violations.append(f"{path}.position.{axis}={position.get(axis)!r}，期望有限数值")
            elif _is_number(site.get(axis)) and abs(float(site[axis]) - float(position[axis])) > EPS:
                violations.append(
                    f"{path}.{axis}={_num(site.get(axis))} 与 position.{axis}={_num(position.get(axis))} 不一致"
                )
    _report("C-SCENE-GEO@1", "备降点派生字段", violations)


def test_zones_derived(scene: dict[str, Any]) -> None:
    """C-SCENE-GEO@1：zones 4 条、R01–R04 顺序、高度带 0–120 m。"""
    zones = scene.get("zones")
    if not isinstance(zones, list):
        _fail(f"C-SCENE-GEO@1 LOWALT_SCENE_DATA.zones 缺失或不是数组（实际：{type(zones).__name__}）")

    violations: list[str] = []
    zone_ids = [zone.get("zone_id") for zone in zones if isinstance(zone, dict)]
    if zone_ids != ["R01", "R02", "R03", "R04"]:
        violations.append(f"zones[*].zone_id={zone_ids!r}，期望 ['R01','R02','R03','R04']（按文件顺序）")

    for index, zone in enumerate(zones):
        path = f"zones[i={index}]"
        if not isinstance(zone, dict):
            violations.append(f"{path} 不是对象（实际：{type(zone).__name__}）")
            continue
        if zone.get("kind") != "restriction_zone":
            violations.append(f"{path}({zone.get('zone_id')}).kind={zone.get('kind')!r}，期望 'restriction_zone'")
        for key, expected in (("alt_min_m", 0.0), ("alt_max_m", 120.0)):
            actual = zone.get(key)
            if not _is_number(actual) or abs(float(actual) - expected) > EPS:
                violations.append(f"{path}({zone.get('zone_id')}).{key}={actual!r}，期望 {expected:g}")
        if zone.get("is_simulated") is not True:
            violations.append(f"{path}({zone.get('zone_id')}).is_simulated={zone.get('is_simulated')!r}，期望 True")
        polygon = _zone_polygon(zone)
        if polygon is None:
            violations.append(f"{path}({zone.get('zone_id')}).polygon_enu 缺失或顶点数 < 3 / 含非数值")
        elif len(polygon) < 4:
            violations.append(f"{path}({zone.get('zone_id')}).polygon_enu 顶点数={len(polygon)}，闭合环应 ≥4")
    _report("C-SCENE-GEO@1", "限制区派生字段与高度带", violations)


def test_obstacles_derived(scene: dict[str, Any]) -> None:
    """C-SCENE-GEO@1：obstacles 20 条、B01–B20 顺序、height_m∈[36,101]、height_source=demo_derived。"""
    obstacles = scene.get("obstacles")
    if not isinstance(obstacles, list):
        _fail(f"C-SCENE-GEO@1 LOWALT_SCENE_DATA.obstacles 缺失或不是数组（实际：{type(obstacles).__name__}）")

    violations: list[str] = []
    expected_ids = [f"B{index:02d}" for index in range(1, 21)]
    obstacle_ids = [
        obstacle.get("obstacle_id") for obstacle in obstacles if isinstance(obstacle, dict)
    ]
    if obstacle_ids != expected_ids:
        violations.append(f"obstacles[*].obstacle_id={obstacle_ids!r}，期望 B01…B20（按文件顺序）")

    for index, obstacle in enumerate(obstacles):
        path = f"obstacles[i={index}]"
        if not isinstance(obstacle, dict):
            violations.append(f"{path} 不是对象（实际：{type(obstacle).__name__}）")
            continue
        obstacle_id = obstacle.get("obstacle_id")
        height = obstacle.get("height_m")
        if not _is_number(height):
            violations.append(f"{path}({obstacle_id}).height_m={height!r}，期望数值")
        elif not (36.0 - EPS <= float(height) <= 101.0 + EPS):
            violations.append(
                f"{path}({obstacle_id}).height_m={_num(height, 2)}，期望落在 [36.0, 101.0]"
            )
        if obstacle.get("height_source") != "demo_derived":
            violations.append(
                f"{path}({obstacle_id}).height_source={obstacle.get('height_source')!r}，"
                "期望 'demo_derived'（源草稿几何无高度字段）"
            )
        if obstacle.get("height_ref") != "agl":
            violations.append(f"{path}({obstacle_id}).height_ref={obstacle.get('height_ref')!r}，期望 'agl'")
        if obstacle.get("kind") != "building":
            violations.append(f"{path}({obstacle_id}).kind={obstacle.get('kind')!r}，期望 'building'")
        if obstacle.get("is_simulated") is not True:
            violations.append(f"{path}({obstacle_id}).is_simulated={obstacle.get('is_simulated')!r}，期望 True")
        area = obstacle.get("footprint_area_m2")
        if not _is_number(area) or float(area) <= 0:
            violations.append(f"{path}({obstacle_id}).footprint_area_m2={area!r}，期望 > 0 的数值")
        if "radius_m" in obstacle:
            violations.append(f"{path}({obstacle_id}) 不应含 radius_m（radius_m 只出现在 sites）")
    _report("C-SCENE-GEO@1", "建筑体块派生字段", violations)


def test_polygons_closed_and_consistent(scene: dict[str, Any]) -> None:
    """C-SCENE-GEO@1：多边形闭合、`polygon_lnglat` 与 `polygon_enu` 顶点数相同/同序/同点。"""
    crs = _crs(scene)
    violations: list[str] = []

    def check_polygon(label: str, zone_or_obstacle: dict[str, Any]) -> None:
        ring_enu = zone_or_obstacle.get("polygon_enu")
        ring_lnglat = zone_or_obstacle.get("polygon_lnglat")
        if not isinstance(ring_enu, list) or not isinstance(ring_lnglat, list):
            violations.append(f"{label}.polygon_enu / polygon_lnglat 缺失或不是数组")
            return
        if len(ring_enu) != len(ring_lnglat):
            violations.append(
                f"{label} 顶点数不一致：polygon_enu={len(ring_enu)}，polygon_lnglat={len(ring_lnglat)}"
            )
            return
        if len(ring_enu) < 4:
            violations.append(f"{label}.polygon_enu 顶点数={len(ring_enu)}，闭合环应 ≥4")
        first_enu, last_enu = ring_enu[0], ring_enu[-1]
        first_lnglat, last_lnglat = ring_lnglat[0], ring_lnglat[-1]
        if not (
            isinstance(first_enu, (list, tuple))
            and isinstance(last_enu, (list, tuple))
            and abs(float(first_enu[0]) - float(last_enu[0])) <= EPS
            and abs(float(first_enu[1]) - float(last_enu[1])) <= EPS
        ):
            violations.append(f"{label}.polygon_enu 首末点不闭合（首 {first_enu!r} / 末 {last_enu!r}）")
        if not (
            isinstance(first_lnglat, (list, tuple))
            and isinstance(last_lnglat, (list, tuple))
            and abs(float(first_lnglat[0]) - float(last_lnglat[0])) <= 1e-9
            and abs(float(first_lnglat[1]) - float(last_lnglat[1])) <= 1e-9
        ):
            violations.append(
                f"{label}.polygon_lnglat 首末点不闭合（首 {first_lnglat!r} / 末 {last_lnglat!r}）"
            )
        for point_index, (enu_point, lnglat_point) in enumerate(zip(ring_enu, ring_lnglat, strict=False)):
            if not (
                isinstance(enu_point, (list, tuple))
                and len(enu_point) >= 2
                and _is_number(enu_point[0])
                and _is_number(enu_point[1])
            ):
                violations.append(f"{label}.polygon_enu[{point_index}]={enu_point!r} 不是 [x_m, y_m]")
                continue
            if not (
                isinstance(lnglat_point, (list, tuple))
                and len(lnglat_point) >= 2
                and _is_number(lnglat_point[0])
                and _is_number(lnglat_point[1])
            ):
                violations.append(
                    f"{label}.polygon_lnglat[{point_index}]={lnglat_point!r} 不是 [lng, lat]"
                )
                continue
            expected_lng, expected_lat = _enu_to_lnglat(
                crs, float(enu_point[0]), float(enu_point[1])
            )
            if (
                abs(float(lnglat_point[0]) - expected_lng) > 1e-9
                or abs(float(lnglat_point[1]) - expected_lat) > 1e-9
            ):
                violations.append(
                    f"{label}.polygon_lnglat[{point_index}]={_num(lnglat_point[0])},{_num(lnglat_point[1])}，"
                    f"按 C-CRS@1 应为 {_num(expected_lng)},{_num(expected_lat)}（点序/坐标不一致）"
                )

    for index, zone in enumerate(scene.get("zones") or []):
        if isinstance(zone, dict):
            check_polygon(f"zones[i={index}]({zone.get('zone_id')})", zone)
    for index, obstacle in enumerate(scene.get("obstacles") or []):
        if isinstance(obstacle, dict):
            check_polygon(f"obstacles[i={index}]({obstacle.get('obstacle_id')})", obstacle)

    _report("C-SCENE-GEO@1", "多边形闭合与经纬度派生一致性", violations)


# --------------------------------------------------------------------------- #
# 组 6：C-SCENE-DATA@1.1 —— 任务
# --------------------------------------------------------------------------- #
def _check_task_fields(scene_data: dict[str, Any]) -> list[str]:
    """C5：任务对象字段集合以 core/models.py 的 Task 为准（缺字段/自造字段都报）。"""
    required, source = _model_field_names(_TaskModel, "Task")
    violations: list[str] = []
    tasks = scene_data.get("tasks")
    if not isinstance(tasks, list):
        return [f"C-SCENE-DATA@1.1 tasks 缺失或不是数组（实际：{type(tasks).__name__}）"]

    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            violations.append(f"tasks[i={index}] 不是对象（实际：{type(task).__name__}）")
            continue
        task_id = task.get("task_id")
        label = f"tasks[{task_id or f'i={index}'}]"
        missing = sorted(field for field in required if field not in task)
        if missing:
            violations.append(
                f"{label} 缺少 Task 字段 {missing}（基准：{source}）；C5 要求字段名逐字对齐 core/models.py"
            )
        for field in sorted(required - {"provenance"}):
            if field in task and task[field] is None:
                violations.append(f"{label}.{field}=None（缺失必须用 null 表达，但 Task 必需字段不可为空）")
        unknown = sorted(
            key
            for key in task
            if key not in required and key not in ALLOWED_EXTRA_TASK_FIELDS and not key.endswith("_lnglat")
        )
        if unknown:
            violations.append(
                f"{label} 出现未授权的自造字段 {unknown}；"
                f"C-SCENE-DATA@1 仅允许 {sorted(ALLOWED_EXTRA_TASK_FIELDS)} 与 *_lnglat"
            )

        for path_key in ("origin", "destination"):
            position = task.get(path_key)
            if not isinstance(position, dict):
                violations.append(f"{label}.{path_key} 缺失或不是对象")
                continue
            if position.get("frame") != "enu_m":
                violations.append(f"{label}.{path_key}.frame={position.get('frame')!r}，期望 'enu_m'")
            if position.get("alt_ref") != "agl":
                violations.append(f"{label}.{path_key}.alt_ref={position.get('alt_ref')!r}，期望 'agl'")
            for axis in ("x_m", "y_m", "alt_m"):
                if not _is_number(position.get(axis)):
                    violations.append(
                        f"{label}.{path_key}.{axis}={position.get(axis)!r}，期望有限数值"
                    )

        provenance = task.get("provenance")
        if not isinstance(provenance, dict):
            violations.append(f"{label}.provenance 缺失或不是对象")
        else:
            for key in ("source", "version", "captured_at", "is_simulated"):
                if key not in provenance:
                    violations.append(f"{label}.provenance 缺少字段 `{key}`")
            if provenance.get("is_simulated") is not True:
                violations.append(
                    f"{label}.provenance.is_simulated={provenance.get('is_simulated')!r}，期望 True"
                )
        if task.get("is_simulated") is not True:
            violations.append(f"{label}.is_simulated={task.get('is_simulated')!r}，期望 True（UI 徽标直接读它）")
        status = task.get("status")
        if status not in {"queued", "in_flight", "infeasible", "delivered", "diverted"}:
            violations.append(
                f"{label}.status={status!r}，期望 queued|in_flight|infeasible|delivered|diverted"
            )
    return violations


def test_tasks_complete(scene: dict[str, Any]) -> None:
    """C-SCENE-DATA@1.1：5 个 task_id 齐全，Task 字段无缺失（基准 core/models.py）。"""
    task_index = _tasks(scene)
    violations: list[str] = []
    if isinstance(scene.get("tasks"), list):
        missing = sorted(task_id for task_id in EXPECTED_TASKS if task_id not in task_index)
        if missing:
            violations.append(f"tasks 缺少必需的 task_id {missing}（实际：{sorted(task_index)}）")
        duplicates = [
            task_id
            for task_id in task_index
            if sum(1 for task in scene["tasks"] if task.get("task_id") == task_id) > 1
        ]
        if duplicates:
            violations.append(f"tasks 中 task_id 重复：{sorted(set(duplicates))}")
    violations.extend(_check_task_fields(scene))
    _report("C-SCENE-DATA@1.1", "任务清单与字段完整性", violations)


def test_tasks_infeasible_status(scene: dict[str, Any]) -> None:
    """C-SCENE-DATA@1.1：T-S4-01 必须为 infeasible，且不得提供候选路线。"""
    task = _tasks(scene).get("T-S4-01")
    violations: list[str] = []
    if task is None:
        violations.append("tasks 中缺少 T-S4-01（不可行任务）")
    elif task.get("status") != "infeasible":
        violations.append(
            f"tasks[T-S4-01].status={task.get('status')!r}，期望 'infeasible'（载荷超出机型能力）"
        )
    routes_for_task = [
        route.get("route_id")
        for route in (scene.get("routes") or [])
        if isinstance(route, dict) and route.get("task_id") == "T-S4-01"
    ]
    if routes_for_task:
        violations.append(f"routes 中不应出现 T-S4-01 的候选路线，实际命中 {routes_for_task}")
    _report("C-SCENE-DATA@1.1", "不可行任务与无候选路线", violations)


def _load_eval_scenarios() -> dict[str, dict[str, Any]]:
    """读取 eval/scenarios/v0.yaml；缺 pyyaml 或解析失败时 skip（C7 允许）。"""
    try:
        import yaml
    except ImportError:
        pytest.skip("SKIP [C7] 未安装 pyyaml：任务数值与 eval/scenarios/v0.yaml 的对齐断言跳过")
    if not EVAL_SCENARIO_YAML.exists():
        pytest.skip(f"SKIP [基线缺失] {_rel(EVAL_SCENARIO_YAML)} 不存在，无法核对任务数值")
    try:
        document = yaml.safe_load(_read_text(EVAL_SCENARIO_YAML))
    except yaml.YAMLError as exc:
        pytest.skip(f"SKIP [基线损坏] {_rel(EVAL_SCENARIO_YAML)} 解析失败：{exc}")
    scenarios = {}
    for scenario in (document or {}).get("scenarios") or []:
        if isinstance(scenario, dict) and isinstance(scenario.get("id"), str):
            scenarios[scenario["id"]] = scenario
    return scenarios


def test_tasks_match_eval_scenarios(scene: dict[str, Any]) -> None:
    """C-SCENE-DATA@1.1：起终点/载荷/时限取自 eval/scenarios/v0.yaml，不得改写。"""
    scenarios = _load_eval_scenarios()
    violations: list[str] = []
    for task_id, scenario_id in EXPECTED_TASKS.items():
        task = _tasks(scene).get(task_id)
        if task is None:
            violations.append(f"tasks 缺少 {task_id}，无法核对场景 {scenario_id}")
            continue
        if task.get("scenario_ref") != scenario_id:
            violations.append(
                f"tasks[{task_id}].scenario_ref={task.get('scenario_ref')!r}，期望 {scenario_id!r}"
            )
        scenario = scenarios.get(scenario_id)
        if scenario is None:
            violations.append(f"eval/scenarios/v0.yaml 中找不到场景 {scenario_id}")
            continue
        for endpoint in ("origin", "destination"):
            expected = scenario.get(endpoint) or {}
            actual = task.get(endpoint) or {}
            for axis in ("x_m", "y_m", "alt_m"):
                expected_value = expected.get(axis)
                actual_value = actual.get(axis)
                if not _is_number(expected_value):
                    violations.append(f"v0.yaml:{scenario_id}.{endpoint}.{axis} 缺失，无法核对")
                    continue
                if not _is_number(actual_value) or abs(
                    float(actual_value) - float(expected_value)
                ) > 1e-6:
                    violations.append(
                        f"tasks[{task_id}].{endpoint}.{axis}={_num(actual_value)}，"
                        f"期望 {_num(expected_value)}（eval/scenarios/v0.yaml:{scenario_id}）"
                    )
        expected_payload = scenario.get("payload_kg")
        actual_payload = task.get("payload_kg")
        if not _is_number(expected_payload):
            violations.append(f"v0.yaml:{scenario_id}.payload_kg 缺失，无法核对")
        elif not _is_number(actual_payload) or abs(float(actual_payload) - float(expected_payload)) > 1e-6:
            violations.append(
                f"tasks[{task_id}].payload_kg={_num(actual_payload)}，"
                f"期望 {_num(expected_payload)}（eval/scenarios/v0.yaml:{scenario_id}）"
            )
        expected_limit = scenario.get("time_limit_s")
        actual_limit = task.get("time_limit_s")
        if not _is_number(expected_limit):
            violations.append(f"v0.yaml:{scenario_id}.time_limit_s 缺失，无法核对")
        elif not _is_number(actual_limit) or abs(float(actual_limit) - float(expected_limit)) > 1e-6:
            violations.append(
                f"tasks[{task_id}].time_limit_s={_num(actual_limit)}，"
                f"期望 {_num(expected_limit)}（eval/scenarios/v0.yaml:{scenario_id}）"
            )
    _report("C-SCENE-DATA@1.1", "任务数值与评测场景对齐", violations)


# --------------------------------------------------------------------------- #
# 组 7：C-SCENE-DATA@1.2 —— 候选路线与几何相交
# --------------------------------------------------------------------------- #
def test_routes_matrix(scene: dict[str, Any]) -> None:
    """C-SCENE-DATA@1.2：5 条必需路线存在，task_id/plan_version/algorithm/diversion_site_id 固定。"""
    routes = scene.get("routes")
    if not isinstance(routes, list):
        _fail(f"C-SCENE-DATA@1.2 LOWALT_SCENE_DATA.routes 缺失或不是数组（实际：{type(routes).__name__}）")

    violations: list[str] = []
    route_index = _index_by(routes, "route_id")
    for route_id, expected in EXPECTED_ROUTES.items():
        route = route_index.get(route_id)
        if route is None:
            violations.append(f"routes 缺少必需路线 {route_id}")
            continue
        for field, expected_value in expected.items():
            actual_value = route.get(field)
            if actual_value != expected_value:
                violations.append(
                    f"routes[{route_id}].{field}={actual_value!r}，期望 {expected_value!r}"
                )
    _report("C-SCENE-DATA@1.2", "必需候选路线与固定元数据", violations)


def test_routes_fields_complete(scene: dict[str, Any]) -> None:
    """C5：路线对象字段集合以 core/models.py 的 RoutePlan 为准；waypoints 至少 2 点。"""
    required_fields, source = _model_field_names(_RouteModel, "RoutePlan")
    violations: list[str] = []
    for index, route in enumerate(scene.get("routes") or []):
        if not isinstance(route, dict):
            violations.append(f"routes[i={index}] 不是对象（实际：{type(route).__name__}）")
            continue
        route_id = route.get("route_id")
        label = f"routes[{route_id or f'i={index}'}]"
        missing = sorted(field for field in required_fields if field not in route)
        if missing:
            violations.append(
                f"{label} 缺少 RoutePlan 字段 {missing}（基准：{source}）"
            )
        unknown = sorted(
            key
            for key in route
            if key not in required_fields
            and key not in ALLOWED_EXTRA_ROUTE_FIELDS
            and not key.endswith("_lnglat")
        )
        if unknown:
            violations.append(
                f"{label} 出现未授权的自造字段 {unknown}；"
                f"C-SCENE-DATA@1 仅允许 {sorted(ALLOWED_EXTRA_ROUTE_FIELDS)}"
            )

        waypoints = route.get("waypoints")
        if not isinstance(waypoints, list) or len(waypoints) < 2:
            violations.append(f"{label}.waypoints 长度={len(waypoints) if isinstance(waypoints, list) else waypoints!r}，期望 ≥2")
        else:
            for waypoint_index, waypoint in enumerate(waypoints):
                point_path = f"{label}.waypoints[{waypoint_index}]"
                if not isinstance(waypoint, dict):
                    violations.append(f"{point_path} 不是对象")
                    continue
                if waypoint.get("frame") != "enu_m":
                    violations.append(f"{point_path}.frame={waypoint.get('frame')!r}，期望 'enu_m'")
                if waypoint.get("alt_ref") != "agl":
                    violations.append(f"{point_path}.alt_ref={waypoint.get('alt_ref')!r}，期望 'agl'")
                alt = waypoint.get("alt_m")
                if not _is_number(alt):
                    violations.append(f"{point_path}.alt_m={alt!r}，期望有限数值")
                elif not (30.0 - EPS <= float(alt) <= 45.0 + EPS):
                    violations.append(f"{point_path}.alt_m={_num(alt, 1)}，期望落在 30–45 m（C-SCENE-DATA@1.2）")
                for axis in ("x_m", "y_m"):
                    if not _is_number(waypoint.get(axis)):
                        violations.append(f"{point_path}.{axis}={waypoint.get(axis)!r}，期望有限数值")

        checks = route.get("checks")
        if not isinstance(checks, list):
            violations.append(f"{label}.checks 缺失或不是数组")
        else:
            for check_index, check in enumerate(checks):
                if not isinstance(check, dict):
                    violations.append(f"{label}.checks[{check_index}] 不是对象")
                    continue
                for key in ("name", "passed", "detail"):
                    if key not in check:
                        violations.append(f"{label}.checks[{check_index}] 缺少字段 `{key}`")
                if "passed" in check and not isinstance(check["passed"], bool):
                    violations.append(
                        f"{label}.checks[{check_index}].passed={check['passed']!r}，期望布尔值"
                    )

        if route.get("is_simulated") is not True:
            violations.append(f"{label}.is_simulated={route.get('is_simulated')!r}，期望 True")
    _report("C-SCENE-DATA@1.2", "路线字段完整性", violations)


def test_routes_endpoints_match_tasks(scene: dict[str, Any]) -> None:
    """C-SCENE-DATA@1.2：每条路线起点=任务 origin、终点=任务 destination。"""
    tasks = _tasks(scene)
    violations: list[str] = []
    for route_id, route in _routes(scene).items():
        task = tasks.get(route.get("task_id"))
        if task is None:
            violations.append(
                f"routes[{route_id}].task_id={route.get('task_id')!r} 找不到对应任务"
            )
            continue
        points = _route_points(route)
        if len(points) < 2:
            violations.append(f"routes[{route_id}].waypoints 无法解析出 ≥2 个 ENU 点")
            continue
        for endpoint, point, position_key in (
            ("起点", points[0], "origin"),
            ("终点", points[-1], "destination"),
        ):
            target = task.get(position_key) or {}
            for axis_index, axis in enumerate(("x_m", "y_m")):
                expected = target.get(axis)
                actual = point[axis_index]
                if not _is_number(expected):
                    violations.append(f"tasks[{route.get('task_id')}].{position_key}.{axis} 缺失")
                    continue
                if abs(actual - float(expected)) > 1e-6:
                    violations.append(
                        f"routes[{route_id}] {endpoint} {axis}={_num(actual)}，"
                        f"期望 {_num(expected)}（= tasks[{route.get('task_id')}].{position_key}.{axis}）"
                    )
    _report("C-SCENE-DATA@1.2", "路线起终点与任务端点一致", violations)


def _check_route_zone(
    scene_data: dict[str, Any], route_id: str, zone_id: str, expect_hit: bool
) -> list[str]:
    """对单条路线与单个限制区做相交判定，返回违例描述。"""
    route = _routes(scene_data).get(route_id)
    zone = _zones(scene_data).get(zone_id)
    if route is None:
        return [f"缺少必需路线 {route_id}，无法判定与 {zone_id} 的相交关系"]
    if zone is None:
        return [f"缺少限制区 {zone_id}，无法判定与 {route_id} 的相交关系"]
    polygon = _zone_polygon(zone)
    if polygon is None:
        return [f"zones[{zone_id}].polygon_enu 不可用（缺失/顶点数不足/含非数值），无法判定相交"]
    points = _route_points(route)
    if len(points) < 2:
        return [f"routes[{route_id}].waypoints 不可用（少于 2 个 ENU 点），无法判定相交"]
    hit = polyline_hits_polygon(points, polygon)
    if hit != expect_hit:
        expectation = "相交" if expect_hit else "不相交"
        return [
            f"routes[{route_id}] 与 zones[{zone_id}] 的相交判定={hit}，"
            f"按 C-SCENE-DATA@1.2 几何硬约束期望{expectation}（射线法/线段相交）"
        ]
    return []


def test_route_old_route_crosses_r01(scene: dict[str, Any]) -> None:
    """C4：RT-S2-01-A 折线必须穿越 R01 多边形（相交判定为 True）。"""
    violations = _check_route_zone(scene, "RT-S2-01-A", "R01", expect_hit=True)
    _report("C-SCENE-DATA@1.2", "旧线穿越 R01", violations)


def test_route_new_route_avoids_all_zones(scene: dict[str, Any]) -> None:
    """C4：RT-S2-01-B 与 R01–R04 全部不相交（相交判定均为 False）。"""
    violations: list[str] = []
    for zone_id in ("R01", "R02", "R03", "R04"):
        violations.extend(_check_route_zone(scene, "RT-S2-01-B", zone_id, expect_hit=False))
    _report("C-SCENE-DATA@1.2", "新线避开全部限制区", violations)


def test_routes_other_geometry_constraints(scene: dict[str, Any]) -> None:
    """C-SCENE-DATA@1.2 其余几何硬约束：S1-01 全避开、S2-04-A 避开 R01、S3-03-A 与 R03 交叉。"""
    violations: list[str] = []
    for zone_id in ("R01", "R02", "R03", "R04"):
        violations.extend(_check_route_zone(scene, "RT-S1-01-A", zone_id, expect_hit=False))
    violations.extend(_check_route_zone(scene, "RT-S2-04-A", "R01", expect_hit=False))
    violations.extend(_check_route_zone(scene, "RT-S3-03-A", "R03", expect_hit=True))
    _report("C-SCENE-DATA@1.2", "其余路线几何硬约束", violations)


# --------------------------------------------------------------------------- #
# 组 8：C-SCENE-DATA@1.3 + C-MARGIN-INVARIANT@1 —— 剖面 I1–I7
# --------------------------------------------------------------------------- #
def _samples(profile: dict[str, Any]) -> list[dict[str, Any]]:
    samples = profile.get("samples")
    if not isinstance(samples, list):
        return []
    return [sample for sample in samples if isinstance(sample, dict)]


def _check_profile_presence(scene_data: dict[str, Any]) -> list[str]:
    profiles = scene_data.get("margin_profiles")
    if not isinstance(profiles, list):
        return [f"C-SCENE-DATA@1.3 margin_profiles 缺失或不是数组（实际：{type(profiles).__name__}）"]
    violations: list[str] = []
    index = _index_by(profiles, "route_id")
    for route_id in PROFILE_ROUTE_IDS:
        profile = index.get(route_id)
        if profile is None:
            violations.append(f"margin_profiles 缺少必需剖面 {route_id}")
        elif not _samples(profile):
            violations.append(f"margin_profiles[{route_id}].samples 为空或不是数组")
    return violations


def _check_profile_fields(scene_data: dict[str, Any]) -> list[str]:
    """C5：剖面与采样点字段集合以 DiversionMarginProfile / DiversionMarginSample 为准。"""
    profile_fields, source = _model_field_names(_ProfileModel, "DiversionMarginProfile")
    sample_fields, sample_source = _model_field_names(_SampleModel, "DiversionMarginSample")
    violations: list[str] = []
    for route_id, profile in _profiles(scene_data).items():
        label = f"margin_profiles[{route_id}]"
        missing = sorted(field for field in profile_fields if field not in profile)
        if missing:
            violations.append(f"{label} 缺少 DiversionMarginProfile 字段 {missing}（基准：{source}）")
        unknown = sorted(
            key
            for key in profile
            if key not in profile_fields and key not in ALLOWED_EXTRA_PROFILE_FIELDS
        )
        if unknown:
            violations.append(
                f"{label} 出现未授权的自造字段 {unknown}；"
                f"C-SCENE-DATA@1 仅允许 {sorted(ALLOWED_EXTRA_PROFILE_FIELDS)}"
            )
        if profile.get("is_simulated") is not True:
            violations.append(f"{label}.is_simulated={profile.get('is_simulated')!r}，期望 True")

        for sample_index, sample in enumerate(_samples(profile)):
            sample_path = f"{label}.samples[{sample_index}]"
            sample_missing = sorted(
                field
                for field in sample_fields
                if field not in sample and field not in OPTIONAL_SAMPLE_FIELDS
            )
            if sample_missing:
                violations.append(
                    f"{sample_path}(s_m={_num(sample.get('s_m'))}) 缺少 DiversionMarginSample 字段 "
                    f"{sample_missing}（基准：{sample_source}）"
                )
            sample_unknown = sorted(
                key
                for key in sample
                if key not in sample_fields and key not in ALLOWED_EXTRA_SAMPLE_FIELDS
            )
            if sample_unknown:
                violations.append(
                    f"{sample_path}(s_m={_num(sample.get('s_m'))}) 出现未授权的自造字段 {sample_unknown}；"
                    f"C-SCENE-DATA@1 仅允许 {sorted(ALLOWED_EXTRA_SAMPLE_FIELDS)}"
                )
    return violations


def _check_step_limit(scene_data: dict[str, Any]) -> list[str]:
    """C-SCENE-DATA@1.3：相邻采样步长 ≤ 20 m。"""
    violations: list[str] = []
    for route_id, profile in _profiles(scene_data).items():
        samples = _samples(profile)
        previous_s_m: float | None = None
        for sample_index, sample in enumerate(samples):
            s_m = sample.get("s_m")
            if not _is_number(s_m):
                violations.append(
                    f"margin_profiles[{route_id}].samples[{sample_index}].s_m={s_m!r}，期望有限数值"
                )
                previous_s_m = None
                continue
            s_m_value = float(s_m)
            if previous_s_m is not None and s_m_value - previous_s_m > SAMPLE_STEP_MAX_M + 1e-6:
                violations.append(
                    f"margin_profiles[{route_id}] s_m={_num(s_m_value, 1)} 与前一点 "
                    f"{_num(previous_s_m, 1)} 的步长={_num(s_m_value - previous_s_m, 1)} m，期望 ≤ 20 m"
                )
            previous_s_m = s_m_value
    return violations


def _check_i1(scene_data: dict[str, Any]) -> list[str]:
    """I1：RT-S2-01-A 至少 5 个负值采样，且 min(margin_wh) ≤ −1.5。"""
    profile = _profiles(scene_data).get("RT-S2-01-A")
    if profile is None:
        return ["I1 缺少剖面 RT-S2-01-A，无法判定（C-SCENE-DATA@1.3）"]
    samples = _samples(profile)
    margins = [
        float(sample["margin_wh"]) for sample in samples if _is_number(sample.get("margin_wh"))
    ]
    violations: list[str] = []
    if len(margins) != len(samples):
        violations.append(
            f"I1 RT-S2-01-A 有 {len(samples) - len(margins)} 个采样点的 margin_wh 不是有限数值"
        )
    negative = [value for value in margins if value < 0]
    if len(negative) < 5:
        violations.append(
            f"I1 RT-S2-01-A 负值采样点数量={len(negative)}，期望 ≥ 5（体现旧线不可行）"
        )
    if margins and min(margins) > -1.5:
        violations.append(
            f"I1 RT-S2-01-A min(margin_wh)={_num(min(margins), 3)}，期望 ≤ −1.500"
        )
    return violations


def _check_i2(scene_data: dict[str, Any]) -> list[str]:
    """I2：RT-S2-01-B 全部 margin_wh ≥ +1.0。"""
    profile = _profiles(scene_data).get("RT-S2-01-B")
    if profile is None:
        return ["I2 缺少剖面 RT-S2-01-B，无法判定（C-SCENE-DATA@1.3）"]
    violations: list[str] = []
    for sample_index, sample in enumerate(_samples(profile)):
        margin = sample.get("margin_wh")
        s_m = sample.get("s_m")
        if not _is_number(margin):
            violations.append(
                f"I2 RT-S2-01-B samples[{sample_index}](s_m={_num(s_m, 1)}) margin_wh={margin!r} 不是有限数值"
            )
        elif float(margin) < 1.0 - EPS:
            violations.append(
                f"I2 RT-S2-01-B s_m={_num(s_m, 1)} margin_wh={_num(margin, 3)}，期望 ≥ +1.000"
            )
    return violations


def _check_i3(scene_data: dict[str, Any]) -> list[str]:
    """I3：s_m 严格递增、首点 0、末点≈路线总长(±0.5)；t_s 非递减。"""
    violations: list[str] = []
    routes = _routes(scene_data)
    for route_id, profile in _profiles(scene_data).items():
        samples = _samples(profile)
        if not samples:
            violations.append(f"I3 margin_profiles[{route_id}].samples 为空，无法判定")
            continue

        first_s_m = samples[0].get("s_m")
        if not _is_number(first_s_m) or abs(float(first_s_m)) > EPS:
            violations.append(
                f"I3 margin_profiles[{route_id}] 首点 s_m={_num(first_s_m, 3)}，期望 0"
            )

        previous_s_m: float | None = None
        previous_t_s: float | None = None
        for sample_index, sample in enumerate(samples):
            s_m = sample.get("s_m")
            if not _is_number(s_m):
                violations.append(
                    f"I3 margin_profiles[{route_id}].samples[{sample_index}].s_m={s_m!r}，期望有限数值"
                )
                previous_s_m = None
                continue
            s_m_value = float(s_m)
            if previous_s_m is not None and s_m_value <= previous_s_m:
                violations.append(
                    f"I3 margin_profiles[{route_id}] samples[{sample_index}].s_m={_num(s_m_value, 3)} "
                    f"未严格大于前一点 {_num(previous_s_m, 3)}"
                )
            previous_s_m = s_m_value

            t_s = sample.get("t_s")
            if not _is_number(t_s):
                violations.append(
                    f"I3 margin_profiles[{route_id}].samples[{sample_index}].t_s={t_s!r}，期望有限数值"
                )
                continue
            if previous_t_s is not None and float(t_s) < previous_t_s - EPS:
                violations.append(
                    f"I3 margin_profiles[{route_id}] samples[{sample_index}].t_s={_num(t_s, 3)} "
                    f"小于前一点 {_num(previous_t_s, 3)}（t_s 必须非递减）"
                )
            previous_t_s = float(t_s)

        route = routes.get(route_id)
        if route is None:
            violations.append(f"I3 routes 中缺少 {route_id}，无法核对剖面末点与路线总长")
            continue
        points = _route_points(route)
        if len(points) < 2:
            violations.append(f"I3 routes[{route_id}].waypoints 无法解析，无法核对路线总长")
            continue
        total_length = polyline_length(points)
        last_s_m = samples[-1].get("s_m")
        if not _is_number(last_s_m):
            violations.append(f"I3 margin_profiles[{route_id}] 末点 s_m={last_s_m!r}，期望数值")
        elif abs(float(last_s_m) - total_length) > 0.5:
            violations.append(
                f"I3 margin_profiles[{route_id}] 末点 s_m={_num(last_s_m, 1)}，"
                f"路线总长={_num(total_length, 1)}，偏差={_num(abs(float(last_s_m) - total_length), 2)} m > 0.5"
            )
    return violations


def _check_i4(scene_data: dict[str, Any]) -> list[str]:
    """I4：profile.reserve_wh === 对应 Task.reserve_energy_wh。"""
    tasks = _tasks(scene_data)
    violations: list[str] = []
    for route_id, profile in _profiles(scene_data).items():
        task_id = profile.get("task_id")
        task = tasks.get(task_id)
        if task is None:
            violations.append(
                f"I4 margin_profiles[{route_id}].task_id={task_id!r} 找不到对应任务，无法核对 reserve_wh"
            )
            continue
        expected = task.get("reserve_energy_wh")
        actual = profile.get("reserve_wh")
        if not _is_number(expected):
            violations.append(f"I4 tasks[{task_id}].reserve_energy_wh={expected!r}，期望有限数值")
        elif not _is_number(actual) or abs(float(actual) - float(expected)) > EPS:
            violations.append(
                f"I4 margin_profiles[{route_id}].reserve_wh={_num(actual, 3)}，"
                f"期望 = tasks[{task_id}].reserve_energy_wh={_num(expected, 3)}"
            )
    return violations


def _check_i5(scene_data: dict[str, Any]) -> list[str]:
    """I5：RT-S2-01-A 负值区间的 nearest_site_id 必须为 "L2"，不得为 null。"""
    profile = _profiles(scene_data).get("RT-S2-01-A")
    if profile is None:
        return ["I5 缺少剖面 RT-S2-01-A，无法判定（C-SCENE-DATA@1.3）"]
    violations: list[str] = []
    negative_samples = 0
    for sample_index, sample in enumerate(_samples(profile)):
        margin = sample.get("margin_wh")
        if not _is_number(margin) or float(margin) >= 0:
            continue
        negative_samples += 1
        nearest = sample.get("nearest_site_id")
        if nearest != "L2":
            violations.append(
                f"I5 RT-S2-01-A samples[{sample_index}] s_m={_num(sample.get('s_m'), 1)} "
                f"margin_wh={_num(margin, 3)} nearest_site_id={nearest!r}，期望 'L2'"
            )
    if negative_samples == 0:
        violations.append("I5 RT-S2-01-A 没有负值采样点，与 I1 前提冲突（无法验证中段唯一备降点不足）")
    return violations


def _check_i6(scene_data: dict[str, Any]) -> list[str]:
    """I6：|e_left_wh − reserve_wh − e_need_wh − margin_wh| ≤ 0.05。"""
    violations: list[str] = []
    for route_id, profile in _profiles(scene_data).items():
        reserve = profile.get("reserve_wh")
        if not _is_number(reserve):
            violations.append(f"I6 margin_profiles[{route_id}].reserve_wh={reserve!r}，期望有限数值")
            continue
        for sample_index, sample in enumerate(_samples(profile)):
            s_m = sample.get("s_m")
            e_left = sample.get("e_left_wh")
            e_need = sample.get("e_need_wh")
            margin = sample.get("margin_wh")
            missing = [
                name
                for name, value in (("e_left_wh", e_left), ("e_need_wh", e_need), ("margin_wh", margin))
                if not _is_number(value)
            ]
            if missing:
                violations.append(
                    f"I6 margin_profiles[{route_id}].samples[{sample_index}](s_m={_num(s_m, 1)}) "
                    f"字段 {missing} 缺失或不是有限数值，无法复算"
                )
                continue
            recomputed = float(e_left) - float(reserve) - float(e_need)
            deviation = abs(recomputed - float(margin))
            if deviation > MARGIN_IDENTITY_TOL_WH:
                violations.append(
                    f"I6 margin_profiles[{route_id}] s_m={_num(s_m, 1)} "
                    f"e_left={_num(e_left, 3)} − reserve={_num(reserve, 3)} − e_need={_num(e_need, 3)} "
                    f"= {_num(recomputed, 3)}，与 margin_wh={_num(margin, 3)} 相差 "
                    f"{_num(deviation, 3)} > {MARGIN_IDENTITY_TOL_WH}"
                )
    return violations


def _check_i7(scene_data: dict[str, Any]) -> list[str]:
    """I7：所有 margin_wh 为有限数（禁 NaN/Infinity/null），且 |margin_wh| ≤ 500。"""
    violations: list[str] = []
    for route_id, profile in _profiles(scene_data).items():
        for sample_index, sample in enumerate(_samples(profile)):
            s_m = sample.get("s_m")
            margin = sample.get("margin_wh")
            if not _is_number(margin):
                violations.append(
                    f"I7 margin_profiles[{route_id}].samples[{sample_index}](s_m={_num(s_m, 1)}) "
                    f"margin_wh={margin!r} 不是有限数值（禁止 NaN/Infinity/null）"
                )
            elif abs(float(margin)) > MARGIN_ABS_LIMIT_WH:
                violations.append(
                    f"I7 margin_profiles[{route_id}] s_m={_num(s_m, 1)} "
                    f"margin_wh={_num(margin, 3)}，|margin_wh| 超过 {_num(MARGIN_ABS_LIMIT_WH, 1)}"
                )
    return violations


def test_profile_presence(scene: dict[str, Any]) -> None:
    """C-SCENE-DATA@1.3：4 条必需剖面存在且有采样点。"""
    _report("C-SCENE-DATA@1.3", "必需剖面存在性", _check_profile_presence(scene))


def test_profile_fields_complete(scene: dict[str, Any]) -> None:
    """C5：剖面/采样点字段集合对齐 core/models.py，且无未授权自造字段。"""
    _report("C-SCENE-DATA@1.3", "剖面字段完整性", _check_profile_fields(scene))


def test_profile_step_limit(scene: dict[str, Any]) -> None:
    """C-SCENE-DATA@1.3：采样步长 ≤ 20 m。"""
    _report("C-SCENE-DATA@1.3", "采样步长", _check_step_limit(scene))


def test_margin_i1_old_route_negative(scene: dict[str, Any]) -> None:
    """C-MARGIN-INVARIANT@1 I1。"""
    _report("C-MARGIN-INVARIANT@1", "I1 旧线负值区", _check_i1(scene))


def test_margin_i2_new_route_non_negative(scene: dict[str, Any]) -> None:
    """C-MARGIN-INVARIANT@1 I2。"""
    _report("C-MARGIN-INVARIANT@1", "I2 新线全程非负", _check_i2(scene))


def test_margin_i3_sampling(scene: dict[str, Any]) -> None:
    """C-MARGIN-INVARIANT@1 I3。"""
    _report("C-MARGIN-INVARIANT@1", "I3 采样序列与路线总长", _check_i3(scene))


def test_margin_i4_reserve_matches_task(scene: dict[str, Any]) -> None:
    """C-MARGIN-INVARIANT@1 I4。"""
    _report("C-MARGIN-INVARIANT@1", "I4 reserve_wh 与任务一致", _check_i4(scene))


def test_margin_i5_old_route_nearest_site(scene: dict[str, Any]) -> None:
    """C-MARGIN-INVARIANT@1 I5。"""
    _report("C-MARGIN-INVARIANT@1", "I5 旧线负值区最近备降点为 L2", _check_i5(scene))


def test_margin_i6_identity(scene: dict[str, Any]) -> None:
    """C-MARGIN-INVARIANT@1 I6（浮点容差 0.05 Wh）。"""
    _report("C-MARGIN-INVARIANT@1", "I6 margin 复算恒等式", _check_i6(scene))


def test_margin_i7_finite(scene: dict[str, Any]) -> None:
    """C-MARGIN-INVARIANT@1 I7（有限性与量级上限）。"""
    _report("C-MARGIN-INVARIANT@1", "I7 margin 有限性", _check_i7(scene))


# --------------------------------------------------------------------------- #
# 组 9：C-SCENE-DATA@1.4 —— 事件时间线
# --------------------------------------------------------------------------- #
def _events(scene_data: dict[str, Any]) -> list[dict[str, Any]]:
    events = scene_data.get("events")
    if not isinstance(events, list):
        return []
    return [event for event in events if isinstance(event, dict)]


def _check_event_kinds(scene_data: dict[str, Any]) -> list[str]:
    raw_events = scene_data.get("events")
    if not isinstance(raw_events, list):
        return [f"C-SCENE-DATA@1.4 events 缺失或不是数组（实际：{type(raw_events).__name__}）"]
    violations: list[str] = []
    events = _events(scene_data)
    allowed = set(RISK_EVENT_KINDS) | {PLAN_VERSION_CHANGE_KIND}
    kind_counts: dict[str, int] = {}
    for index, event in enumerate(events):
        kind = event.get("kind")
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        if kind not in allowed:
            violations.append(
                f"events[i={index}](event_id={event.get('event_id')!r}).kind={kind!r}，"
                f"期望 ∈ {sorted(allowed)}（RiskEvent 只允许五值，plan_version_change 是展示层条目类型）"
            )
    for kind in RISK_EVENT_KINDS:
        if kind_counts.get(kind, 0) < 1:
            violations.append(f"events 中 kind={kind!r} 的条目数量=0，期望 ≥1（五值各 ≥1 条）")
    if len(events) < 6:
        violations.append(f"events 时间线条目总数={len(events)}，期望 ≥ 6（五值 + plan_version_change）")
    return violations


def _check_event_shapes(scene_data: dict[str, Any]) -> list[str]:
    """RiskEvent 条目必须具备 models.py 的必需字段；plan_version_change 条目豁免。"""
    violations: list[str] = []
    for index, event in enumerate(_events(scene_data)):
        kind = event.get("kind")
        event_id = event.get("event_id")
        label = f"events[{event_id or f'i={index}'}]"
        if not isinstance(event_id, str) or not event_id:
            violations.append(f"events[i={index}].event_id={event_id!r}，期望非空字符串")
        if kind == PLAN_VERSION_CHANGE_KIND:
            for key in ("from_version", "to_version", "at_s"):
                if key not in event:
                    violations.append(f"{label}（plan_version_change）缺少字段 `{key}`")
            continue
        geometry = event.get("geometry")
        if not isinstance(geometry, dict):
            violations.append(
                f"{label}.geometry={geometry!r}，期望 GeoJSON geometry 对象"
                "（models.py 的 RiskEvent.geometry 默认 {}）"
            )
        elif kind in {"restriction_zone", "landing_site_change"}:
            # 空间型事件必须给出可渲染几何；非空间事件（wind/link/battery）允许 {}。
            if not geometry.get("type"):
                violations.append(f"{label}.geometry 缺少 `type`（kind={kind!r} 为空间型事件）")
            if "coordinates" not in geometry:
                violations.append(f"{label}.geometry 缺少 `coordinates`（kind={kind!r} 为空间型事件）")
        alt_min = event.get("alt_min_m")
        alt_max = event.get("alt_max_m")
        if alt_min is not None and not _is_number(alt_min):
            violations.append(f"{label}.alt_min_m={alt_min!r}，期望数值或 null")
        if alt_max is not None and not _is_number(alt_max):
            violations.append(f"{label}.alt_max_m={alt_max!r}，期望数值或 null")
        if _is_number(alt_min) and _is_number(alt_max) and float(alt_min) > float(alt_max):
            violations.append(
                f"{label}.alt_min_m={_num(alt_min)} > alt_max_m={_num(alt_max)}（高度带自相矛盾）"
            )
        provenance = event.get("provenance")
        if not isinstance(provenance, dict):
            violations.append(f"{label}.provenance 缺失或不是对象（RiskEvent 必需）")
        else:
            for key in ("source", "version", "captured_at", "is_simulated"):
                if key not in provenance:
                    violations.append(f"{label}.provenance 缺少字段 `{key}`")
            if provenance.get("is_simulated") is not True:
                violations.append(
                    f"{label}.provenance.is_simulated={provenance.get('is_simulated')!r}，期望 True"
                )
    return violations


def _check_event_effective_from(scene_data: dict[str, Any]) -> list[str]:
    """`effective_from` 必须等于基准时刻 + `at_s`（容差 ±1 s）。"""
    violations: list[str] = []
    for index, event in enumerate(_events(scene_data)):
        event_id = event.get("event_id")
        label = f"events[{event_id or f'i={index}'}]"
        at_s = event.get("at_s")
        if not _is_number(at_s):
            violations.append(f"{label}.at_s={at_s!r}，期望有限数值（相对任务开始秒数）")
            continue
        if float(at_s) < 0:
            violations.append(f"{label}.at_s={_num(at_s)}，期望 ≥ 0")
        effective_from = event.get("effective_from")
        if not isinstance(effective_from, str):
            violations.append(f"{label}.effective_from={effective_from!r}，期望 ISO8601 UTC 字符串")
            continue
        try:
            parsed = _parse_iso_utc(effective_from)
        except ValueError:
            violations.append(f"{label}.effective_from={effective_from!r}，无法解析为 ISO8601")
            continue
        expected = BASE_TIME + timedelta(seconds=float(at_s))
        deviation = abs((parsed - expected).total_seconds())
        if deviation > 1.0:
            violations.append(
                f"{label}.effective_from={effective_from}，按 at_s={_num(at_s)} 应为 "
                f"{expected.isoformat().replace('+00:00', 'Z')}，相差 {_num(deviation, 1)} s > 1 s"
            )
        effective_until = event.get("effective_until")
        if isinstance(effective_until, str):
            try:
                until = _parse_iso_utc(effective_until)
            except ValueError:
                violations.append(f"{label}.effective_until={effective_until!r}，无法解析为 ISO8601")
                continue
            if until < parsed:
                violations.append(
                    f"{label}.effective_until={effective_until} 早于 effective_from={effective_from}"
                )
    return violations


def _check_plan_version_change(scene_data: dict[str, Any]) -> list[str]:
    """必须存在 T-S2-01 的 v1 → v2 版本变更条目。"""
    violations: list[str] = []
    changes = [
        event for event in _events(scene_data) if event.get("kind") == PLAN_VERSION_CHANGE_KIND
    ]
    if not changes:
        return ["events 中缺少 kind='plan_version_change' 的版本变更条目（C-SCENE-DATA@1.4）"]
    target = [
        event
        for event in changes
        if event.get("task_id") == "T-S2-01"
        and event.get("from_version") == "v1"
        and event.get("to_version") == "v2"
    ]
    if not target:
        violations.append(
            "events 中缺少 T-S2-01 的 v1 → v2 版本变更条目（实际条目："
            + ", ".join(
                f"{event.get('task_id')}:{event.get('from_version')}→{event.get('to_version')}"
                for event in changes
            )
            + "）"
        )
    return violations


def test_events_kinds_and_timeline_size(scene: dict[str, Any]) -> None:
    """C-SCENE-DATA@1.4：五值 kind 各 ≥1；kind 不越界；时间线条目 ≥6。"""
    _report("C-SCENE-DATA@1.4", "事件 kind 覆盖与时间线规模", _check_event_kinds(scene))


def test_events_risk_event_shape(scene: dict[str, Any]) -> None:
    """C-SCENE-DATA@1.4：RiskEvent 条目字段齐全（geometry/alt 带/provenance）。"""
    _report("C-SCENE-DATA@1.4", "RiskEvent 形状", _check_event_shapes(scene))


def test_events_effective_from_matches_at_s(scene: dict[str, Any]) -> None:
    """C-SCENE-DATA@1.4：effective_from 可由 at_s 与基准时刻推算一致（±1 s）。"""
    _report("C-SCENE-DATA@1.4", "生效时刻与 at_s 一致", _check_event_effective_from(scene))


def test_events_plan_version_change(scene: dict[str, Any]) -> None:
    """C-SCENE-DATA@1.4：必须含 T-S2-01 的 v1 → v2 版本变更条目。"""
    _report("C-SCENE-DATA@1.4", "计划版本变更条目", _check_plan_version_change(scene))


# --------------------------------------------------------------------------- #
# 组 10：C-COPY@1 —— 表述红线（文件级禁用词扫描）
# --------------------------------------------------------------------------- #
# 扫描范围：apps/web/** 的文本文件。
# 排除 node_modules / dist / .vite / __pycache__：这些是第三方依赖或构建产物，
# 不是本特性的交付文案；其 license 文本里天然可能出现 "forked from" 等字样，
# 纳入扫描只会制造误报，且与 C8（单文件 <10 s）冲突。
SCAN_EXCLUDED_DIRS = {"node_modules", "dist", ".vite", "__pycache__", ".git"}
SCAN_EXCLUDED_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svgz", ".bmp",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp4", ".webm", ".mp3", ".wav", ".zip", ".gz", ".glb", ".gltf", ".wasm", ".bin",
}


def iter_web_text_files() -> list[tuple[Path, str]]:
    """枚举 apps/web 下参与红线扫描的文本文件（二进制与第三方目录跳过）。"""
    if not WEB_DIR.exists():
        return []
    collected: list[tuple[Path, str]] = []
    for path in sorted(WEB_DIR.rglob("*")):
        if not path.is_file():
            continue
        try:
            relative_parts = path.relative_to(WEB_DIR).parts
        except ValueError:  # pragma: no cover - rglob 不会产生越界路径
            continue
        if any(part in SCAN_EXCLUDED_DIRS for part in relative_parts):
            continue
        if path.suffix.lower() in SCAN_EXCLUDED_SUFFIXES:
            continue
        try:
            raw = path.read_bytes()
        except OSError:  # pragma: no cover - 权限/锁文件属环境问题
            continue
        if b"\x00" in raw[:4096]:
            continue
        collected.append((path, raw.decode("utf-8", errors="replace")))
    return collected


# 「整词/整短语」护栏：短串 `实飞` 会命中「真实飞控遥测」「实测飞行」这类合法复合词，
# 而这些合法复合词本身不是红线（红线是"把仿真称作实飞"）。因此按前一个字做排除：
# 命中「真实飞…」「实测飞…」时不报，交由更长的短语规则（真实飞行/实测飞行）单独判定。
PHRASE_EXCLUDED_PRECEDING_CHARS = {
    "实飞": ("真", "测"),
}


def scan_forbidden_phrases(files: Sequence[tuple[Path, str]]) -> list[str]:
    """整词/整短语、不区分大小写地扫描禁用串，返回 `文件:行 命中...` 描述。"""
    hits: list[str] = []
    for path, text in files:
        lowered = text.lower()
        lines = text.splitlines()
        for phrase, reason in FORBIDDEN_PHRASES:
            needle = phrase.lower()
            excluded_previous = PHRASE_EXCLUDED_PRECEDING_CHARS.get(phrase, ())
            cursor = 0
            while True:
                index = lowered.find(needle, cursor)
                if index < 0:
                    break
                cursor = index + len(needle)
                if index > 0 and text[index - 1] in excluded_previous:
                    continue
                line_no = text.count("\n", 0, index) + 1
                line = lines[line_no - 1].strip() if line_no - 1 < len(lines) else ""
                hits.append(
                    f"{_rel(path)}:{line_no} 命中禁用串「{phrase}」（{reason}）；"
                    f"所在行：{line[:120]!r}"
                )
    return hits


def test_copy_forbidden_phrases() -> None:
    """C-COPY@1：apps/web/** 全部文本文件禁用词零命中（页脚合法引用不得误报）。"""
    files = iter_web_text_files()
    if not files:
        pytest.skip("SKIP [待联调] apps/web 下没有可扫描的文本文件")
    hits = scan_forbidden_phrases(files)
    _report("C-COPY@1", f"禁用词扫描（{len(files)} 个文本文件）", hits)


def test_copy_required_statements(html: str) -> None:
    """C-COPY@1：页头仿真标注 / 无实机飞行 / 页脚版权来源在 index.html 中必须出现。"""
    violations = [
        f"index.html 未出现必现文案 `{phrase}`（{reason}）"
        for phrase, reason in REQUIRED_COPY_IN_HTML
        if phrase not in html
    ]
    _report("C-COPY@1", "必须出现的文案", violations)


# --------------------------------------------------------------------------- #
# 组 11：版权页脚（R10.4）
# --------------------------------------------------------------------------- #
def test_footer_copyright(html: str) -> None:
    """C-STATIC-TEST@1「版权」：页脚含 HALOFLUX by Ryder191 与 原创实现。"""
    violations: list[str] = []
    if "HALOFLUX by Ryder191" not in html:
        violations.append("index.html 未出现 `HALOFLUX by Ryder191`（视觉语言来源声明）")
    if "原创实现" not in html:
        violations.append("index.html 未出现 `原创实现`（页面原创声明，未复制其源码）")
    if "PolyForm Noncommercial" not in html:
        violations.append(
            "index.html 未出现 `PolyForm Noncommercial`（来源许可证与非商业用途声明）"
        )
    _report("C-COPY@1", "页脚版权声明", violations)


# --------------------------------------------------------------------------- #
# C-PAGE-ANCHORS@1 —— 页面锚点与诊断接口（供 T3/T4/T5 驱动）
# --------------------------------------------------------------------------- #
def test_page_anchors(html: str) -> None:
    """C-PAGE-ANCHORS@1：必需 id 存在且唯一，scene.js 以经典脚本引入。"""
    violations: list[str] = []
    for anchor in REQUIRED_ANCHOR_IDS:
        occurrences = len(re.findall(rf"""id\s*=\s*["']{re.escape(anchor)}["']""", html))
        if occurrences == 0:
            violations.append(f"index.html 缺少锚点 `id=\"{anchor}\"`")
        elif occurrences > 1:
            violations.append(f"index.html 锚点 `id=\"{anchor}\"` 出现 {occurrences} 次，期望唯一")
    _report("C-PAGE-ANCHORS@1", "必需 DOM 锚点", violations)


def test_page_script_and_diagnostics(html: str) -> None:
    """C-STATIC-TEST@1「文件存在」+ C-PAGE-ANCHORS@1：经典脚本引入与诊断接口。"""
    violations: list[str] = []
    script_pattern = re.compile(
        r"""<script\b[^>]*\bsrc\s*=\s*["']assets/scene\.js["'][^>]*>""", re.IGNORECASE
    )
    script_match = script_pattern.search(html)
    if script_match is None:
        violations.append(
            "index.html 未以 `<script src=\"assets/scene.js\">` 引入唯一数据资源脚本"
        )
    else:
        if re.search(r"""type\s*=\s*["']module["']""", script_match.group(0), re.IGNORECASE):
            violations.append(
                "`assets/scene.js` 被以 type=\"module\" 引入（file:// 下会被 CORS 拒绝，必须是经典脚本）"
            )
    if "window.LOWALT_CONSOLE" not in html:
        violations.append("index.html 未定义诊断接口 `window.LOWALT_CONSOLE`（C-PAGE-ANCHORS@1）")
    if "1.0.0" not in html:
        violations.append("index.html 未出现版本号 `1.0.0`（LOWALT_CONSOLE.version 契约值）")
    _report("C-PAGE-ANCHORS@1", "数据脚本引入与诊断接口", violations)