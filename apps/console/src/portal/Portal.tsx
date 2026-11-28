import Landing from "./LandingPage";
import {
  createContext,
  lazy,
  Suspense,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type ComponentType,
} from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  Bell,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Command,
  Compass,
  Cpu,
  FileBarChart2,
  HelpCircle,
  LayoutDashboard,
  LoaderCircle,
  LogOut,
  Map,
  Menu,
  Orbit,
  PanelLeftClose,
  Plus,
  Radio,
  Route,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Users,
  X,
} from "lucide-react";
import {
  api,
  ApiError,
  downloadJson,
  message,
  safeTarget,
  stateLabel,
  type DispatchTask,
  type Policy,
  type Summary,
  type User,
} from "./api";
import { MissionList, MissionWizard, TaskDetail } from "./MissionPages";
import { AccountPage, IdentityPage } from "./IdentityPages";
import { ThemeToggle } from "./Theme";
import Assistant from "../assistant/Assistant";
import type { AssistantContext } from "../assistant/types";
import "./portal.css";

// Portal pages have no live telemetry; the assistant still answers knowledge and
// intake questions. Keep one stable object so it does not retrigger effects.
const PORTAL_ASSISTANT_CONTEXT: AssistantContext = {
  is_simulated: true,
  sampled_at: new Date().toISOString(),
  task_id: "T-S1-01",
  selected_task_id: null,
  route_id: "S1-01-baseline",
  progress: 0,
  // Portal pages carry no telemetry. The backend rejects demo mode without demo
  // telemetry, so declare live with empty payloads rather than inventing numbers.
  telemetry_mode: "live",
  telemetry: null,
  live_telemetry: null,
  terrain: null,
  events: [],
};
import "./workspace-theme.css";

const Console = lazy(() => import("../App"));
const AircraftLibrary = lazy(() => import("../AircraftLibrary"));
type PortalState = {
  user: User;
  go: (path: string) => void;
  toast: (text: string) => void;
  refreshUser: () => Promise<void>;
  can: (permission: string) => boolean;
  summary: Summary | null;
  refreshSummary: () => Promise<void>;
};
const Context = createContext<PortalState | null>(null);
export function usePortal() {
  const value = useContext(Context);
  if (!value) throw new Error("Portal context required");
  return value;
}
export function Button({
  children,
  onClick,
  primary = false,
  disabled = false,
  type = "button",
  className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  primary?: boolean;
  disabled?: boolean;
  type?: "button" | "submit";
  className?: string;
}) {
  return (
    <button
      type={type}
      className={`p-button ${primary ? "p-primary" : ""} ${className}`}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  );
}
export function Empty({
  title,
  children,
  icon: Icon = Route,
}: {
  title: string;
  children?: ReactNode;
  icon?: ComponentType<{ size?: number }>;
}) {
  return (
    <div className="p-empty">
      <span>
        <Icon size={27} />
      </span>
      <h3>{title}</h3>
      {children}
    </div>
  );
}
export function PageTitle({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  const path = window.location.pathname;
  const Symbol = path.startsWith("/missions")
    ? Route
    : path.startsWith("/identity") || path === "/account"
      ? ShieldCheck
      : path === "/analytics"
        ? FileBarChart2
        : path === "/help"
          ? BookOpen
          : LayoutDashboard;
  return (
    <div className="p-page-title">
      <span className="p-page-symbol">
        <Symbol size={23} strokeWidth={1.6} />
      </span>
      <div>
        {eyebrow && <p className="p-kicker">{eyebrow}</p>}
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}
export function ErrorLine({ text }: { text: string }) {
  return text ? (
    <div role="alert" className="p-error">
      <ShieldCheck size={17} />
      <span>{text}</span>
    </div>
  ) : null;
}
export function Loading() {
  return (
    <div className="p-loading" role="status">
      <LoaderCircle className="p-spin" size={22} />
      正在连接工作区…
    </div>
  );
}

const modules = [
  {
    path: "/missions",
    title: "任务中心",
    description: "从任务创建到执行回执，每一步都清晰可见。",
    icon: Route,
    permission: "task.read",
    index: "01",
  },
  {
    path: "/airspace",
    title: "空域态势",
    description: "在真实地图上定位，探索航线、地形与天气。",
    icon: Map,
    permission: "map.read",
    index: "02",
  },
  {
    path: "/fleet",
    title: "设备与遥测",
    description: "查看飞行参数、设备状态与数据来源。",
    icon: Radio,
    permission: "telemetry.read",
    index: "03",
  },
  {
    path: "/aircraft",
    title: "配送机型库",
    description: "查看官方机型规格，选择或录入配送测试参数。",
    icon: Cpu,
    permission: "map.read",
    index: "05",
  },
  {
    path: "/analytics",
    title: "运行记录",
    description: "追溯决策过程，导出可复核的任务证据。",
    icon: FileBarChart2,
    permission: "report.read",
    index: "04",
  },
];
const pages = [
  {
    path: "/workspace",
    title: "工作台",
    icon: LayoutDashboard,
    permission: "workspace.read",
  },
  ...modules,
  {
    path: "/identity/users",
    title: "成员管理",
    icon: Users,
    permission: "identity.manage",
  },
  {
    path: "/identity/roles",
    title: "角色权限",
    icon: ShieldCheck,
    permission: "identity.manage",
  },
  {
    path: "/account",
    title: "账户与安全",
    icon: Settings2,
    permission: "workspace.read",
  },
  {
    path: "/help",
    title: "使用指南",
    icon: BookOpen,
    permission: "workspace.read",
  },
];
function Brand({ go }: { go: (path: string) => void }) {
  return (
    <a
      href="/"
      className="p-brand"
      onClick={(e) => {
        e.preventDefault();
        go("/");
      }}
      aria-label="AERIS 首页"
    >
      <span className="p-brand-mark">
        <Orbit size={25} />
      </span>
      <strong>AERIS</strong>
    </a>
  );
}

function AuthPage({
  path,
  go,
  policy,
  refresh,
}: {
  path: string;
  go: (path: string) => void;
  policy: Policy | null;
  refresh: () => Promise<void>;
}) {
  const setup = !!policy?.setup_required;
  const register = path.startsWith("/register") || setup;
  const [email, setEmail] = useState(""),
    [password, setPassword] = useState(""),
    [name, setName] = useState(""),
    [invite, setInvite] = useState(
      new URLSearchParams(location.search).get("invite") || "",
    ),
    [code, setCode] = useState(""),
    [challenge, setChallenge] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const target = safeTarget(new URLSearchParams(location.search).get("next"));
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const value = await api<{ mfa_required: boolean; challenge?: string }>(
        challenge
          ? "/auth/mfa/login"
          : setup
            ? "/auth/setup"
            : register
              ? "/auth/register"
              : "/auth/login",
        challenge
          ? { challenge, code }
          : register
            ? { email, password, name, invite }
            : { email, password },
      );
      if (value.mfa_required) {
        setChallenge(value.challenge!);
        setPassword("");
      } else {
        await refresh();
        go(target);
      }
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="p-auth">
      <header>
        <Brand go={go} />
        <ThemeToggle />
        <button className="p-text-button" onClick={() => go("/")}>
          <ArrowRight size={15} />
          返回首页
        </button>
      </header>
      <main>
        <aside className="p-auth-story">
          <span className="p-kicker">A CLEARER WAY TO FLY</span>
          <h1>
            每一个可靠的任务，
            <br />
            从安全连接开始。
          </h1>
          <p>
            在一个清晰的工作区里，
            <br />
            让任务、团队与决策保持同步。
          </p>
          <div className="p-auth-graphic">
            <Orbit size={160} strokeWidth={0.55} />
            <span>
              <ShieldCheck size={26} />
            </span>
          </div>
          <small>LOCAL FIRST. TEAM READY.</small>
        </aside>
        <section className="p-auth-form">
          <div className="p-auth-icon">
            <ShieldCheck size={23} />
          </div>
          <p className="p-kicker">
            {setup ? "WELCOME TO YOUR WORKSPACE" : "YOUR MISSION STARTS HERE"}
          </p>
          <h2>
            {challenge
              ? "验证你的身份"
              : setup
                ? "创建团队工作区"
                : register
                  ? "加入你的团队"
                  : "欢迎回来"}
          </h2>
          <p>
            {challenge
              ? "输入验证器 App 中的 6 位动态验证码。"
              : setup
                ? "设置第一位管理员，随后邀请团队成员。"
                : register
                  ? policy?.registration === "invite"
                    ? "使用管理员邀请的邮箱与邀请码注册。"
                    : "创建账户，开始探索你的工作区。"
                  : "登录 AERIS，继续你的低空任务。"}
          </p>
          {!policy ? (
            <ErrorLine text="无法读取身份服务，请先启动本地后端后刷新。" />
          ) : (
            <form onSubmit={(e) => void submit(e)}>
              {challenge ? (
                <label>
                  动态验证码
                  <input
                    autoComplete="one-time-code"
                    inputMode="numeric"
                    pattern="[0-9]{6}"
                    maxLength={6}
                    required
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    autoFocus
                  />
                </label>
              ) : (
                <>
                  {register && (
                    <label>
                      你的姓名
                      <input
                        autoComplete="name"
                        maxLength={60}
                        required
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        placeholder="团队成员如何称呼你"
                      />
                    </label>
                  )}
                  <label>
                    工作邮箱
                    <input
                      type="email"
                      autoComplete="email"
                      required
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="name@company.com"
                    />
                  </label>
                  <label>
                    密码
                    <input
                      type="password"
                      autoComplete={
                        register ? "new-password" : "current-password"
                      }
                      required
                      minLength={register ? 10 : 1}
                      maxLength={128}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder={
                        register
                          ? "至少10位，包含字母和数字"
                          : "输入你的账户密码"
                      }
                    />
                  </label>
                  {register && !setup && policy.registration !== "closed" && (
                    <label>
                      邀请码{" "}
                      {policy.registration === "open" && (
                        <small>（可选）</small>
                      )}
                      <input
                        required={policy.registration === "invite"}
                        autoComplete="off"
                        value={invite}
                        onChange={(e) => setInvite(e.target.value)}
                        placeholder="由工作区管理员提供"
                      />
                    </label>
                  )}
                </>
              )}
              <ErrorLine text={error} />
              <Button
                type="submit"
                primary
                disabled={
                  busy ||
                  (register && !setup && policy.registration === "closed")
                }
              >
                {busy ? <LoaderCircle className="p-spin" size={17} /> : null}
                {challenge
                  ? "验证并进入工作区"
                  : setup
                    ? "创建工作区"
                    : register
                      ? "创建账户"
                      : "登录工作区"}
                <ArrowRight size={17} />
              </Button>
            </form>
          )}
          <div className="p-auth-switch">
            {challenge ? (
              <button
                onClick={() => {
                  setChallenge("");
                  setCode("");
                  setError("");
                }}
              >
                返回账号密码登录
              </button>
            ) : (
              !setup && (
                <>
                  {register ? "已有账户？" : "还没有账户？"}
                  <button
                    onClick={() => {
                      setError("");
                      go(
                        (register ? "/login" : "/register") +
                          "?next=" +
                          encodeURIComponent(target),
                      );
                    }}
                  >
                    {register ? "登录" : "使用邀请注册"}
                  </button>
                </>
              )
            )}
          </div>
          <div className="p-auth-footnote">
            <ShieldCheck size={15} />
            <span>
              密码加密保存 · 支持验证器 MFA
              <br />
              邮箱验证状态可在“账户与安全”中查看。
            </span>
          </div>
        </section>
      </main>
    </div>
  );
}

function Dashboard() {
  const { user, go, summary, can } = usePortal();
  const count = summary?.tasks.length ?? 0;
  return (
    <>
      <PageTitle
        eyebrow="YOUR OPERATIONS, IN FOCUS"
        title={`${user.name}，欢迎回到工作台`}
        description="从这里了解当前状态，开始一项清晰可控的任务。"
        action={
          can("task.create") && (
            <Button primary onClick={() => go("/missions/new")}>
              <Plus size={17} />
              创建任务
            </Button>
          )
        }
      />
      <div className="p-dashboard-intro">
        <div>
          <span className="p-badge">开始你的第一条完整链路</span>
          <h2>从一个场景，走到一份可追溯的结果。</h2>
          <p>系统会引导你核对任务参数，再运行规划、独立校验与本地执行。</p>
          <div className="p-mini-steps">
            <span>
              <b>1</b>选择场景
            </span>
            <ChevronRight size={14} />
            <span>
              <b>2</b>核对参数
            </span>
            <ChevronRight size={14} />
            <span>
              <b>3</b>查看结果
            </span>
          </div>
        </div>
        <div className="p-dashboard-orbit">
          <Orbit size={100} strokeWidth={0.6} />
          <span>
            <Route size={25} />
          </span>
        </div>
      </div>
      <div className="p-stat-grid">
        {[
          {
            label: "任务记录",
            value: summary ? count : "—",
            detail: "来自本地任务仓库",
            icon: Route,
          },
          {
            label: "正在执行",
            value: summary
              ? summary.tasks.filter((t) =>
                  ["executing", "accepted"].includes(t.execution?.state || ""),
                ).length
              : "—",
            detail: "以执行端实际状态为准",
            icon: Activity,
          },
          {
            label: "自定义规划",
            value: summary?.planning_tasks.length ?? "—",
            detail: "独立任务 API 已接入",
            icon: Map,
          },
          {
            label: "当前角色",
            value: user.role_name,
            detail: "操作权限由服务端校验",
            icon: ShieldCheck,
          },
        ].map((s) => (
          <div className="p-stat" key={s.label}>
            <div>
              {s.label}
              <s.icon size={17} />
            </div>
            <strong>{s.value}</strong>
            <small>{s.detail}</small>
          </div>
        ))}
      </div>
      <div className="p-dashboard-columns">
        <section className="p-card">
          <div className="p-card-head">
            <div>
              <h2>最近任务</h2>
              <p>关注任务状态，继续未完成的工作。</p>
            </div>
            <button className="p-text-button" onClick={() => go("/missions")}>
              查看全部
              <ArrowRight size={14} />
            </button>
          </div>
          {!summary ? (
            <div className="p-summary-loading" role="status">
              <LoaderCircle size={23} className="p-spin" />
              <span>正在读取任务记录…</span>
            </div>
          ) : summary.tasks.length ? (
            <TaskRows tasks={summary.tasks.slice(0, 4)} />
          ) : (
            <Empty title="工作区已准备好">
              <p>创建第一个任务后，进度与回执会显示在这里。</p>
            </Empty>
          )}
        </section>
        <section className="p-card">
          <div className="p-card-head">
            <div>
              <h2>模块连接</h2>
              <p>真实服务状态，清楚了解接入边界。</p>
            </div>
            <span className="p-tag">本地</span>
          </div>
          <div className="p-service-list">
            {summary?.services.map((s) => (
              <div key={s.name}>
                <span
                  className={`p-service-dot ${s.status === "pending" ? "pending" : ""}`}
                />
                <div>
                  <strong>{s.name}</strong>
                  <p>{s.detail}</p>
                </div>
                <span>
                  {s.status === "pending"
                    ? "待接入"
                    : s.status === "configured"
                      ? "已配置"
                      : "可用"}
                </span>
              </div>
            )) || <p>正在读取模块状态…</p>}
          </div>
        </section>
      </div>
      <div className="p-section-title compact">
        <h2>你的工作入口</h2>
        <span>核心功能，一步到达</span>
      </div>
      <div className="p-module-grid">
        {modules
          .filter((m) => can(m.permission))
          .map((m) => (
            <button
              className="p-module-card"
              key={m.path}
              onClick={() => go(m.path)}
            >
              <div>
                <m.icon size={22} />
                <span>{m.index}</span>
              </div>
              <h3>
                {m.title}
                <ArrowRight size={16} />
              </h3>
              <p>{m.description}</p>
            </button>
          ))}
      </div>
    </>
  );
}

export function TaskRows({ tasks }: { tasks: DispatchTask[] }) {
  const { go } = usePortal();
  return (
    <div className="p-task-rows">
      {tasks.map((t) => (
        <button key={t.task_id} onClick={() => go("/missions/" + t.task_id)}>
          <span className="p-task-icon">
            <Route size={18} />
          </span>
          <div>
            <strong>{t.scenario_id} · 低空任务</strong>
            <p>
              {t.task_id.slice(0, 8)} ·{" "}
              {t.execution?.plan_version || "尚未生成版本"}
            </p>
          </div>
          <span
            className={`p-status ${t.planning_status === "blocked" || ["failed", "rejected"].includes(t.execution?.state || "") ? "warning" : ""}`}
          >
            {stateLabel(t.execution?.state || t.planning_status)}
          </span>
          <ChevronRight size={16} />
        </button>
      ))}
    </div>
  );
}

function Analytics() {
  const { summary, go, toast } = usePortal();
  return (
    <>
      <PageTitle
        eyebrow="TRACEABLE BY DESIGN"
        title="运行记录"
        description="从任务到回执，保留每一次决策的依据。"
        action={
          <Button
            onClick={() => {
              downloadJson(summary, "aeris-workspace-summary.json");
              toast("工作区摘要已导出");
            }}
            disabled={!summary}
          >
            <ArrowDownToLine size={16} />
            导出工作区摘要
          </Button>
        }
      />
      <div className="p-info">
        <ShieldCheck size={19} />
        <p>
          这里展示真实本地接口的记录。进入任务详情可查看工具调用、执行回执并导出完整证据；这些记录属于合成联调。
        </p>
      </div>
      <section className="p-card">
        <div className="p-card-head">
          <h2>任务证据</h2>
          <span className="p-tag">{summary?.tasks.length || 0} 条记录</span>
        </div>
        {summary?.tasks.length ? (
          <TaskRows tasks={summary.tasks} />
        ) : (
          <Empty title="还没有运行记录">
            <p>完成一次任务，规划、校验和回执就会归档于此。</p>
            <Button onClick={() => go("/missions")}>
              查看任务中心
              <ArrowRight size={15} />
            </Button>
          </Empty>
        )}
      </section>
      <section className="p-card p-spaced">
        <div className="p-card-head">
          <h2>独立规划记录</h2>
        </div>
        {summary?.planning_tasks.length ? (
          <div className="p-task-rows">
            {summary.planning_tasks.map((t) => (
              <button
                key={t.task_id}
                onClick={() => go("/missions/plan/" + t.task_id)}
              >
                <Map size={20} />
                <div>
                  <strong>{t.task_id}</strong>
                  <p>自定义仿真任务 · {t.vehicle_type}</p>
                </div>
                <ChevronRight size={16} />
              </button>
            ))}
          </div>
        ) : (
          <Empty title="暂无自定义规划" />
        )}
      </section>
    </>
  );
}
function HelpPage() {
  const { go, can } = usePortal();
  return (
    <>
      <PageTitle
        title="从第一项任务开始"
        description="不需要一次了解所有功能。先完成一个小目标，再逐步探索。"
      />
      <div className="p-help-grid">
        {[
          {
            icon: Route,
            title: "创建并运行第一项任务",
            text: "在任务中心选择“场景联调”，核对起终点和合成参数，再确认运行。系统自动调用 M3、M2、独立校验和本地 M4。",
            path: "/missions/new",
            action: "开始创建",
            permission: "task.create",
          },
          {
            icon: Map,
            title: "在真实地图上定位",
            text: "进入空域态势，点击定位按钮。支持浏览器定位、地名搜索与经纬度输入。地图目的地保存为草稿，完成坐标标定前不会下发飞控。",
            path: "/airspace",
            action: "打开地图",
            permission: "map.read",
          },
          {
            icon: Radio,
            title: "查看设备实时遥测",
            text: "设备页默认读取本地遥测文件流。未配置或数据过期时显示实际连接状态。演示回放与遥测源明确区分。",
            path: "/fleet",
            action: "查看设备",
            permission: "telemetry.read",
          },
          {
            icon: Compass,
            title: "比较航线与导航演练",
            text: "在飞行导航中计算场景方案或导入真实坐标航线。比较后启用参考引导，查看下一航点、偏航提示与高度剖面；视图操作不下发飞控。",
            path: "/airspace?navigation=1",
            action: "打开飞行导航",
            permission: "map.read",
          },
          {
            icon: ShieldCheck,
            title: "邀请团队与保护账户",
            text: "在账户页完成邮箱验证并设置 MFA。管理员可在身份与访问中邀请成员并选择角色；邀请码绑定邮箱，48小时有效，仅可使用一次。",
            path: "/account",
            action: "配置账户",
            permission: "workspace.read",
          },
        ].map((h) => (
          <section className="p-card p-help-card" key={h.title}>
            <h.icon size={24} />
            <h2>{h.title}</h2>
            <p>{h.text}</p>
            {can(h.permission) && (
              <Button onClick={() => go(h.path)}>
                {h.action}
                <ArrowRight size={15} />
              </Button>
            )}
          </section>
        ))}
      </div>
      <div className="p-info">
        <HelpCircle size={19} />
        <p>
          随时按 Ctrl / ⌘ K
          查找模块。任务流程可保存草稿并稍后继续；地图组件可在“组件管理”中按需显示。
        </p>
      </div>
    </>
  );
}

export default function Portal() {
  const [path, setPath] = useState(location.pathname + location.search),
    [user, setUser] = useState<User | null>(null),
    [policy, setPolicy] = useState<Policy | null>(null),
    [loading, setLoading] = useState(true),
    [summary, setSummary] = useState<Summary | null>(null),
    [summaryError, setSummaryError] = useState(""),
    [notice, setNotice] = useState(""),
    [collapsed, setCollapsed] = useState(false),
    [mobileMenu, setMobileMenu] = useState(false),
    [search, setSearch] = useState(false),
    [query, setQuery] = useState(""),
    [notifications, setNotifications] = useState(false),
    [account, setAccount] = useState(false),
    // Declared before any early return: hooks must run in the same order on
    // every render, including the loading and unauthenticated paths.
    [portalAssistantOpen, setPortalAssistantOpen] = useState(false);
  const commandRef = useRef<HTMLElement>(null);
  const searchTrigger = useRef<HTMLElement | null>(null);
  function go(to: string) {
    if (to !== location.pathname + location.search)
      history.pushState({}, "", to);
    setPath(to);
    setSearch(false);
    setAccount(false);
    setNotifications(false);
    setMobileMenu(false);
    window.scrollTo({ top: 0, behavior: "instant" });
  }
  async function refreshUser() {
    try {
      const value = await api<{ user: User }>("/auth/me");
      setUser(value.user);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) setUser(null);
      throw error;
    }
  }
  async function refreshSummary() {
    try {
      setSummary(await api<Summary>("/workspace/summary"));
      setSummaryError("");
    } catch (e) {
      setSummaryError(message(e));
    }
  }
  useEffect(() => {
    let active = true;
    Promise.allSettled([
      api<Policy>("/auth/policy"),
      api<{ user: User }>("/auth/me"),
    ]).then(([p, u]) => {
      if (!active) return;
      if (p.status === "fulfilled") setPolicy(p.value);
      if (u.status === "fulfilled") setUser(u.value.user);
      setLoading(false);
    });
    const pop = () => setPath(location.pathname + location.search);
    window.addEventListener("popstate", pop);
    return () => {
      active = false;
      window.removeEventListener("popstate", pop);
    };
  }, []);
  useEffect(() => {
    if (!user) {
      setSummary(null);
      return;
    }
    void refreshSummary();
    const id = setInterval(() => void refreshSummary(), 7000);
    const unauthorized = () => {
      setUser(null);
      setSummary(null);
    };
    window.addEventListener("aeris:unauthorized", unauthorized);
    return () => {
      clearInterval(id);
      window.removeEventListener("aeris:unauthorized", unauthorized);
    };
  }, [user?.id]);
  useEffect(() => {
    if (!notice) return;
    const id = setTimeout(() => setNotice(""), 4500);
    return () => clearTimeout(id);
  }, [notice]);
  useEffect(() => {
    const viewport = window.matchMedia("(max-width: 700px)");
    const resize = () => {
      if (!viewport.matches) setMobileMenu(false);
    };
    viewport.addEventListener("change", resize);
    return () => viewport.removeEventListener("change", resize);
  }, []);
  useEffect(() => {
    if (!mobileMenu) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const frame = requestAnimationFrame(() => {
      document
        .querySelector<HTMLButtonElement>(".p-sidebar-brand > button")
        ?.focus();
    });
    const trap = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const elements = Array.from(
        document.querySelectorAll<HTMLElement>(
          ".p-sidebar button:not([disabled]),.p-sidebar a[href]",
        ),
      ).filter((element) => element.getClientRects().length > 0);
      const first = elements[0],
        last = elements.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", trap);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("keydown", trap);
      document.body.style.overflow = previousOverflow;
      document.querySelector<HTMLButtonElement>(".p-mobile-toggle")?.focus();
    };
  }, [mobileMenu]);
  useEffect(() => {
    if (!search) return;
    searchTrigger.current = document.activeElement as HTMLElement | null;
    const trap = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const elements = commandRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]),input,a[href],[tabindex="0"]',
      );
      if (!elements?.length) return;
      const first = elements[0],
        last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", trap);
    return () => {
      document.removeEventListener("keydown", trap);
      searchTrigger.current?.focus();
    };
  }, [search]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearch((v) => !v);
      }
      if (e.key === "Escape") {
        setSearch(false);
        setAccount(false);
        setNotifications(false);
        setMobileMenu(false);
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  const pathname = path.split("?")[0];
  const publicPage = ["/", "/login", "/register"].includes(pathname);
  useEffect(() => {
    if (!loading && !user && !publicPage)
      go("/login?next=" + encodeURIComponent(path));
  }, [loading, user, publicPage, path]);
  const can = (permission: string) => !!user?.permissions.includes(permission);
  const current =
    pages.find((p) => p.path === pathname) ||
    pages.find((p) => pathname.startsWith(p.path + "/"));
  const required =
    pathname === "/missions/new" ? "task.create" : current?.permission;
  if (loading) return <Loading />;
  if (pathname === "/") return <Landing go={go} user={user} />;
  if (pathname === "/login" || pathname === "/register")
    return (
      <AuthPage
        key={pathname}
        path={path}
        go={go}
        policy={policy}
        refresh={async () => {
          await refreshUser();
          setPolicy(await api<Policy>("/auth/policy"));
        }}
      />
    );
  if (!user) return <Loading />;
  const activeTitle =
    pathname === "/missions/new"
      ? "创建任务"
      : pathname.startsWith("/missions/plan/")
        ? "航线规划详情"
        : pathname.startsWith("/missions/")
          ? "任务详情"
          : current?.title || "页面未找到";
  const isConsole = pathname === "/airspace" || pathname === "/fleet";
  let content: ReactNode;
  if (required && !can(required))
    content = (
      <Empty title="当前角色无法访问此页面" icon={ShieldCheck}>
        <p>请联系管理员调整权限，或返回工作台。</p>
        <Button onClick={() => go("/workspace")}>返回工作台</Button>
      </Empty>
    );
  else if (pathname === "/workspace") content = <Dashboard />;
  else if (pathname === "/missions") content = <MissionList />;
  else if (pathname === "/missions/new") content = <MissionWizard />;
  else if (pathname.startsWith("/missions/"))
    content = (
      <TaskDetail
        key={pathname}
        taskId={pathname.split("/").at(-1)!}
        planning={pathname.startsWith("/missions/plan/")}
      />
    );
  else if (isConsole)
    content = (
      <Suspense fallback={<Loading />}>
        <Console
          key={pathname}
          embedded
          readOnly={!can("task.create")}
          initialLive={pathname === "/fleet"}
          initialMapKind={
            new URLSearchParams(window.location.search).get("map") ===
            "shenzhen"
              ? "shenzhen"
              : undefined
          }
        />
      </Suspense>
    );
  else if (pathname === "/aircraft")
    content = (
      <Suspense fallback={<Loading />}>
        <AircraftLibrary onNavigate={go} />
      </Suspense>
    );
  else if (pathname === "/analytics") content = <Analytics />;
  else if (pathname.startsWith("/identity/"))
    content = <IdentityPage rolesOnly={pathname.endsWith("/roles")} />;
  else if (pathname === "/account") content = <AccountPage />;
  else if (pathname === "/help") content = <HelpPage />;
  else
    content = (
      <Empty title="这个页面暂不存在">
        <Button onClick={() => go("/workspace")}>返回工作台</Button>
      </Empty>
    );
  return (
    <Context.Provider
      value={{
        user,
        go,
        toast: setNotice,
        refreshUser,
        can,
        summary,
        refreshSummary,
      }}
    >
      <div
        data-area={
          pathname.startsWith("/missions")
            ? "missions"
            : pathname.startsWith("/identity") || pathname === "/account"
              ? "identity"
              : pathname === "/airspace"
                ? "airspace"
                : pathname === "/fleet"
                  ? "fleet"
                  : pathname === "/analytics"
                    ? "analytics"
                    : "workspace"
        }
        className={`p-shell ${collapsed ? "p-collapsed" : ""} ${mobileMenu ? "p-mobile-open" : ""}`}
      >
        {mobileMenu && (
          <button
            className="p-mobile-backdrop"
            aria-label="关闭导航"
            onClick={() => setMobileMenu(false)}
          />
        )}
        <aside className="p-sidebar" id="workspace-sidebar" inert={search}>
          <div className="p-sidebar-brand">
            <Brand go={go} />
            <button
              className="p-icon"
              aria-label="折叠导航"
              onClick={() => {
                setCollapsed(!collapsed);
                setMobileMenu(false);
              }}
            >
              <PanelLeftClose size={18} />
            </button>
          </div>
          <div
            className="p-workspace-select"
            title="当前使用 AERIS 团队本地工作区"
          >
            <span className="p-workspace-icon">A</span>
            <span>
              <strong>AERIS 团队</strong>
              <small>本地工作区</small>
            </span>
          </div>
          <nav aria-label="工作区导航">
            <p className="p-nav-group">工作空间</p>
            {pages
              .slice(0, 6)
              .filter((p) => can(p.permission))
              .map((p) => (
                <button
                  title={p.title}
                  key={p.path}
                  className={current?.path === p.path ? "active" : ""}
                  onClick={() => go(p.path)}
                >
                  <p.icon size={19} />
                  <span>{p.title}</span>
                  {p.path === "/missions" && !!summary?.tasks.length && (
                    <small>{summary.tasks.length}</small>
                  )}
                </button>
              ))}
            {can("identity.manage") && (
              <>
                <p className="p-nav-group">身份与访问</p>
                {pages.slice(6, 8).map((p) => (
                  <button
                    key={p.path}
                    title={p.title}
                    className={current?.path === p.path ? "active" : ""}
                    onClick={() => go(p.path)}
                  >
                    <p.icon size={18} />
                    <span>{p.title}</span>
                  </button>
                ))}
              </>
            )}
          </nav>
          <div className="p-sidebar-bottom">
            {can("map.read") && (
              <button
                className="p-guide-link"
                onClick={() => go("/airspace?map=shenzhen")}
              >
                <Compass size={17} />
                <span>深圳三维大厅</span>
              </button>
            )}
            <button
              className="p-guide-link"
              onClick={() => window.location.assign("/demo")}
            >
              <Sparkles size={17} />
              <span>竞赛演示回放</span>
            </button>
            <button className="p-guide-link" onClick={() => go("/help")}>
              <BookOpen size={18} />
              <span>新手使用指南</span>
              <ArrowRight size={15} />
            </button>
            <div className="p-local-badge">
              <span />
              本地工作区<small>v0.2</small>
            </div>
          </div>
        </aside>
        <div className="p-shell-main" inert={mobileMenu || search}>
          <header className="p-app-header">
            <button
              className="p-icon p-mobile-toggle"
              aria-label="展开导航"
              aria-expanded={mobileMenu}
              aria-controls="workspace-sidebar"
              onClick={() => setMobileMenu(!mobileMenu)}
            >
              <Menu size={20} />
            </button>
            {collapsed && (
              <button
                className="p-icon"
                aria-label="展开完整导航"
                onClick={() => setCollapsed(false)}
              >
                <Menu size={18} />
              </button>
            )}
            <div className="p-context">
              <span className="p-context-dot" />
              团队工作区
              <ChevronRight size={13} />
              <strong>{activeTitle}</strong>
            </div>
            <div className="p-header-tools">
              <ThemeToggle />
              <button
                className="p-global-search"
                onClick={() => setSearch(true)}
                aria-label="全局搜索"
              >
                <Search size={15} />
                <span>搜索功能、任务…</span>
                <kbd>⌘ K</kbd>
              </button>
              <button
                className="p-icon"
                title="帮助中心"
                aria-label="帮助中心"
                onClick={() => go("/help")}
              >
                <HelpCircle size={19} />
              </button>
              <div className="p-popover-wrap">
                <button
                  className="p-icon"
                  aria-label="通知"
                  onClick={() => {
                    setNotifications(!notifications);
                    setAccount(false);
                  }}
                >
                  <Bell size={19} />
                  {(!user.email_verified ||
                    summary?.dispatch.active_task_id) && <i />}
                </button>
                {notifications && (
                  <div className="p-popover p-notifications">
                    <h3>工作区通知</h3>
                    {!user.email_verified && (
                      <button onClick={() => go("/account")}>
                        <ShieldCheck size={17} />
                        <span>
                          完成邮箱验证<small>验证后可安全邀请团队成员</small>
                        </span>
                      </button>
                    )}
                    {summary?.dispatch.active_task_id && (
                      <button
                        onClick={() =>
                          go("/missions/" + summary.dispatch.active_task_id)
                        }
                      >
                        <Activity size={17} />
                        <span>
                          有一项任务尚未结束<small>查看执行状态与回执</small>
                        </span>
                      </button>
                    )}
                    <button onClick={() => go("/fleet")}>
                      <Radio size={17} />
                      <span>
                        核对设备接入状态
                        <small>
                          {summary?.services.find((s) => s.name === "飞控遥测")
                            ?.detail || "打开设备页查看"}
                        </small>
                      </span>
                    </button>
                  </div>
                )}
              </div>
              <span className="p-header-separator" />
              <div className="p-popover-wrap">
                <button
                  className="p-account-button"
                  aria-label="账户菜单"
                  onClick={() => {
                    setAccount(!account);
                    setNotifications(false);
                  }}
                >
                  <span>{user.name.slice(0, 1).toUpperCase()}</span>
                  <div>
                    <strong>{user.name}</strong>
                    <small>{user.role_name}</small>
                  </div>
                  <ChevronDown size={13} />
                </button>
                {account && (
                  <div className="p-popover">
                    <div className="p-account-email">
                      {user.email}
                      <small>
                        {user.email_verified ? "邮箱已验证" : "邮箱待验证"}
                      </small>
                    </div>
                    <button onClick={() => go("/account")}>
                      <ShieldCheck size={17} />
                      账户与安全
                    </button>
                    <button onClick={() => go("/")}>
                      <Compass size={17} />
                      产品首页
                    </button>
                    <button
                      onClick={() =>
                        void api("/auth/logout", {})
                          .then(() => {
                            setUser(null);
                            setSummary(null);
                            go("/login");
                          })
                          .catch((e) => setNotice(message(e)))
                      }
                    >
                      <LogOut size={17} />
                      退出 / 切换账户
                    </button>
                  </div>
                )}
              </div>
            </div>
          </header>
          <main className={`p-content ${isConsole ? "p-console-content" : ""}`}>
            <div className="p-breadcrumb">
              <button onClick={() => go("/workspace")}>工作台</button>
              {pathname !== "/workspace" && (
                <>
                  <ChevronRight size={13} />
                  {pathname.startsWith("/missions/") && (
                    <>
                      <button onClick={() => go("/missions")}>任务中心</button>
                      <ChevronRight size={13} />
                    </>
                  )}
                  <span>{activeTitle}</span>
                </>
              )}
            </div>
            {summaryError && (
              <div className="p-error" role="alert">
                模块状态读取失败：{summaryError}
                <button onClick={() => void refreshSummary()}>重新连接</button>
              </div>
            )}
            {content}
          </main>
          <footer className="p-app-footer">
            <span>AERIS · 低空智能调度平台</span>
            <span>本地运行 / 合成联调 · 飞控执行未启用</span>
          </footer>
        </div>
      </div>
      {!isConsole && (
        <Assistant
          open={portalAssistantOpen}
          onToggle={() => setPortalAssistantOpen((value) => !value)}
          context={PORTAL_ASSISTANT_CONTEXT}
          onDraft={() => true}
          onFocus={() => {}}
          onRoute={() => {}}
          onPanel={() => {}}
          onInjectTerrain={() => {}}
          onEvent={() => {}}
        />
      )}
      {notice && (
        <div className="p-toast" role="status">
          <CheckCircle2 size={19} />
          {notice}
          <button aria-label="关闭提示" onClick={() => setNotice("")}>
            <X size={16} />
          </button>
        </div>
      )}
      {search && (
        <div className="p-modal-backdrop" onClick={() => setSearch(false)}>
          <section
            ref={commandRef}
            className="p-command"
            role="dialog"
            aria-modal="true"
            aria-label="全局搜索"
            onClick={(e) => e.stopPropagation()}
          >
            <div>
              <Search size={21} />
              <input
                autoFocus
                placeholder="查找模块或任务编号…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              <button onClick={() => setSearch(false)} aria-label="关闭搜索">
                <kbd>ESC</kbd>
              </button>
            </div>
            <p className="p-kicker">快速到达</p>
            {pages
              .filter((p) => can(p.permission) && p.title.includes(query))
              .map((p) => (
                <button key={p.path} onClick={() => go(p.path)}>
                  <p.icon size={18} />
                  {p.title}
                  <ArrowRight size={15} />
                </button>
              ))}
            {summary?.tasks
              .filter(
                (t) =>
                  query &&
                  (t.task_id.includes(query) ||
                    t.scenario_id.toLowerCase().includes(query.toLowerCase())),
              )
              .slice(0, 5)
              .map((t) => (
                <button
                  key={t.task_id}
                  onClick={() => go("/missions/" + t.task_id)}
                >
                  <Route size={18} />
                  {t.scenario_id} · {t.task_id.slice(0, 8)}
                  <ArrowRight size={15} />
                </button>
              ))}
            {query &&
              !pages.some(
                (p) => can(p.permission) && p.title.includes(query),
              ) &&
              !summary?.tasks.some(
                (t) =>
                  t.task_id.includes(query) ||
                  t.scenario_id.toLowerCase().includes(query.toLowerCase()),
              ) && (
                <p className="p-search-empty">
                  没有匹配结果，请试试“任务”或任务编号。
                </p>
              )}
            <footer>
              <Command size={13} />
              快捷键 Ctrl / ⌘ K 打开 · Esc 关闭
            </footer>
          </section>
        </div>
      )}
    </Context.Provider>
  );
}
