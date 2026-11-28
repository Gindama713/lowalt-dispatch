import { useRef, useState } from "react";
import { Check, Clock3, MapPin } from "lucide-react";

import { formatCoordinates, type GeoPlace, type LngLat } from "../geo";
import { MapPicker } from "./MapPicker";
import { PinPreview } from "./PinPreview";
import type {
  Clarification,
  IntakeConfirmation,
  MapPin as MapPinData,
} from "./types";
import "./clarification.css";

type Props = {
  data: Clarification;
  busy: boolean;
  onConfirm: (text: string, confirmation?: IntakeConfirmation) => void;
};

export function ClarificationCard({ data, busy, onConfirm }: Props) {
  const [picked, setPicked] = useState<{
    origin?: GeoPlace;
    destination?: GeoPlace;
  }>({});
  const suggested = data.questions.find(
    (item) => item.field === "scheduled_for",
  )?.current;
  const [when, setWhen] = useState(() =>
    suggested
      ? new Date(new Date(suggested).getTime() + 8 * 3600_000)
          .toISOString()
          .slice(0, 16)
      : "",
  );
  const submitted = useRef<{ signature: string; id: string } | null>(null);
  const [payload, setPayload] = useState(() =>
    data.draft_values?.payload_kg == null
      ? ""
      : String(data.draft_values.payload_kg),
  );
  const [priority, setPriority] = useState(
    () => data.draft_values?.priority || "P2",
  );
  const [picker, setPicker] = useState<"origin" | "destination" | null>(null);

  const applyPlace = (field: "origin" | "destination", place: GeoPlace) => {
    // Only a pick made inside THIS card may override the backend pin. Reading
    // the global map selection here used to overwrite a freshly resolved
    // Nanchang coordinate with a stale Shanghai click.
    setPicked((current) => ({ ...current, [field]: place }));
    setPicker(null);
  };

  const pins = data.map_pins.map((pin: MapPinData) => {
    const local = pin.field === "origin" ? picked.origin : picked.destination;
    // Local ENU metres are NOT WGS84. Never send them back as map coordinates.
    const point = local?.point ?? (pin.crs === "EPSG:4326" ? pin.point : null);
    return {
      ...pin,
      name: local?.name ?? pin.name,
      point,
      crs: local ? "EPSG:4326" : pin.crs,
      address: local?.address ?? pin.address,
      fromMap: !!local,
    };
  });
  const located = pins.every((pin) => pin.point);
  const weight = payload.trim() === "" ? NaN : Number(payload);
  const ready =
    !!when &&
    located &&
    Number.isFinite(weight) &&
    weight >= 0 &&
    weight <= 100 &&
    !busy;

  const confirmPin = (pin: (typeof pins)[number]) => {
    if (!pin.point) return;
    applyPlace(pin.field === "origin" ? "origin" : "destination", {
      name: pin.name,
      point: pin.point as LngLat,
      source: "map_click",
      capturedAt: new Date().toISOString(),
    });
  };

  const submit = () => {
    if (!ready) return;
    const origin = pins.find((pin) => pin.field === "origin");
    const destination = pins.find((pin) => pin.field === "destination");
    if (!origin?.point || !destination?.point) return;
    const scheduled = `${when}:00+08:00`;
    const text = `确认创建任务工单：${origin.name} → ${destination.name}，${when.replace("T", " ")} UTC+8，载荷 ${weight} 公斤，优先级 ${priority}。`;
    const signature = JSON.stringify([
      origin.name,
      origin.point,
      destination.name,
      destination.point,
      scheduled,
      weight,
      priority,
    ]);
    if (submitted.current?.signature !== signature)
      submitted.current = { signature, id: crypto.randomUUID() };
    onConfirm(text, {
      confirmation_id: submitted.current.id,
      text,
      origin: origin.name,
      destination: destination.name,
      origin_point: origin.point as LngLat,
      destination_point: destination.point as LngLat,
      scheduled_for: scheduled,
      payload_kg: weight,
      priority: priority as "P1" | "P2",
    });
  };

  return (
    <section className="intake-clarify" data-testid="intake-clarification">
      <header>
        <Clock3 size={14} />
        <strong>待确认 · AI 任务工单</strong>
        <span>核对后建单</span>
      </header>
      <p className="intake-clarify-lead">{data.summary.split("\n")[0]}</p>
      <ol className="intake-clarify-questions">
        {data.questions.map((item, index) => (
          <li key={`${item.field}-${index}`} data-field={item.field}>
            <span>{index + 1}</span>
            {item.question}
            {item.options && item.options.length > 0 && (
              <div className="intake-clarify-options">
                {item.options.map((option) => (
                  <button
                    key={option.label}
                    type="button"
                    disabled={busy}
                    onClick={() => onConfirm(option.value)}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            )}
          </li>
        ))}
      </ol>

      <div className="intake-clarify-map" data-testid="intake-map-pins">
        <div className="intake-clarify-map-head">
          <MapPin size={13} />
          <strong>地图定位</strong>
          <button
            type="button"
            onClick={() => setPicked({})}
            disabled={!picked.origin && !picked.destination}
          >
            恢复助手坐标
          </button>
          <button
            type="button"
            onClick={() => window.location.assign("/airspace")}
          >
            去地图选点
          </button>
        </div>
        {pins.map((pin) => (
          <div className="intake-pin" key={pin.field} data-pin={pin.field}>
            <div className="intake-pin-head">
              <span>{pin.field === "origin" ? "起点" : "终点"}</span>
              <strong>{pin.name}</strong>
            </div>
            {pin.address && (
              <small className="intake-pin-address">{pin.address}</small>
            )}
            {!!pin.candidates?.length && (
              <div className="place-results">
                {pin.candidates.map((candidate, index) => (
                  <button
                    key={index}
                    type="button"
                    onClick={() =>
                      setPicked((current) => ({
                        ...current,
                        [pin.field]: { ...candidate, source: "osm_search" },
                      }))
                    }
                  >
                    {candidate.name}
                    <small>
                      {candidate.address} · {formatCoordinates(candidate.point)}
                    </small>
                  </button>
                ))}
              </div>
            )}
            {pin.point ? (
              <PinPreview
                point={pin.point as LngLat}
                label={pin.name}
                onOpen={() =>
                  setPicker(pin.field === "origin" ? "origin" : "destination")
                }
              />
            ) : (
              <div className="intake-pin-empty">
                <MapPin size={15} />
                <span>
                  {pin.crs && pin.crs !== "EPSG:4326"
                    ? "场景坐标不是经纬度，请搜索或地图选点"
                    : "未定位，请搜索或地图选点"}
                </span>
              </div>
            )}
            <div className="intake-pin-foot">
              <code>
                {pin.point
                  ? formatCoordinates(pin.point as LngLat)
                  : "坐标未解析，助手不会猜"}
              </code>
              <div className="intake-pin-actions">
                <button
                  type="button"
                  disabled={!pin.point}
                  onClick={() => confirmPin(pin)}
                >
                  确定使用
                </button>
                <button
                  type="button"
                  onClick={() =>
                    setPicker(pin.field === "origin" ? "origin" : "destination")
                  }
                >
                  搜地点
                </button>
              </div>
            </div>
          </div>
        ))}
        <p className="intake-clarify-hint">
          在空域态势页用「地点定位」分别设为起点/终点，回到这里点「重新读取」。坐标不会由助手猜测。
        </p>
      </div>

      <p className="intake-clarify-weather">{data.weather_feasibility.note}</p>

      <div className="intake-clarify-form">
        <label>
          具体时间 · UTC+8
          <input
            type="datetime-local"
            aria-label="确认起飞时间"
            value={when}
            onChange={(event) => setWhen(event.target.value)}
          />
        </label>
        <label>
          载荷 (kg)
          <input
            type="number"
            min="0"
            max="100"
            step="0.1"
            aria-label="确认载荷重量"
            value={payload}
            onChange={(event) => setPayload(event.target.value)}
          />
        </label>
        <label>
          优先级
          <select
            aria-label="确认优先级"
            value={priority}
            onChange={(event) => setPriority(event.target.value)}
          >
            <option value="P2">P2 常规</option>
            <option value="P1">P1 应急</option>
          </select>
        </label>
      </div>

      <button
        type="button"
        className="intake-clarify-submit"
        data-testid="intake-confirm"
        disabled={!ready}
        onClick={submit}
      >
        <Check size={14} /> 确认并创建任务工单
      </button>
      <small className="intake-clarify-foot">
        工单只做记录，不进入 M3、不产生飞控指令；推荐路线仅为几何预览 · 仿真。
      </small>
      {picker && (
        <MapPicker
          field={picker}
          initial={
            (pins.find((pin) => pin.field === picker)?.point as
              | LngLat
              | null
              | undefined) ?? null
          }
          onClose={() => setPicker(null)}
          onPick={(place) => applyPlace(picker, place)}
        />
      )}
    </section>
  );
}
