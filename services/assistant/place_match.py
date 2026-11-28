"""Deterministic ranking for place candidates.

Photon returns several rows for almost every university (main campus, east
campus, affiliated college, another city). Treating "more than one row" as
ambiguous made the assistant ask the user to re-identify a place it had already
resolved correctly. The rule here is narrower:

* an exact normalized name match wins and is returned with coordinates;
* only a query without an exact match, but with several strong candidates
  nearby, is ambiguous;
* a request for a gate/building/stop never silently falls back to the parent
  campus centroid.
"""

from __future__ import annotations

import math
import re

CLUSTER_M = 1000.0
VARIANT_M = 8000.0
STRONG_SCORE = 60.0
EXACT = 99.0

_POI = re.compile(r"(东门|西门|南门|北门|大门|门|楼|馆|站|停车场|食堂|宿舍|操场|广场)$")
_BRACKETS = re.compile(r"[（(][^）)]*[）)]")


def normalize(name: str) -> str:
    # Keep the text inside brackets: "江西农业大学(东区)" is a different place
    # from the main campus, not the same name with decoration.
    value = (name or "").strip().replace("（", "(").replace("）", ")")
    return re.sub(r"\s+", "", value)


def distance_m(a: list[float], b: list[float]) -> float:
    lng1, lat1, lng2, lat2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 6371008.8 * 2 * math.asin(math.sqrt(min(1.0, h)))


UNFIT = ("highway", "waterway", "railway")


def score(query: str, candidate: str, kind: str = "") -> float:
    q, c = normalize(query), normalize(candidate)
    if not q or not c:
        return 0.0
    if any(part in (kind or "") for part in UNFIT):
        return 0.0
    if q == c:
        return 100.0
    if c.startswith(q):
        base = 84.0
    elif q in c:
        base = 66.0
    elif c in q:
        base = 42.0
    else:
        overlap = len(set(q) & set(c))
        if overlap < 2:
            return 0.0
        base = 20.0 * overlap / max(len(set(q)), 1)
    # A long tail ("…科技学院（共青校区）") is less likely to be the named place.
    return round(max(0.0, base - min(8.0, max(0, len(c) - len(q)) * 0.4)), 1)


def _row(item: dict, matched: str, confidence: str) -> dict:
    return {
        "name": item.get("name", ""),
        "point": list(item.get("point") or []),
        "address": item.get("address", ""),
        "matched": matched,
        "confidence": confidence,
    }


def resolve(query: str, rows: list[dict]) -> dict:
    ranked = sorted(
        (
            (score(query, item.get("name", ""), item.get("kind", "")), item)
            for item in rows
            if item.get("point")
        ),
        key=lambda pair: (-pair[0], len(pair[1].get("name", ""))),
    )
    if not ranked:
        return {
            "status": "unresolved",
            "candidates": [],
            "note": "未检索到可用的地点候选；道路、水系不算起降点，未猜坐标。",
        }
    best_score, best = ranked[0]
    near = [
        (value, item)
        for value, item in ranked
        if value >= best_score - 5 and distance_m(best["point"], item["point"]) <= CLUSTER_M
    ]
    # Same physical place returned twice (different OSM ways) collapses into one.
    variants = [
        item
        for value, item in ranked
        if value >= STRONG_SCORE
        and value >= best_score - 8
        and CLUSTER_M < distance_m(best["point"], item["point"]) <= VARIANT_M
    ]
    exact = best_score >= EXACT
    weak = best_score < STRONG_SCORE and len([1 for value, _ in ranked if value > 0]) >= 2
    ambiguous = (not exact) and (bool(variants) or weak)

    if len(normalize(query)) <= 4 and best_score < EXACT:
        return {
            "status": "unresolved",
            "candidates": [],
            "note": (
                f"「{query}」太短，检索首条是「{best['name']}」，可能不是你要的地方。"
                "请补城市或写全称；短名称不当坐标使用。"
            ),
        }
    if _POI.search(query) and not _POI.search(best.get("name", "")):
        return {
            "status": "unresolved",
            "candidates": [_row(item, "parent", "low") for _, item in near[:3]],
            "note": (
                f"只找到「{best['name']}」本体，没有该门/楼/设施的独立坐标。"
                "不要把学校中心当成门口，请在地图上点选。"
            ),
        }
    if ambiguous:
        pool = variants or [item for value, item in ranked[:4] if value > 0]
        options = [_row(item, "variant", "medium") for item in pool[:4]]
        return {
            "status": "ambiguous",
            "candidates": options,
            "note": f"「{query}」命中多个相近地点，请选定一个；未自动采用第一条。",
        }
    return {
        "status": "ok",
        "best": best,
        "score": best_score,
        "confidence": "high" if exact else ("medium" if best_score >= STRONG_SCORE else "low"),
        "candidates": [_row(item, "best" if item is best else "alternative", "high" if item is best else "low") for _, item in near[:1]],
        "alternatives": [
            _row(item, "alternative", "low")
            for value, item in ranked[1:4]
            if item not in [pair[1] for pair in near]
        ],
    }
