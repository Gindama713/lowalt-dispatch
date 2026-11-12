"""把 `模块:函数` 解析成可调用对象。

规划器和 M3 都走这里。HTTP 参数不会被当成导入路径。
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any


class EntrypointError(Exception):
    """配置的入口不存在或不可调用。"""


def load_callable(spec: str) -> Callable[..., Any]:
    text = spec.strip()
    module_name, sep, qualname = text.partition(":")
    if not sep or not module_name or not qualname:
        raise EntrypointError(f"入口必须写成 模块:函数，收到 {spec!r}")

    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise EntrypointError(f"无法导入 {module_name}（来自 {text}）") from exc

    obj: Any = module
    for part in qualname.split("."):
        if not part:
            raise EntrypointError(f"入口 {text} 的函数名不完整")
        try:
            obj = getattr(obj, part)
        except AttributeError as exc:
            raise EntrypointError(f"{text} 不存在") from exc

    if not callable(obj):
        raise EntrypointError(f"{text} 不可调用")
    return obj
