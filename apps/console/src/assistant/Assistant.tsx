import { useEffect, useRef, useState } from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  Bot,
  BookOpen,
  Check,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  FileCheck2,
  ListChecks,
  LoaderCircle,
  MapPin,
  MessageSquareText,
  Minus,
  Plus,
  Radio,
  RotateCcw,
  Send,
  ShieldCheck,
  Sparkles,
  Square,
  TriangleAlert,
  X,
} from "lucide-react";
import { getHealth, requestTurn, validDraft } from "./api";
import { toolLabels } from "./types";
import type {
  AssistantContext,
  AssistantDraft,
  AssistantResult,
  Health,
  PreviewRoute,
  ToolTrace,
} from "./types";
import type { PanelId, Point } from "../types";
import "./assistant.css";

type Message = {
  id: string;
  role: "user" | "assistant";
  text: string;
  state: "pending" | "done" | "error";
  traces: ToolTrace[];
  result?: AssistantResult;
};
type Props = {
  open: boolean;
  onToggle: () => void;
  context: AssistantContext;
  onDraft: (draft: AssistantDraft) => boolean;
  onFocus: (point: Point, label: string) => void;
  onRoute: (route: PreviewRoute | null) => void;
  onPanel: (panel: PanelId) => void;
  onInjectTerrain: () => void;
  onEvent: (title: string, detail: string) => void;
};
const suggestions = [
  {
    title: "查询项目文档",
    text: "ACK 代表飞完了吗？",
    subtitle: "查看接口语义和原文依据",
    icon: BookOpen,
  },
  {
    title: "创建配送任务",
    text: "从医疗物资中转站到北区应急中心，配送1公斤药品，优先级P1",
    subtitle: "自然语言 → 可编辑任务卡",
    icon: Plus,
  },
  {
    title: "分析当前风险",
    text: "分析地形变化对当前航线的影响",
    subtitle: "变化区域 → 航线影响 → 建议",
    icon: ShieldCheck,
  },
  {
    title: "查询飞行状态",
    text: "查询当前飞行状态和电量",
    subtitle: "带时间和来源的遥测快照",
    icon: Radio,
  },
  {
    title: "总结任务记录",
    text: "总结本次任务记录和告警",
    subtitle: "事件证据 → 页面会话摘要",
    icon: ListChecks,
  },
];
function loadDraft() {
  try {
    const value = JSON.parse(
      localStorage.getItem("aeris-assistant-draft") || "null",
    );
    return validDraft(value) ? value : null;
  } catch {
    return null;
  }
}
function download(value: unknown) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = `aeris-assistant-DEMO-${Date.now()}.json`;
  document.body.append(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

function TaskStatusCard({
  task,
}: {
  task: NonNullable<AssistantResult["task_status"]>;
}) {
  return (
    <section
      className="assistant-result-card assistant-task-status"
      aria-label="本地任务状态"
    >
      <div className="assistant-card-title">
        <ShieldCheck size={14} />
        <strong>{task.source}</strong>
        <span>{task.scenario_id}</span>
      </div>
      <dl>
        <dt>任务 ID</dt>
        <dd>
          <code>{task.task_id}</code>
        </dd>
        <dt>航线版本</dt>
        <dd>{task.plan_version ?? "—"}</dd>
        <dt>规划状态</dt>
        <dd>{task.planning_label}</dd>
        <dt>执行回执</dt>
        <dd>
          {task.ack_accepted === null
            ? "暂无"
            : task.ack_accepted
              ? "已受理"
              : "已拒绝"}
        </dd>
        <dt>执行状态</dt>
        <dd>{task.execution_label ?? "暂无"}</dd>
      </dl>
    </section>
  );
}

function ToolActions({
  result,
  onFocus,
  onPanel,
}: {
  result: AssistantResult;
  onFocus: Props["onFocus"];
  onPanel: Props["onPanel"];
}) {
  const flight = result.traces.find(
    (t) => t.name === "get_flight_status",
  )?.result;
  const places = result.traces.find((t) => t.name === "list_places")?.result
    ?.places;
  const isPoint = (value: unknown): value is Point =>
    Array.isArray(value) &&
    value.length === 2 &&
    value.every((v) => Number.isFinite(v) && v >= 0 && v <= 3000);
  return (
    <div className="assistant-evidence-actions">
      {isPoint(flight?.point) && (
        <button
          onClick={() =>
            onFocus(flight.point as Point, "AER-01 · 演示轨迹位置")
          }
        >
          <MapPin size={11} />
          定位无人机
        </button>
      )}
      {flight && (
        <button onClick={() => onPanel("instruments")}>展开飞行仪表</button>
      )}
      {result.traces.some((t) => t.name === "list_events") && (
        <button onClick={() => onPanel("events")}>查看事件记录</button>
      )}
      {Array.isArray(places) &&
        places.map((place) =>
          place && typeof place.name === "string" && isPoint(place.point) ? (
            <button
              key={place.name}
              onClick={() => onFocus(place.point, place.name)}
            >
              <MapPin size={10} />
              {place.name}
            </button>
          ) : null,
        )}
    </div>
  );
}

export default function Assistant(props: Props) {
  const [health, setHealth] = useState<Health | null>(null);
  const [connection, setConnection] = useState<
    "checking" | "online" | "offline"
  >("checking");
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [draft, setDraft] = useState<AssistantDraft | null>(loadDraft);
  const [saved, setSaved] = useState("");
  const [busy, setBusy] = useState(false);
  const [configOpen, setConfigOpen] = useState(false);
  const [clearConfirm, setClearConfirm] = useState(false);
  const [preview, setPreview] = useState<PreviewRoute | null>(null);
  const [visiblePreview, setVisiblePreview] = useState(false);
  const [latestResult, setLatestResult] = useState<AssistantResult | null>(
    null,
  );
  const [refresh, setRefresh] = useState(0);
  const request = useRef<AbortController | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const log = useRef<HTMLDivElement>(null);
  const current = useRef(props);
  current.current = props;
  const previousTerrain = useRef(props.context.terrain?.revision ?? 0);
  const [unreadRisk, setUnreadRisk] = useState(false);
  useEffect(() => {
    const revision = props.context.terrain?.revision ?? 0;
    if (revision !== previousTerrain.current) {
      previousTerrain.current = revision;
      if (props.context.terrain?.count) setUnreadRisk(true);
    }
  }, [props.context.terrain]);
  useEffect(() => {
    if (!props.open) return;
    const controller = new AbortController();
    let active = true;
    setConnection("checking");
    const timeout = setTimeout(() => controller.abort(), 5000);
    getHealth(controller.signal)
      .then((value) => {
        if (!active) return;
        setHealth(value);
        setConnection("online");
      })
      .catch(() => {
        if (active) setConnection("offline");
      })
      .finally(() => clearTimeout(timeout));
    return () => {
      active = false;
      clearTimeout(timeout);
      controller.abort();
    };
  }, [props.open, refresh]);
  useEffect(() => {
    if (props.open) {
      const timer = setTimeout(() => input.current?.focus(), 180);
      return () => clearTimeout(timer);
    }
  }, [props.open]);
  useEffect(() => {
    try {
      localStorage.setItem("aeris-assistant-draft", JSON.stringify(draft));
    } catch {
      /* Local drafts can still be exported. */
    }
  }, [draft]);
  useEffect(() => {
    log.current?.scrollTo({
      top: log.current.scrollHeight,
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "instant"
        : "smooth",
    });
  }, [messages, busy, draft, preview, latestResult]);
  useEffect(() => () => request.current?.abort(), []);

  const send = async (value = text) => {
    const question = value.trim();
    if (!question || request.current || question.length > 3000) return;
    const controller = new AbortController();
    request.current = controller;
    const identifier = crypto.randomUUID();
    const history = messages
      .filter((m) => m.state === "done")
      .slice(-14)
      .map((m) => ({ role: m.role, content: m.text.slice(0, 6000) }));
    setText("");
    setBusy(true);
    setClearConfirm(false);
    setMessages((m) =>
      [
        ...m,
        {
          id: crypto.randomUUID(),
          role: "user" as const,
          text: question,
          state: "done" as const,
          traces: [],
        },
        {
          id: identifier,
          role: "assistant" as const,
          text: "",
          state: "pending" as const,
          traces: [],
        },
      ].slice(-60),
    );
    const update = (fn: (message: Message) => Message) =>
      setMessages((m) =>
        m.map((message) => (message.id === identifier ? fn(message) : message)),
      );
    const timeout = setTimeout(() => controller.abort("timeout"), 95000);
    try {
      const result = await requestTurn(
        { text: question, history, draft, context: current.current.context },
        controller.signal,
        (packet) => {
          if (packet.type === "tool_start")
            update((m) => ({
              ...m,
              traces: [
                ...m.traces,
                { id: packet.id, name: packet.name, status: "running" },
              ],
            }));
          if (packet.type === "tool_result")
            update((m) => ({
              ...m,
              traces: m.traces.map((t) =>
                t.id === packet.trace.id ? packet.trace : t,
              ),
            }));
        },
      );
      update((m) => ({
        ...m,
        text: result.text,
        state: "done",
        result,
        traces: result.traces,
      }));
      setLatestResult(result);
      setConnection("online");
      setHealth({
        status: "ok",
        provider: result.provider,
        model_configured: result.provider === "maas",
        dispatch_enabled: false,
        protocol: "aeris-assistant-1",
      });
      if (result.draft) {
        setDraft(result.draft);
        if (JSON.stringify(result.draft) !== JSON.stringify(draft)) {
          setPreview(null);
          setVisiblePreview(false);
          current.current.onRoute(null);
        }
      }
      if (result.route?.status === "geometry_only") setPreview(result.route);
      if (result.risk) setUnreadRisk(false);
      current.current.onEvent(
        "调度助手完成工具查询",
        `${result.provider === "local" ? "本地规则" : "MaaS模型"} · ${result.traces.length}项工具 · ${result.turn_id.slice(0, 8)}`,
      );
    } catch (error) {
      const stopped = controller.signal.aborted;
      const message = stopped
        ? controller.signal.reason === "timeout"
          ? "请求超时，已停止等待。请检查模型服务后重试。"
          : "已停止接收本轮结果。已开始的只读工具可能仍在完成，未下发飞行命令。"
        : error instanceof Error
          ? error.message
          : "助手请求失败";
      update((m) => ({
        ...m,
        text: message,
        state: "error",
        traces: m.traces.map((t) =>
          t.status === "running" ? { ...t, status: "error" } : t,
        ),
      }));
    } finally {
      clearTimeout(timeout);
      request.current = null;
      setBusy(false);
    }
  };

  const editDraft = (fields: Partial<AssistantDraft>) => {
    setDraft((d) => (d ? { ...d, ...fields } : d));
    setPreview(null);
    setVisiblePreview(false);
    props.onRoute(null);
  };
  const exportConversation = () =>
    download({
      schema: "aeris-assistant-1",
      is_simulated: true,
      exported_at: new Date().toISOString(),
      provider: health?.provider ?? "unconnected",
      messages,
      draft,
      dispatch_enabled: false,
    });
  const saveDraft = () => {
    if (
      !draft ||
      !draft.origin?.trim() ||
      !draft.destination?.trim() ||
      draft.payload_kg === null ||
      !draft.name.trim()
    )
      return;
    if (props.onDraft(draft)) {
      setSaved(JSON.stringify(draft));
      props.onEvent(
        "已确认助手任务草稿",
        `${draft.name} · 已存任务空间，待正式参数与安全校验`,
      );
    }
  };
  const clear = () => {
    setMessages([]);
    setLatestResult(null);
    setDraft(null);
    setPreview(null);
    setSaved("");
    setVisiblePreview(false);
    props.onRoute(null);
    setClearConfirm(false);
  };
  const risk = latestResult?.risk;
  const draftComplete =
    draft?.origin?.trim() &&
    draft.destination?.trim() &&
    draft.payload_kg !== null &&
    draft.name.trim();

  return (
    <>
      {!props.open && (
        <button
          className={`assistant-launcher ${unreadRisk ? "has-risk" : ""}`}
          onClick={props.onToggle}
          aria-label="打开调度助手"
        >
          <span className="assistant-launcher-icon">
            <Sparkles size={18} />
          </span>
          <span>
            调度助手
            <small>
              {unreadRisk ? "有新的地形变化待分析" : "任务 · 风险 · 记录"}
            </small>
          </span>
          <kbd>A</kbd>
          {unreadRisk && <i />}
        </button>
      )}
      <aside
        className={`assistant-panel ${props.open ? "open" : ""}`}
        aria-label="调度助手"
        hidden={!props.open}
      >
        <div className="assistant-heading">
          <div className="assistant-brand-icon">
            <Sparkles size={20} />
          </div>
          <div>
            <div className="assistant-eyebrow">AERIS / COPILOT</div>
            <h2>
              调度助手 <span>BETA</span>
            </h2>
          </div>
          <button
            className="icon-button"
            onClick={() => setConfigOpen((v) => !v)}
            aria-label="助手连接说明"
          >
            <CircleHelp size={16} />
          </button>
          <button
            className="icon-button"
            onClick={props.onToggle}
            aria-label="收起调度助手"
          >
            <Minus size={18} />
          </button>
        </div>
        <div className={`assistant-connection ${connection}`}>
          <i />
          <span>
            {connection === "checking"
              ? "检查助手服务…"
              : connection === "offline"
                ? "助手服务未连接"
                : health?.provider === "maas"
                  ? "华为云模型接口 · 工具模式"
                  : "本地规则模式 · 模型未接入"}
          </span>
          <button
            aria-label="刷新助手连接"
            onClick={() => setRefresh((v) => v + 1)}
          >
            <RotateCcw size={12} />
          </button>
        </div>
        {configOpen && (
          <div className="assistant-config">
            <strong>连接与执行边界</strong>
            <p>
              前端通过本地后端调用工具。配置服务端MaaS地址、模型ID和密钥后可启用模型工具编排；密钥不进入浏览器。
            </p>
            <p>
              当前遥测为演示源，路线只做几何预览。草稿确认只保存到任务空间。
            </p>
            <code>后端：127.0.0.1:8012</code>
          </div>
        )}
        {unreadRisk && (
          <div className="assistant-risk-nudge">
            <TriangleAlert size={14} />
            <span>地形 REV {props.context.terrain?.revision} 已更新</span>
            <button
              disabled={busy}
              onClick={() => void send("分析最新地形变化对当前航线的影响")}
            >
              分析影响 <ArrowRight size={12} />
            </button>
          </div>
        )}
        <div
          className="assistant-conversation"
          ref={log}
          aria-label="助手对话记录"
        >
          {!messages.length && (
            <div className="assistant-welcome">
              <span className="assistant-orbit">
                <Bot size={28} />
                <i />
                <b />
              </span>
              <div className="assistant-eyebrow">YOUR MISSION, CONNECTED.</div>
              <h3>把意图，变成下一步。</h3>
              <p>
                创建配送任务、检查变化影响，
                <br />
                也可以直接询问当前飞行状态。
              </p>
              <div className="assistant-suggestions">
                {suggestions.map((s) => (
                  <button
                    key={s.title}
                    onClick={() => void send(s.text)}
                    disabled={busy}
                  >
                    <s.icon size={17} />
                    <span>
                      {s.title}
                      <small>{s.subtitle}</small>
                    </span>
                    <ChevronRight size={14} />
                  </button>
                ))}
              </div>
              <div className="assistant-data-note">
                <ShieldCheck size={13} />{" "}
                每项工具结果都有来源，重要操作由你确认。
              </div>
            </div>
          )}
          {messages.map((message) => (
            <article
              className={`assistant-message ${message.role} ${message.state}`}
              key={message.id}
            >
              <div className="assistant-message-role">
                {message.role === "assistant" ? (
                  <>
                    <Sparkles size={12} /> 调度助手
                  </>
                ) : (
                  "你"
                )}
                {message.result && (
                  <ToolActions
                    result={message.result}
                    onFocus={props.onFocus}
                    onPanel={props.onPanel}
                  />
                )}
                {message.result && (
                  <span>
                    {message.result.provider === "maas"
                      ? "MODEL + TOOLS"
                      : "LOCAL RULES"}
                  </span>
                )}
              </div>
              {message.traces.length > 0 && (
                <div className="assistant-traces">
                  {message.traces.map((trace) => (
                    <details key={trace.id}>
                      <summary>
                        {trace.status === "running" ? (
                          <LoaderCircle
                            size={12}
                            className="assistant-spinning"
                          />
                        ) : trace.status === "error" ? (
                          <TriangleAlert size={12} />
                        ) : (
                          <Check size={12} />
                        )}
                        <span>
                          {Object.hasOwn(toolLabels, trace.name)
                            ? toolLabels[trace.name]
                            : "工具调用"}
                        </span>
                        <small>
                          {trace.status === "running"
                            ? "处理中"
                            : `${trace.elapsed_ms ?? 0} ms`}
                        </small>
                        <ChevronDown size={11} />
                      </summary>
                      {trace.source && <p>{trace.source}</p>}
                      {trace.result && (
                        <pre>
                          {JSON.stringify(
                            {
                              arguments: trace.arguments ?? {},
                              result: trace.result,
                            },
                            null,
                            2,
                          )}
                        </pre>
                      )}
                    </details>
                  ))}
                </div>
              )}
              {message.text && (
                <p className="assistant-message-text">{message.text}</p>
              )}
              {message.result?.documents?.map((doc) => (
                <details
                  className="assistant-document"
                  key={`${doc.path}:${doc.start_line}`}
                >
                  <summary>
                    <BookOpen size={13} />
                    <span>{doc.heading}</span>
                  </summary>
                  <p>
                    {doc.path} · 第 {doc.start_line}–{doc.end_line} 行 ·{" "}
                    {doc.revision}
                  </p>
                  <blockquote>{doc.text}</blockquote>
                </details>
              ))}
              {message.result?.task_status && (
                <TaskStatusCard task={message.result.task_status} />
              )}
              {message.state === "pending" && (
                <div className="assistant-thinking">
                  <i />
                  <i />
                  <i />
                  <span>正在根据工具结果处理</span>
                </div>
              )}
              {message.state === "error" && (
                <button
                  className="assistant-retry"
                  disabled={busy}
                  onClick={() => {
                    const index = messages.indexOf(message);
                    const previous = messages[index - 1];
                    if (previous?.role === "user") void send(previous.text);
                  }}
                >
                  <RotateCcw size={11} /> 重试本轮问题
                </button>
              )}
              {message.result && (
                <div className="assistant-message-foot">
                  <span>
                    {message.result.task_status
                      ? "本地合成任务"
                      : message.result.traces.some(
                            (trace) => trace.name === "search_project_docs",
                          )
                        ? "项目文档"
                        : props.context.telemetry_mode === "live"
                          ? "LIVE TELEMETRY"
                          : "DEMO CONTEXT"}
                  </span>
                  <span>{message.result.turn_id.slice(0, 8)}</span>
                </div>
              )}
            </article>
          ))}
          {risk?.status === "no_change_data" && (
            <div className="assistant-followups">
              <button disabled={busy} onClick={props.onInjectTerrain}>
                注入演示地形变化
              </button>
            </div>
          )}
          {risk && risk.status !== "no_change_data" && (
            <section
              className={`assistant-result-card risk-${risk.status}`}
              aria-label="风险分析结果"
            >
              <div className="assistant-card-title">
                <ShieldCheck size={14} />
                <strong>变化影响核查</strong>
                <span>REV {risk.terrain_revision}</span>
              </div>
              <div className="assistant-risk-facts">
                <div>
                  <span>平面交叠航段</span>
                  <strong>{risk.affected_segments?.length ?? 0}</strong>
                </div>
                <div>
                  <span>其中剩余航段</span>
                  <strong>{risk.remaining_segment_count ?? 0}</strong>
                </div>
              </div>
              <p>
                {risk.status === "review_required"
                  ? "存在需要进一步校验的平面交叠"
                  : risk.status === "past_segments_only"
                    ? "交叠位于已回放航段"
                    : "本次未发现包围框平面交叠"}
              </p>
              <small>
                平面筛查结果不能代替净空与备降校验。
                {risk.stale ? " 当前地形数据已过期。" : ""}
              </small>
              <div className="assistant-card-actions">
                <button
                  disabled={!risk.focus_point}
                  onClick={() =>
                    risk.focus_point &&
                    props.onFocus(risk.focus_point, "地形变化区域")
                  }
                >
                  <MapPin size={12} /> 定位变化区域
                </button>
                <button onClick={() => props.onPanel("events")}>
                  查看事件
                </button>
              </div>
            </section>
          )}
          {draft && (
            <section
              className="assistant-result-card assistant-draft-card"
              aria-label="助手任务草稿"
            >
              <div className="assistant-card-title">
                <FileCheck2 size={14} />
                <strong>任务草稿</strong>
                <span>待确认</span>
              </div>
              <fieldset disabled={busy}>
                <label>
                  任务名称
                  <input
                    aria-label="助手任务名称"
                    maxLength={80}
                    value={draft.name}
                    onChange={(e) => editDraft({ name: e.target.value })}
                  />
                </label>
                <div className="assistant-draft-stops">
                  <label>
                    起点
                    <input
                      aria-label="助手任务起点"
                      list="assistant-places"
                      maxLength={120}
                      placeholder="选择已登记地点"
                      value={draft.origin ?? ""}
                      onChange={(e) =>
                        editDraft({ origin: e.target.value || null })
                      }
                    />
                  </label>
                  <ArrowRight size={13} />
                  <label>
                    终点
                    <input
                      aria-label="助手任务终点"
                      list="assistant-places"
                      maxLength={120}
                      placeholder="选择已登记地点"
                      value={draft.destination ?? ""}
                      onChange={(e) =>
                        editDraft({ destination: e.target.value || null })
                      }
                    />
                  </label>
                </div>
                <datalist id="assistant-places">
                  {[
                    "医疗物资中转站",
                    "北区应急中心",
                    "L1",
                    "L2",
                    "L3",
                    "L4",
                  ].map((p) => (
                    <option key={p} value={p} />
                  ))}
                </datalist>
                <div className="assistant-draft-grid">
                  <label>
                    载荷 / kg
                    <input
                      aria-label="助手任务载荷"
                      type="number"
                      min="0"
                      max="100"
                      step="0.1"
                      value={draft.payload_kg ?? ""}
                      placeholder="待补充"
                      onChange={(e) =>
                        editDraft({
                          payload_kg:
                            e.target.value &&
                            Number.isFinite(e.target.valueAsNumber)
                              ? Math.max(
                                  0,
                                  Math.min(100, e.target.valueAsNumber),
                                )
                              : null,
                        })
                      }
                    />
                  </label>
                  <label>
                    优先级
                    <select
                      aria-label="助手任务优先级"
                      value={draft.priority}
                      onChange={(e) =>
                        editDraft({ priority: e.target.value as "P1" | "P2" })
                      }
                    >
                      <option value="P1">P1 · 应急</option>
                      <option value="P2">P2 · 常规</option>
                    </select>
                  </label>
                </div>
              </fieldset>
              <p className="assistant-draft-limit">
                机型、能量与独立安全校验待补充；保存草稿不代表正式下发。
              </p>
              <div className="assistant-card-actions">
                <button
                  disabled={!draftComplete || busy}
                  onClick={() => void send("预览当前任务草稿的几何路线")}
                >
                  <MapPin size={12} /> 预览几何路线
                </button>
                <button
                  className="primary"
                  disabled={
                    !draftComplete || busy || saved === JSON.stringify(draft)
                  }
                  onClick={saveDraft}
                >
                  <Check size={12} />{" "}
                  {saved === JSON.stringify(draft)
                    ? "已保存到任务空间"
                    : "确认保存草稿"}
                </button>
              </div>
            </section>
          )}
          {preview && (
            <section
              className="assistant-result-card"
              aria-label="路线预览结果"
            >
              <div className="assistant-card-title">
                <MapPin size={14} />
                <strong>几何路线预览</strong>
                <span>A*</span>
              </div>
              <div className="assistant-risk-facts">
                <div>
                  <span>几何长度</span>
                  <strong>
                    {(preview.length_m / 1000).toFixed(2)}
                    <small> km</small>
                  </strong>
                </div>
                <div>
                  <span>航点数量</span>
                  <strong>{preview.waypoint_count}</strong>
                </div>
              </div>
              <p>已实际计算 · 能量与备降校验待完成</p>
              <small>{preview.assumptions}</small>
              <div className="assistant-card-actions">
                <button
                  onClick={() => {
                    setVisiblePreview((v) => !v);
                    props.onRoute(visiblePreview ? null : preview);
                  }}
                >
                  <MapPin size={12} />
                  {visiblePreview ? "隐藏预览航线" : "地图展示预览"}
                </button>
                <button onClick={() => props.onPanel("analysis")}>
                  查看余量组件
                </button>
              </div>
            </section>
          )}
          {messages.length > 0 && (
            <div className="assistant-followups">
              <button
                disabled={busy}
                onClick={() => void send("查询当前飞行状态")}
              >
                查询状态
              </button>
              <button
                disabled={busy}
                onClick={() => void send("列出已登记地点")}
              >
                地点列表
              </button>
              <button
                disabled={busy}
                onClick={() => void send("总结本次任务记录")}
              >
                记录摘要
              </button>
            </div>
          )}
        </div>
        <div className="assistant-composer-wrap">
          {connection === "offline" && (
            <div className="assistant-offline">
              <TriangleAlert size={13} />
              <span>请启动本地助手后端，其他控制台功能可继续使用。</span>
            </div>
          )}
          <form
            className="assistant-composer"
            onSubmit={(e) => {
              e.preventDefault();
              void send();
            }}
          >
            <textarea
              ref={input}
              aria-label="向调度助手提问"
              placeholder="描述任务，或询问当前风险…"
              maxLength={3000}
              rows={2}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (
                  e.key === "Enter" &&
                  !e.shiftKey &&
                  !e.nativeEvent.isComposing
                ) {
                  e.preventDefault();
                  void send();
                }
              }}
            />
            <div>
              <span>Enter 发送 · Shift + Enter 换行</span>
              {busy ? (
                <button
                  type="button"
                  aria-label="停止接收助手结果"
                  onClick={() => request.current?.abort()}
                >
                  <Square size={13} />
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={!text.trim()}
                  aria-label="发送给调度助手"
                >
                  <Send size={15} />
                </button>
              )}
            </div>
          </form>
          <div className="assistant-bottom-actions">
            <span>演示数据 · 下发未接入</span>
            <button
              onClick={exportConversation}
              aria-label="导出助手对话"
              disabled={!messages.length}
            >
              <ArrowDownToLine size={12} />
            </button>
            <button
              onClick={() => setClearConfirm((v) => !v)}
              aria-label="清空助手会话"
              disabled={busy || !messages.length}
            >
              <RotateCcw size={12} />
            </button>
          </div>
          {clearConfirm && (
            <div className="assistant-clear-confirm">
              <span>清空对话和助手草稿？已保存的任务保留。</span>
              <button onClick={clear}>确认</button>
              <button onClick={() => setClearConfirm(false)}>取消</button>
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
