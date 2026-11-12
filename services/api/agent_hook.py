"""M3 的预留调用点。本文件不是 Agent。

不创建 agent/ 目录，也不在这里写状态机、工具循环或模型调用。
M3 由其他组员实现。他们把自己的函数配到 AGENT_ENTRY 后，
规划完成时会把结构化上下文传进去。

返回值一律不采用：不改路线、不改任务状态、不把模型文本当成校验结论。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from services.api.entrypoints import EntrypointError, load_callable
from services.api.envelopes import AgentHookResult, AgentStatus


class AgentContext(BaseModel):
    """交给 M3 的事实。只有 id 和这次规划的结果标志，没有飞控指令。"""

    model_config = ConfigDict(extra="forbid")

    event: Literal["plan_completed"]
    task_id: str
    snapshot_id: str
    route_id: str
    found: bool
    algorithm: str


def agent_status(entry: str) -> AgentStatus:
    if not entry.strip():
        return AgentStatus(
            status="not_implemented",
            entry_configured=False,
            detail=(
                "M3 未接入。规划接口在算出路线之后会调用 services.api.agent_hook.invoke_task_agent；"
                "当前该函数固定返回未实现。设置 AGENT_ENTRY=模块:函数 后才会真正调用，"
                "并且仍然不会按返回值改写路线。"
            ),
        )
    return AgentStatus(
        status="entry_configured",
        entry_configured=True,
        detail=(
            "已配置 M3 入口。规划完成后会调用它。本服务不解释、不执行它的返回值。"
            "模块路径写在规划响应的 agent.entry 里，不要把密钥放进 AGENT_ENTRY。"
        ),
    )


def invoke_task_agent(ctx: AgentContext, *, entry: str) -> AgentHookResult:
    spec = entry.strip()
    if not spec:
        return AgentHookResult(
            status="not_implemented",
            detail=(
                "未实现。M3 任务 Agent 不在本服务，这里没有状态机，也没有模型调用。"
                "设置 AGENT_ENTRY 后才会把同一次规划的 task_id、snapshot_id、route_id 送出去。"
            ),
            entry=None,
            applied=False,
        )
    try:
        fn = load_callable(spec)
        fn(ctx)
    except EntrypointError as exc:
        return AgentHookResult(
            status="error",
            detail=f"M3 入口无法加载：{exc}",
            entry=spec,
            applied=False,
        )
    except Exception as exc:
        return AgentHookResult(
            status="error",
            detail=f"调用 M3 入口失败：{exc.__class__.__name__}: {exc}",
            entry=spec,
            applied=False,
        )
    return AgentHookResult(
        status="invoked",
        detail="已调用 M3 入口。本服务没有根据返回值改变路线、任务或快照。",
        entry=spec,
        applied=False,
    )
