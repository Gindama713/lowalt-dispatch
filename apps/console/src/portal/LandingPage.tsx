import { lazy, Suspense, useId, useState } from "react";
import {
  Activity,
  ArrowDown,
  ArrowRight,
  Box,
  Check,
  CheckCircle2,
  ChevronRight,
  Compass,
  Cpu,
  FileBarChart2,
  Layers3,
  Map,
  MoveUpRight,
  Orbit,
  Play,
  Radio,
  Route,
  ShieldCheck,
  Sparkles,
  Users,
} from "lucide-react";
import type { User } from "./api";
import { ThemeToggle } from "./Theme";
import "./landing.css";

const ShenzhenCityScene = lazy(() => import("../ShenzhenCityScene"));

const capabilities = [
  {
    path: "/missions",
    title: "任务中心",
    subtitle: "让复杂任务，有序发生。",
    description: "从场景选择、参数审核到规划与执行回执，一条清晰的任务流。",
    icon: Route,
    tone: "blue",
    number: "01",
  },
  {
    path: "/airspace",
    title: "空域态势",
    subtitle: "从全局，看到每个细节。",
    description: "真实地图、二维与三维视角，叠加天气、地形和航线信息。",
    icon: Map,
    tone: "teal",
    number: "02",
  },
  {
    path: "/fleet",
    title: "设备与遥测",
    subtitle: "每一次变化，都有来源。",
    description: "汇集飞行参数与设备状态，清楚区分实时遥测、过期数据与演示。",
    icon: Radio,
    tone: "violet",
    number: "03",
  },
  {
    path: "/analytics",
    title: "运行记录",
    subtitle: "让每个决定，都可追溯。",
    description: "串联任务版本、工具调用、校验与回执，随时查看并导出完整记录。",
    icon: FileBarChart2,
    tone: "amber",
    number: "04",
  },
];

function SpatialCanvas({ variant = 0 }: { variant?: number }) {
  const prefix = useId().replace(/:/g, "");
  const id = (name: string) => `${prefix}-${name}`;
  const paint = (name: string) => `url(#${id(name)})`;
  const buildings = Array.from({ length: 23 }, (_, i) => ({
    x: 124 + (i % 6) * 83 + (Math.floor(i / 6) % 2) * 27,
    y: 221 + Math.floor(i / 6) * 56 - (i % 6) * 16,
    w: 28 + ((i * 7) % 30),
    h: 22 + ((i * 13) % 64),
  }));
  return (
    <svg
      className="l-spatial-canvas"
      viewBox="0 0 860 610"
      fill="none"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={id("l-city-top")} x2="1" y2="1">
          <stop stopColor="#d6d8ff" />
          <stop offset="1" stopColor="#a8c7ef" />
        </linearGradient>
        <linearGradient id={id("l-city-side")} x2="0" y2="1">
          <stop stopColor="#a7a7ed" stopOpacity=".75" />
          <stop offset="1" stopColor="#7f91d3" stopOpacity=".16" />
        </linearGradient>
        <radialGradient id={id("l-field")}>
          <stop stopColor="#9ed9fc" stopOpacity=".21" />
          <stop offset="1" stopColor="#8678e5" stopOpacity="0" />
        </radialGradient>
        <linearGradient id={id("l-route")} x2="1" y2="1">
          <stop stopColor="#6df5dc" />
          <stop offset="1" stopColor="#b0d0ff" />
        </linearGradient>
        <filter id={id("l-glow")}>
          <feGaussianBlur stdDeviation="5" />
        </filter>
        <pattern
          id={id("l-net")}
          width="42"
          height="42"
          patternUnits="userSpaceOnUse"
        >
          <path d="M42 0H0V42" stroke="#a6bcf0" strokeOpacity=".2" />
        </pattern>
      </defs>
      <ellipse cx="425" cy="347" rx="375" ry="191" fill={paint("l-field")} />
      <g transform="translate(80 197) matrix(1 .32 -1 .32 265 -10)">
        <rect width="460" height="460" fill={paint("l-net")} />
        <rect
          x="-35"
          y="-35"
          width="530"
          height="530"
          stroke="#b6c8fc"
          strokeOpacity=".16"
        />
        <rect
          x="-70"
          y="-70"
          width="600"
          height="600"
          stroke="#b6c8fc"
          strokeOpacity=".07"
        />
      </g>
      <g className="l-city-buildings">
        {buildings.map((b, i) => (
          <g key={i} opacity={i % 3 === 0 ? 0.7 : 0.9}>
            <path
              d={`M${b.x} ${b.y - b.h}l${b.w} 14-${b.w} 14-${b.w}-14Z`}
              fill={paint("l-city-top")}
            />
            <path
              d={`M${b.x - b.w} ${b.y - b.h}l${b.w} 14v${b.h}l-${b.w}-14Z`}
              fill={paint("l-city-side")}
            />
            <path
              d={`M${b.x} ${b.y - b.h + 14}l${b.w}-14v${b.h}l-${b.w} 14Z`}
              fill="#657fbe"
              fillOpacity=".37"
            />
            <path
              d={`M${b.x - b.w + 5} ${b.y - b.h + 9}l${b.w - 10} 9M${b.x - b.w + 5} ${b.y - b.h + 18}l${b.w - 10} 9`}
              stroke="#d2e7ff"
              strokeOpacity=".25"
            />
          </g>
        ))}
      </g>
      <ellipse
        cx="420"
        cy="325"
        rx="256"
        ry="125"
        stroke="#aad9f6"
        strokeOpacity=".12"
      />
      <ellipse
        cx="420"
        cy="325"
        rx="282"
        ry="143"
        stroke="#aad9f6"
        strokeOpacity=".2"
        strokeDasharray="3 9"
        className="l-orbit-line"
      />
      <path
        id={id("l-flight-path")}
        d={
          variant === 1
            ? "M154 363 246 318 340 350 421 288 550 323 680 250"
            : "M154 363 247 391 368 330 405 254 538 212 680 250"
        }
        stroke="#62e7cf"
        strokeWidth="11"
        strokeOpacity=".14"
        filter={paint("l-glow")}
      />
      <path
        d={
          variant === 1
            ? "M154 363 246 318 340 350 421 288 550 323 680 250"
            : "M154 363 247 391 368 330 405 254 538 212 680 250"
        }
        stroke={paint("l-route")}
        strokeWidth="2.3"
        strokeDasharray="6 5"
        className="l-route-motion"
      />
      {[
        [154, 363],
        [680, 250],
      ].map(([x, y], i) => (
        <g key={i}>
          <ellipse
            cx={x}
            cy={y}
            rx="16"
            ry="7"
            fill="#70e8d1"
            fillOpacity=".12"
            stroke="#8fe7db"
            strokeOpacity=".5"
          />
          <circle cx={x} cy={y} r="4" fill="#b5ffed" />
          <path
            d={`M${x} ${y - 6}v-40`}
            stroke="#b3d9f2"
            strokeOpacity=".35"
            strokeDasharray="3 4"
          />
          <text
            x={x - 9}
            y={y - 55}
            fill="#c8dcf9"
            fontSize="10"
            fontFamily="monospace"
          >
            {i ? "DESTINATION" : "ORIGIN"}
          </text>
        </g>
      ))}
      <g className="l-drone-float">
        <path
          d="M422 141v136"
          stroke="#b9e7ff"
          strokeOpacity=".3"
          strokeDasharray="3 6"
        />
        <ellipse
          cx="422"
          cy="279"
          rx="28"
          ry="9"
          fill="#98f4de"
          fillOpacity=".07"
          stroke="#9de9df"
          strokeOpacity=".35"
        />
        <g transform="translate(422 140)">
          <ellipse
            cy="7"
            rx="75"
            ry="22"
            fill="#a1cfff"
            fillOpacity=".13"
            filter={paint("l-glow")}
          />
          <path
            d="m-38-14 76 28m-76 0 76-28"
            stroke="#d7e9ff"
            strokeWidth="8"
            strokeLinecap="round"
          />
          <g fill="#dce9ff" fillOpacity=".1" stroke="#d9edff" strokeWidth="1.2">
            {[
              [-43, -17],
              [43, -17],
              [-43, 17],
              [43, 17],
            ].map(([x, y]) => (
              <ellipse key={x + ":" + y} cx={x} cy={y} rx="24" ry="10" />
            ))}
          </g>
          <path d="M-13-16h26l7 25-20 10-20-10Z" fill="#eff5ff" />
          <path d="M-6-5h12" stroke="#5f8ef5" strokeWidth="2" />
          <circle cy="14" r="3" fill="#5b8df2" />
        </g>
      </g>
      <path
        d="M623 100h-46l-30 27M642 410h-42l-28-24"
        stroke="#bccaf4"
        strokeOpacity=".35"
      />
      <text x="630" y="104" fill="#dceaff" fontSize="9" letterSpacing="2">
        AIRSPACE / AERIS
      </text>
      <text x="650" y="414" fill="#dceaff" fontSize="9" letterSpacing="1">
        ROUTE VISUALIZATION
      </text>
    </svg>
  );
}

export default function LandingPage({
  go,
  user,
}: {
  go: (path: string) => void;
  user: User | null;
}) {
  const [scene, setScene] = useState(0);
  const destination = (path: string) =>
    go(user ? path : "/login?next=" + encodeURIComponent(path));
  const scenes = [
    {
      name: "低空配送",
      icon: Route,
      title: "从出发，到抵达。",
      text: "围绕起终点、载荷与可用能量，验证配送任务的规划和回执链路。",
      tags: ["场景任务", "路线审核", "执行回执"],
    },
    {
      name: "园区巡检",
      icon: Compass,
      title: "复杂空间，清晰掌握。",
      text: "在地图中了解空间、地形与天气信息，为巡检任务积累可复核的规划依据。",
      tags: ["地图定位", "地形视角", "风险信息"],
    },
    {
      name: "应急响应",
      icon: ShieldCheck,
      title: "面对变化，留有下一步。",
      text: "在仿真场景中观察限制区与备降条件变化，记录安全校验与处置结果。",
      tags: ["动态限制", "安全校验", "决策追溯"],
    },
  ];
  return (
    <div className="aeris-home">
      <header className="l-header">
        <div className="l-header-inner">
          <a
            className="l-brand"
            href="/"
            onClick={(e) => {
              e.preventDefault();
              go("/");
            }}
          >
            <Orbit size={28} />
            <strong>
              AERIS<span>低空智能调度</span>
            </strong>
          </a>
          <nav aria-label="产品导航">
            <a href="#capabilities">产品能力</a>
            <a href="#scenarios">应用场景</a>
            <a href="#workflow">工作方式</a>
            <button onClick={() => destination("/help")}>使用指南</button>
          </nav>
          <div className="l-account">
            <ThemeToggle />
            <button onClick={() => go(user ? "/workspace" : "/login")}>
              {user ? "工作台" : "登录"}
              <ArrowRight size={15} />
            </button>
            <button className="l-outline" onClick={() => go("/register")}>
              免费试用
            </button>
          </div>
        </div>
      </header>
      <main>
        <section className="l-hero">
          <div className="l-hero-halo" />
          <div className="l-hero-lines" aria-hidden="true">
            <svg viewBox="0 0 1600 720" preserveAspectRatio="none">
              <path d="M0 560C430 610 470 10 1600 110M0 630C520 700 580 50 1600 190M0 720C480 740 820 120 1600 270" />
            </svg>
          </div>
          <div className="l-product-nav">
            <span>
              <Box size={15} />
              AERIS PLATFORM
            </span>
            <div>
              <span>本地工作区</span>
              <i />
              <span>任务全流程协同</span>
            </div>
          </div>
          <div className="l-hero-inner">
            <div className="l-hero-copy">
              <div className="l-announcement">
                <span>
                  <Sparkles size={12} />
                </span>
                空间感知，让决策更进一步
                <ChevronRight size={13} />
              </div>
              <p className="l-eyebrow">A CLEARER WAY TO FLY</p>
              <h1>
                让每一次低空任务，
                <br />
                <em>都有清晰的下一步。</em>
              </h1>
              <p className="l-hero-description">
                从空间感知，到任务决策。
                <br />
                在一个工作区，连接任务、空域与团队，
                <br />
                让每一次出发，都有依据可循。
              </p>
              <div className="l-hero-actions">
                <button
                  className="p-hero-cta l-primary"
                  onClick={() => destination("/missions/new")}
                >
                  创建第一个任务
                  <ArrowRight size={19} />
                </button>
                <a href="/console">
                  <Orbit size={15} />
                  进入深圳三维调度台
                </a>
                <a href="/demo">
                  <Play size={14} />
                  观看竞赛演示
                </a>
              </div>
              <div className="l-hero-trust">
                <span>
                  <ShieldCheck size={14} />
                  安全校验
                </span>
                <span>
                  <Layers3 size={14} />
                  清晰流程
                </span>
                <span>
                  <FileBarChart2 size={14} />
                  全程追溯
                </span>
              </div>
            </div>
            <div
              className="l-hero-visual"
              id="hero-model-slot"
              data-model-slot="hero"
              aria-label="深圳湾艺术三维。不是实测空域或实飞"
            >
              <Suspense fallback={<SpatialCanvas />}>
                <ShenzhenCityScene variant="hero" />
              </Suspense>
              <div className="l-visual-tag l-tag-top">
                <span className="l-tag-icon">
                  <Route size={17} />
                </span>
                <div>
                  <strong>任务与空间，同步连接</strong>
                  <small>MISSION × SPATIAL INTELLIGENCE</small>
                </div>
                <CheckCircle2 size={15} />
              </div>
              <div className="l-visual-tag l-tag-bottom">
                <span className="l-tag-icon violet">
                  <ShieldCheck size={18} />
                </span>
                <div>
                  <strong>每一步决策，都有依据</strong>
                  <small>规划 · 校验 · 回执 · 追溯</small>
                </div>
              </div>
              <div className="l-model-caption">
                <span />
                <span>深圳湾艺术场景 · 非测绘坐标，不是实飞</span>
                <MoveUpRight size={13} />
              </div>
            </div>
          </div>
          <div className="l-hero-bottom">
            <span>
              <i />
              DESIGNED FOR EVERY NEXT MOVE
            </span>
            <a href="#capabilities">
              向下探索
              <ArrowDown size={14} />
            </a>
          </div>
        </section>
        <div className="l-capability-strip">
          <span>一条链路，连接完整决策。</span>
          {[
            { icon: Cpu, label: "任务 Agent" },
            { icon: Route, label: "航线规划" },
            { icon: ShieldCheck, label: "独立校验" },
            { icon: Radio, label: "执行回执" },
            { icon: Activity, label: "状态追踪" },
          ].map((item, i) => (
            <div key={item.label}>
              <item.icon size={19} />
              <strong>{item.label}</strong>
              {i < 4 && <ChevronRight size={13} />}
            </div>
          ))}
        </div>
        <section className="l-section l-capabilities" id="capabilities">
          <div className="l-section-heading">
            <div>
              <p className="l-eyebrow">ONE PLATFORM. EVERY PERSPECTIVE.</p>
              <h2>每个关键环节，都在你的掌握之中。</h2>
              <p>从第一次创建任务，到每一次结果复核，让协作始终保持清晰。</p>
            </div>
            <span>
              为完整任务链路而设计
              <MoveUpRight size={16} />
            </span>
          </div>
          <div className="l-feature-grid">
            {capabilities.map((c) => (
              <a
                key={c.path}
                className={`l-feature-card l-tone-${c.tone}`}
                href={c.path}
                onClick={(e) => {
                  e.preventDefault();
                  destination(c.path);
                }}
              >
                <div className="l-feature-visual">
                  <span className="l-feature-orbit" />
                  <c.icon size={48} strokeWidth={1.1} />
                  <span className="l-feature-index">{c.number} / AERIS</span>
                  <div className="l-feature-lines">
                    <i />
                    <i />
                    <i />
                  </div>
                </div>
                <div className="l-feature-text">
                  <span>
                    {c.title}
                    <ArrowRight size={17} />
                  </span>
                  <h3>{c.subtitle}</h3>
                  <p>{c.description}</p>
                </div>
              </a>
            ))}
          </div>
        </section>
        <section className="l-scenarios" id="scenarios">
          <div className="l-section">
            <div className="l-section-heading">
              <div>
                <p className="l-eyebrow">BUILT AROUND YOUR SCENARIO</p>
                <h2>以真实需求为起点，探索低空的更多可能。</h2>
                <p>从公开地图与仿真场景开始，逐步验证你的业务流程。</p>
              </div>
            </div>
            <div
              className="l-scenario-tabs"
              role="tablist"
              aria-label="应用场景"
            >
              {scenes.map((s, i) => (
                <button
                  key={s.name}
                  role="tab"
                  aria-selected={scene === i}
                  aria-controls="scenario-content"
                  id={"scenario-tab-" + i}
                  tabIndex={scene === i ? 0 : -1}
                  onClick={() => setScene(i)}
                  onKeyDown={(event) => {
                    const next =
                      event.key === "Home"
                        ? 0
                        : event.key === "End"
                          ? scenes.length - 1
                          : event.key === "ArrowRight"
                            ? (i + 1) % scenes.length
                            : event.key === "ArrowLeft"
                              ? (i + scenes.length - 1) % scenes.length
                              : null;
                    if (next === null) return;
                    event.preventDefault();
                    setScene(next);
                    document.getElementById("scenario-tab-" + next)?.focus();
                  }}
                >
                  <s.icon size={17} />
                  {s.name}
                  <span>0{i + 1}</span>
                </button>
              ))}
            </div>
            <div
              className="l-scenario-panel"
              id="scenario-content"
              role="tabpanel"
              aria-labelledby={"scenario-tab-" + scene}
            >
              <div className="l-scenario-copy" key={scene}>
                <span className="l-small-label">
                  应用方向 / {scenes[scene].name}
                </span>
                <h3>{scenes[scene].title}</h3>
                <p>{scenes[scene].text}</p>
                <div className="l-scenario-tags">
                  {scenes[scene].tags.map((t) => (
                    <span key={t}>
                      <Check size={13} />
                      {t}
                    </span>
                  ))}
                </div>
                <button
                  onClick={() =>
                    destination(scene === 1 ? "/airspace" : "/missions/new")
                  }
                >
                  {scene === 1 ? "探索空域态势" : "从场景任务开始"}
                  <ArrowRight size={16} />
                </button>
                <small>应用流程示意，当前执行采用本地合成联调。</small>
              </div>
              <div className="l-scenario-art">
                <SpatialCanvas variant={scene} />
                <span>
                  <i />
                  SPATIAL WORKFLOW / 0{scene + 1}
                </span>
              </div>
            </div>
          </div>
        </section>
        <section className="l-section l-workflow" id="workflow">
          <div className="l-section-heading">
            <div>
              <p className="l-eyebrow">CONFIDENCE, STEP BY STEP</p>
              <h2>第一次使用，也能从容开始。</h2>
              <p>一次只关注当前步骤，让下一步始终清晰可见。</p>
            </div>
            <button onClick={() => destination("/help")}>
              打开新手指南
              <ArrowRight size={16} />
            </button>
          </div>
          <div className="l-workflow-grid">
            {[
              {
                icon: FlagIcon,
                title: "选择场景，定义目标",
                text: "选择已有场景，明确任务起终点；也可以输入自己的仿真参数。",
                step: "01",
                tone: "blue",
              },
              {
                icon: ShieldCheck,
                title: "核对参数，再做决定",
                text: "逐项核对运行边界，人工确认后启动规划与独立安全校验。",
                step: "02",
                tone: "teal",
              },
              {
                icon: FileBarChart2,
                title: "查看结果，追溯依据",
                text: "获得明确状态与执行回执，查看审计、导出记录或创建下一项任务。",
                step: "03",
                tone: "violet",
              },
            ].map((w) => (
              <div className={"l-workflow-card l-tone-" + w.tone} key={w.step}>
                <div>
                  <span>{w.step}</span>
                  <w.icon size={22} />
                </div>
                <h3>{w.title}</h3>
                <p>{w.text}</p>
              </div>
            ))}
          </div>
        </section>
        <section className="l-bottom-note">
          <div>
            <span className="l-bottom-symbol">
              <Orbit size={45} strokeWidth={1} />
            </span>
            <div>
              <p className="l-eyebrow">INTELLIGENCE, WITH CONFIDENCE</p>
              <h2>把复杂留给系统，把从容留给团队。</h2>
              <p>本地部署起步，角色权限守护，任务证据随时可查。</p>
            </div>
          </div>
          <div className="l-bottom-points">
            <span>
              <Users size={17} />
              团队协作
            </span>
            <span>
              <ShieldCheck size={17} />
              角色权限
            </span>
            <span>
              <Cpu size={17} />
              本地运行
            </span>
          </div>
        </section>
      </main>
      <footer className="l-footer">
        <a
          className="l-brand"
          href="/"
          onClick={(e) => {
            e.preventDefault();
            go("/");
          }}
        >
          <Orbit size={23} />
          <strong>AERIS</strong>
        </a>
        <span>低空智能调度平台</span>
        <div>
          <button onClick={() => destination("/help")}>使用指南</button>
          <button onClick={() => go("/login")}>账户登录</button>
          <small>© 2026 AERIS · LOCAL WORKSPACE</small>
        </div>
      </footer>
    </div>
  );
}
function FlagIcon({ size = 22 }: { size?: number }) {
  return <Compass size={size} />;
}
