"""API 自己的错误。路由把它变成 HTTP 响应，不带堆栈。"""

from __future__ import annotations


class ApiError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
