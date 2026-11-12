"""Search approved repository documentation and return verifiable excerpts."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = (
    "事实文档.md",
    "docs/接口契约.md",
    "启动指南.md",
    "docs/M3_2026-11-10基础接入与下一步.md",
    "docs/M4_计划与验收.md",
    "services/assistant/README.md",
    "services/api/README.md",
)
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
WORD = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*|[\u3400-\u9fff]+")
FILLER = re.compile(
    r"项目文档|项目资料|知识库|文档|资料|解释一下|查一下|查一查|请问|告诉我|是什么|什么意思|"
    r"什么时候|为什么|什么|怎么|如何|是否|能不能|可以吗|能否|有没有|有什么|这个|代表|等于|了吗|吗|呢"
)
EXCERPT_LIMIT = 900


@dataclass(frozen=True)
class Excerpt:
    path: str
    heading: str
    start_line: int
    end_line: int
    revision: str
    text: str


def _terms(text: str) -> set[str]:
    terms = set()
    for word in WORD.findall(text.casefold()):
        if word.isascii():
            if len(word) >= 2:
                terms.add(word)
        else:
            terms.update(word[i : i + 2] for i in range(len(word) - 1))
    if terms & {"ack", "回执"}:
        terms.update(("ack", "回执"))
    return terms


def _split(path: str, data: bytes):
    revision = hashlib.sha256(data).hexdigest()[:12]
    titles: list[tuple[int, str]] = []
    block: list[str] = []
    first_line = 1
    fence = ""
    size = 0

    def excerpt():
        return Excerpt(
            path,
            " / ".join(title for _, title in titles) or path,
            first_line,
            first_line + len(block) - 1,
            revision,
            "\n".join(block),
        )

    for number, line in enumerate(data.decode("utf-8-sig").splitlines(), 1):
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        heading = HEADING.match(line) if not fence else None
        boundary = heading or (not fence and size + len(line) > EXCERPT_LIMIT)
        if boundary and block:
            yield excerpt()
            block.clear()
            size = 0
        if heading:
            level, title = len(heading[1]), heading[2]
            while titles and titles[-1][0] >= level:
                titles.pop()
            titles.append((level, title))
            continue
        if not line.strip() and not block:
            continue
        if not block:
            first_line = number
        block.append(line)
        size += len(line) + 1
        if marker:
            if not fence:
                fence = marker[1]
            elif marker[1].startswith(fence) and line.strip() == marker[1]:
                fence = ""
    if block:
        yield excerpt()


@lru_cache(maxsize=1)
def _index():
    # ponytail: scan this small, fixed document set in memory; index on disk if it grows substantially.
    rows = []
    frequencies: Counter[str] = Counter()
    for path in DOCUMENTS:
        for excerpt in _split(path, (ROOT / path).read_bytes()):
            body = _terms(excerpt.text)
            title = _terms(excerpt.heading.rsplit(" / ", 1)[-1])
            rows.append((excerpt, body, title))
            frequencies.update(body | title)
    return rows, frequencies


def search(query: str) -> list[dict]:
    query = FILLER.sub(" ", query.replace("飞完", "执行完成").replace("禁飞区", "限制区"))
    terms = _terms(query)
    if not terms:
        return []
    rows, frequencies = _index()
    weights = {term: math.log1p(len(rows) / (1 + frequencies[term])) for term in terms}
    minimum = sum(weights.values()) * 0.29
    candidates = []
    for excerpt, body, title in rows:
        matches = terms & body
        if not matches or (len(terms) > 1 and len(matches) < 2):
            continue
        score = sum(weights[term] for term in matches)
        if score >= minimum:
            score += 0.65 * sum(weights[term] for term in terms & title)
            candidates.append((score, excerpt))
    candidates.sort(key=lambda item: -item[0])
    if not candidates:
        return []
    # Preserve strong alternatives without presenting weak matches as evidence.
    return [asdict(excerpt) for score, excerpt in candidates[:3] if score >= candidates[0][0] * 0.72]
