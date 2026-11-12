import { ANCHOR } from './geo/enu.ts'
import './App.css'

function flag(value: string | undefined): string {
  return value && value.length > 0 ? '已配置（值未显示）' : '未配置（待用户申请 token）'
}

export default function App() {
  const apiBase = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'
  const lat = import.meta.env.VITE_ANCHOR_LAT || String(ANCHOR.lat)
  const lon = import.meta.env.VITE_ANCHOR_LON || String(ANCHOR.lon)
  const h = import.meta.env.VITE_ANCHOR_H || String(ANCHOR.h)

  return (
    <main className="page">
      <p className="badge">阶段 0 占位</p>
      <h1>低空航线安全规划与动态避险智能体</h1>
      <p className="sub">前端工程脚手架（Vite + React 19 + TypeScript）。本页不做视觉设计，仅作启动与对照入口。</p>

      <p>
        <a className="legacy-link" href="/legacy/demo-baseline.html">
          打开冻结的原版 demo 存档（对照基准）
        </a>
      </p>

      <ul className="meta">
        <li>API 根地址：<code>{apiBase}</code></li>
        <li>
          锚点（兴隆湖湖心）：<code>{lat}°N, {lon}°E, h={h} m</code>
        </li>
        <li>天地图 token：{flag(import.meta.env.VITE_TIANDITU_TOKEN)}</li>
        <li>Cesium ion token：{flag(import.meta.env.VITE_CESIUM_ION_TOKEN)}</li>
      </ul>

      <p className="note">
        详细依据见 <code>docs/锚点决议.md</code>。R3F / Cesium / MapLibre
        已登记为依赖，本阶段不实现功能。
      </p>
    </main>
  )
}
