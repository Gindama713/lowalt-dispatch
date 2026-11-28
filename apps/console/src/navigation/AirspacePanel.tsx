import { useRef, useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  Layers,
  LocateFixed,
  Upload,
} from "lucide-react";
import {
  airspaceExample,
  airspaceKinds,
  airspaceTiming,
  regionPoints,
  type AirspaceKind,
} from "./airspace";
import { altitudeLabel } from "./engine";
import type { NavigationController } from "./Navigation";

export function AirspaceLegend({ nav }: { nav: NavigationController }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <aside className="nav-map-legend" aria-label="空域分类图例">
      <button aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
        <Layers size={14} />
        <strong>空域图例</strong>
        <small>
          {nav.regions.length
            ? `${nav.visibleRegions.length}/${nav.regions.length} 区域`
            : "数据未接入"}
        </small>
        {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
      </button>
      {expanded && (
        <div>
          {Object.entries(airspaceKinds).map(([id, kind]) => (
            <label key={id} title={kind.help}>
              <input
                type="checkbox"
                checked={nav.regionKinds.includes(id as AirspaceKind)}
                onChange={() => nav.toggleRegionKind(id as AirspaceKind)}
              />
              <i style={{ background: kind.color }} />
              <span>{kind.title}</span>
              <b>{nav.regions.filter((r) => r.kind === id).length}</b>
            </label>
          ))}
          <p>
            数量为本次载入总数；隐藏仅影响显示，不取消避让。大疆 FlySafe
            厂商地理围栏参考不等于官方许可。
          </p>
          <button
            onClick={() => {
              nav.setOpen(true);
              nav.setTab("airspace");
            }}
          >
            管理区域与来源
          </button>
        </div>
      )}
    </aside>
  );
}

export default function Airspace({
  nav,
  download,
  onOverview,
}: {
  nav: NavigationController;
  download: (value: unknown, name: string) => void;
  onOverview: (points: [number, number][]) => void;
}) {
  const file = useRef<HTMLInputElement>(null);
  const [search, setSearch] = useState("");
  const selected = nav.regions.find((r) => r.id === nav.selectedRegion);
  const results = nav.regions.filter((r) =>
    (r.name + r.source).toLowerCase().includes(search.toLowerCase()),
  );
  return (
    <section className="nav-airspaces" aria-label="空域区域图层管理">
      <div className="nav-section-heading">
        <div>
          <h3>看清区域，也看清来源</h3>
          <p>
            主数据源是大疆 FlySafe 厂商地理围栏参考，不是法定空域，不是 UOM /
            国家地图官网 / 天地图，也不是飞行批准。查询失败或 0
            个区域表示未知，不是放行。手动导入和演练走廊只作附加对照。
          </p>
        </div>
        <div className="nav-inline">
          <input
            ref={file}
            type="file"
            hidden
            accept=".json,.geojson,application/geo+json,application/json"
            onChange={(e) => {
              if (e.target.files?.[0])
                void nav.importAirspace(e.target.files[0]);
              e.target.value = "";
            }}
          />
          <button className="nav-button" onClick={() => file.current?.click()}>
            <Upload size={14} />
            手动导入 GeoJSON（附加）
          </button>
          <button
            className="nav-link"
            onClick={() =>
              download(airspaceExample, "airspace-example.geojson")
            }
          >
            下载空域示例
          </button>
        </div>
      </div>
      <div className="nav-region-filters">
        {Object.entries(airspaceKinds).map(([id, kind]) => (
          <button
            key={id}
            aria-pressed={nav.regionKinds.includes(id as AirspaceKind)}
            title={kind.help}
            onClick={() => nav.toggleRegionKind(id as AirspaceKind)}
          >
            <i style={{ background: kind.color }} />
            <span>{kind.title}</span>
            <b>{nav.regions.filter((r) => r.kind === id).length}</b>
          </button>
        ))}
      </div>
      <p className="nav-note">
        计数为本次载入总数，不是当前视野或全国总数；没有数据不表示该地点没有限制，空的
        FlySafe 结果也不是放行。全国范围的大疆 FlySafe
        厂商围栏是单独的地图图层，默认打开，不写入这条航线的约束快照，也不跟着工单切换被清掉。尚未过期的禁飞区与内部管制区会写入服务端约束快照并纳入二维全高度避让，隐藏分类仅影响地图显示、不会取消避让约束，也不会修改飞控电子围栏。
      </p>
      {nav.activeSnapshot &&
        nav.activeSnapshot.source_status !== "not_loaded" && (
          <p className="nav-note" data-testid="airspace-panel-snapshot">
            当前服务端快照：<code>{nav.activeSnapshot.snapshot_id}</code> · 摘要{" "}
            <code>{nav.activeSnapshot.digest.slice(0, 23)}…</code> · 纳入硬避让{" "}
            {nav.activeSnapshot.enforced_zone_count} /{" "}
            {nav.activeSnapshot.total_zone_count} 个区域
          </p>
        )}
      {nav.activeSnapshot?.failure_reason ? (
        <p
          className="nav-note"
          role="status"
          data-testid="flysafe-refresh-note"
        >
          {nav.activeSnapshot.failure_reason}
        </p>
      ) : null}
      {nav.regionError && (
        <div className="nav-error" role="alert">
          {nav.regionError}
        </div>
      )}
      {nav.regions.length ? (
        <>
          <label className="nav-region-search">
            搜索区域或来源
            <input
              value={search}
              maxLength={150}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="输入区域名称或发布来源"
            />
          </label>
          <div className="nav-region-layout">
            <div className="nav-region-list">
              {results.map((r) => (
                <button
                  key={r.id}
                  aria-pressed={r.id === nav.selectedRegion}
                  onClick={() => nav.setSelectedRegion(r.id)}
                >
                  <i style={{ background: airspaceKinds[r.kind].color }} />
                  <span>
                    <strong>{r.name}</strong>
                    <small>
                      {airspaceKinds[r.kind].title} ·{" "}
                      {r.is_simulated ? "演练" : "真实性待核实"} ·{" "}
                      {airspaceTiming(r)}
                    </small>
                  </span>
                </button>
              ))}
              {!results.length && (
                <p className="nav-note">没有匹配区域，请调整关键词。</p>
              )}
            </div>
            <div className="nav-region-detail">
              {selected ? (
                <>
                  <span className="nav-frame">
                    {airspaceKinds[selected.kind].title} ·{" "}
                    {selected.is_simulated ? "演练区域" : "来源声明，未经核验"}
                  </span>
                  <h4>{selected.name}</h4>
                  <p>{airspaceKinds[selected.kind].help}</p>
                  <dl>
                    <dt>来源类型</dt>
                    <dd>
                      {
                        {
                          official: "官方来源声明",
                          manufacturer: "厂商参考",
                          team: "团队资料",
                        }[selected.source_kind]
                      }{" "}
                      · 未验证真实性
                    </dd>
                    <dt>发布来源</dt>
                    <dd>{selected.source}</dd>
                    <dt>引用 / 版本</dt>
                    <dd>{selected.source_ref}</dd>
                    <dt>数据更新时间</dt>
                    <dd>{new Date(selected.updated_at).toLocaleString()}</dd>
                    <dt>有效期</dt>
                    <dd>
                      {selected.effective_from
                        ? new Date(selected.effective_from).toLocaleString()
                        : "待核实"}{" "}
                      —{" "}
                      {selected.effective_until
                        ? new Date(selected.effective_until).toLocaleString()
                        : "待核实"}{" "}
                      · {airspaceTiming(selected)}
                    </dd>
                    <dt>高度上限</dt>
                    <dd>
                      {selected.max_height_m == null
                        ? "未提供，不能推断"
                        : `${selected.max_height_m} m · ${altitudeLabel(selected.altitude_ref)}`}
                    </dd>
                    <dt>原始说明</dt>
                    <dd>{selected.description || "未提供"}</dd>
                  </dl>
                  <button
                    className="nav-button"
                    onClick={() => {
                      if (!nav.regionKinds.includes(selected.kind))
                        nav.toggleRegionKind(selected.kind);
                      nav.setFollow(false);
                      onOverview(regionPoints(selected));
                    }}
                  >
                    <LocateFixed size={14} />
                    定位该区域
                  </button>
                </>
              ) : (
                <p>选择区域查看来源、时效及高度信息。</p>
              )}
            </div>
          </div>
          <div className="nav-start-row">
            <p>
              当前区域已同步至服务端约束快照，刷新页面或恢复绑定工单后仍可找回。通过已知区域检查不代表获准起飞。
            </p>
            <div className="nav-inline">
              <button
                className="nav-button"
                onClick={() =>
                  download(
                    {
                      type: "FeatureCollection",
                      coordinate_system: "WGS84",
                      features: nav.regions.map(
                        ({ geometry, ...properties }) => ({
                          type: "Feature",
                          geometry,
                          properties,
                        }),
                      ),
                    },
                    "airspace-reference.geojson",
                  )
                }
              >
                导出区域资料
              </button>
              <button
                className="nav-link"
                onClick={() => void nav.clearAirspace("clear")}
              >
                移除本次导入图层
              </button>
            </div>
          </div>
        </>
      ) : (
        <div className="nav-empty">
          <Layers size={25} />
          <div>
            <strong>
              {nav.activeSnapshot?.source_status === "unavailable"
                ? "大疆 FlySafe 不可用或为空（未知，不是放行）"
                : nav.activeSnapshot?.source_status === "known_empty"
                  ? "当前已知空域快照显式为空（0 个区域）"
                  : "尚未载入区域边界"}
            </strong>
            <p>
              已提供分类图例与导入入口。请提供有来源的 WGS84 GeoJSON
              后显示真实边界；不会将构造示例自动画到真实地图。
            </p>
          </div>
        </div>
      )}
    </section>
  );
}
