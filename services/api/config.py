"""运行配置。

PostgreSQL 与 Redis 只留配置位：读到了就在 /health 里标 configured，
本进程不连接它们。密钥只来自环境变量，响应里不回显。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_dotenv(path: Path | None = None) -> None:
    """读仓库根的 .env。已存在的环境变量不覆盖，值也不要打到日志里。"""
    file = path or (REPO_ROOT / ".env")
    if not file.is_file():
        return
    for line_no, raw in enumerate(file.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            raise RuntimeError(f".env 第 {line_no} 行不是 KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise RuntimeError(f".env 第 {line_no} 行缺少变量名")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _text(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_env: str = "dev"
    storage_backend: Literal["memory", "sqlite"] = "sqlite"
    sqlite_path: str = "data/api.sqlite"
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)

    # 云上数据库的配置位。两个名字任一非空即视为“已配置、未连接”。
    rds_dsn: str = ""
    database_url: str = ""
    dcs_host: str = ""
    dcs_port: int = Field(default=6379, ge=1, le=65535)
    redis_url: str = ""

    # 空字符串表示用当前仓库里的 A* 基线。不要把 HTTP 里的算法名填到这里。
    planner_entry: str = ""
    # 空字符串表示 M3 未接入。
    agent_entry: str = ""

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        backend = (_text("STORAGE_BACKEND", "sqlite") or "sqlite").lower()
        port_text = _text("API_PORT", "8000") or "8000"
        dcs_port_text = _text("DCS_PORT", "6379") or "6379"
        try:
            api_port = int(port_text)
            dcs_port = int(dcs_port_text)
        except ValueError as exc:
            raise RuntimeError("API_PORT / DCS_PORT 必须是整数") from exc
        return cls(
            app_env=_text("APP_ENV", "dev") or "dev",
            storage_backend=backend,  # type: ignore[arg-type]
            sqlite_path=_text("SQLITE_PATH", "data/api.sqlite") or "data/api.sqlite",
            api_host=_text("API_HOST", "127.0.0.1") or "127.0.0.1",
            api_port=api_port,
            rds_dsn=_text("RDS_DSN"),
            database_url=_text("DATABASE_URL"),
            dcs_host=_text("DCS_HOST"),
            dcs_port=dcs_port,
            redis_url=_text("REDIS_URL"),
            planner_entry=_text("PLANNER_ENTRY"),
            agent_entry=_text("AGENT_ENTRY"),
        )

    def sqlite_file(self) -> Path | None:
        if self.storage_backend != "sqlite":
            return None
        path = Path(self.sqlite_path)
        if not path.is_absolute():
            path = REPO_ROOT / path
        return path
