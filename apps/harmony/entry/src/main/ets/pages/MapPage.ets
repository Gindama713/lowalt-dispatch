import { router } from '@kit.ArkUI';
import { AlertStore } from '../client/AlertStore';
import { Repository } from '../client/Repository';
import { ApiError } from '../model/errors';
import {
  GeoPolygon,
  LandingSite,
  Position,
  RiskSnapshot,
  RouteRecord,
  SceneDocument,
  Task
} from '../model/types';
import { TopBar } from '../view/TopBar';
import { Drone3DBackground } from '../view/Drone3DBackground';

interface MapParams {
  taskId?: string;
  routeId?: string;
}

@Entry
@Component
struct MapPage {
  @State errorText: string = '';
  @State summary: string = '正在读取场景…';
  private settings: RenderingContextSettings = new RenderingContextSettings(true);
  private context: CanvasRenderingContext2D = new CanvasRenderingContext2D(this.settings);
  private viewW: number = 1;
  private viewH: number = 1;
  private scale: number = 0.08;
  private camX: number = 1600;
  private camY: number = 1600;
  private panCamX: number = 1600;
  private panCamY: number = 1600;
  private pinchBase: number = 0.08;
  private ready: boolean = false;
  private taskId: string = '';
  private routeId: string = '';
  private sceneDoc: SceneDocument | null = null;
  private taskDoc: Task | null = null;
  private routeDoc: RouteRecord | null = null;
  private activeZoneIds: string[] = [];

  aboutToAppear(): void {
    const raw = router.getParams() as MapParams;
    if (raw !== undefined && raw !== null) {
      if (raw.taskId !== undefined) {
        this.taskId = raw.taskId;
      }
      if (raw.routeId !== undefined) {
        this.routeId = raw.routeId;
      }
    }
    this.load();
  }

  private load(): void {
    const source = Repository.get();
    source.getScene('v0').then((scene: SceneDocument) => {
      this.sceneDoc = scene;
      this.summary = '障碍 ' + String(scene.counts.obstacles) + ' · 限制区 ' +
        String(scene.counts.restriction_zones) + ' · 备降点 ' + String(scene.counts.landing_sites);
      this.fit();
      this.redraw();
    }).catch((err: Object) => {
      this.errorText = AlertStore.recordFromError('地图场景', err);
    });
    if (this.taskId.length === 0) {
      return;
    }
    source.getTask(this.taskId).then((task: Task) => {
      this.taskDoc = task;
      this.redraw();
    }).catch((err: Object) => {
      this.errorText = AlertStore.recordFromError('地图任务', err);
    });
    source.getLatestSnapshot(this.taskId).then((snapshot: RiskSnapshot) => {
      const ids: string[] = [];
      for (let i = 0; i < snapshot.events.length; i++) {
        const zoneId = snapshot.events[i].zone_id;
        if (zoneId !== null) {
          ids.push(zoneId);
        }
      }
      this.activeZoneIds = ids;
      this.redraw();
    }).catch((err: Object) => {
      if (!(err instanceof ApiError && err.status === 404)) {
        this.errorText = AlertStore.recordFromError('地图快照', err);
      }
    });
    if (this.routeId.length > 0) {
      source.getRoute(this.taskId, this.routeId).then((route: RouteRecord) => {
        this.routeDoc = route;
        this.redraw();
      }).catch((err: Object) => {
        this.errorText = AlertStore.recordFromError('地图航线', err);
      });
    }
  }

  private fit(): void {
    if (this.viewW <= 1 || this.viewH <= 1) {
      return;
    }
    this.camX = 1600;
    this.camY = 1600;
    this.scale = Math.min(this.viewW, this.viewH) / 3400;
  }

  private sx(x: number): number {
    return this.viewW / 2 + (x - this.camX) * this.scale;
  }

  private sy(y: number): number {
    return this.viewH / 2 - (y - this.camY) * this.scale;
  }

  private redraw(): void {
    if (!this.ready) {
      return;
    }
    const ctx = this.context;
    ctx.clearRect(0, 0, this.viewW, this.viewH);
    ctx.fillStyle = '#E7EEEA';
    ctx.fillRect(0, 0, this.viewW, this.viewH);
    ctx.strokeStyle = '#D5E0DA';
    ctx.lineWidth = 1;
    for (let meter = 0; meter <= 3000; meter += 500) {
      ctx.beginPath();
      ctx.moveTo(this.sx(meter), this.sy(0));
      ctx.lineTo(this.sx(meter), this.sy(3000));
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(this.sx(0), this.sy(meter));
      ctx.lineTo(this.sx(3000), this.sy(meter));
      ctx.stroke();
    }
    if (this.sceneDoc !== null) {
      for (let i = 0; i < this.sceneDoc.obstacles.length; i++) {
        this.paintPolygon(this.sceneDoc.obstacles[i], 'rgba(120, 132, 140, 0.85)', '#5E6A72');
      }
      for (let i = 0; i < this.sceneDoc.restriction_zones.length; i++) {
        const zone = this.sceneDoc.restriction_zones[i];
        const active = this.isActive(zone.id);
        this.paintPolygon(zone, active ? 'rgba(196, 62, 62, 0.35)' : 'rgba(196, 62, 62, 0.08)', '#C43E3E');
        this.label(zone.id, zone.rings);
      }
      for (let i = 0; i < this.sceneDoc.landing_sites.length; i++) {
        this.paintSite(this.sceneDoc.landing_sites[i]);
      }
    }
    this.paintRoute();
    this.paintEndpoint(this.taskDoc === null ? null : this.taskDoc.origin, '起');
    this.paintEndpoint(this.taskDoc === null ? null : this.taskDoc.destination, '终');
    ctx.fillStyle = '#1C2B26';
    ctx.font = '12px sans-serif';
    ctx.fillText('北 +Y', 12, 18);
  }

  private isActive(zoneId: string): boolean {
    for (let i = 0; i < this.activeZoneIds.length; i++) {
      if (this.activeZoneIds[i] === zoneId) {
        return true;
      }
    }
    return false;
  }

  private paintPolygon(polygon: GeoPolygon, fill: string, stroke: string): void {
    if (polygon.rings.length === 0 || polygon.rings[0].length === 0) {
      return;
    }
    const ring = polygon.rings[0];
    const ctx = this.context;
    ctx.beginPath();
    ctx.moveTo(this.sx(ring[0][0]), this.sy(ring[0][1]));
    for (let i = 1; i < ring.length; i++) {
      ctx.lineTo(this.sx(ring[i][0]), this.sy(ring[i][1]));
    }
    ctx.closePath();
    ctx.fillStyle = fill;
    ctx.fill();
    ctx.strokeStyle = stroke;
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }

  private label(text: string, rings: number[][][]): void {
    if (rings.length === 0 || rings[0].length === 0) {
      return;
    }
    this.context.fillStyle = '#7A1F1F';
    this.context.font = '12px sans-serif';
    this.context.fillText(text, this.sx(rings[0][0][0]) + 4, this.sy(rings[0][0][1]) - 4);
  }

  private paintSite(site: LandingSite): void {
    if (site.position.x_m === null || site.position.y_m === null) {
      return;
    }
    const ctx = this.context;
    const radius = Math.max(4, site.radius_m * this.scale);
    ctx.beginPath();
    ctx.arc(this.sx(site.position.x_m), this.sy(site.position.y_m), radius, 0, Math.PI * 2);
    ctx.fillStyle = site.occupied ? 'rgba(224, 122, 61, 0.85)' : 'rgba(31, 138, 112, 0.85)';
    ctx.fill();
    ctx.fillStyle = '#14312A';
    ctx.font = '12px sans-serif';
    ctx.fillText(site.site_id, this.sx(site.position.x_m) + radius + 2, this.sy(site.position.y_m));
  }

  private paintRoute(): void {
    const route = this.routeDoc;
    if (route === null || route.waypoints.length < 2) {
      return;
    }
    const ctx = this.context;
    ctx.beginPath();
    const first = route.waypoints[0];
    if (first.x_m === null || first.y_m === null) {
      return;
    }
    ctx.moveTo(this.sx(first.x_m), this.sy(first.y_m));
    for (let i = 1; i < route.waypoints.length; i++) {
      const point = route.waypoints[i];
      if (point.x_m === null || point.y_m === null) {
        continue;
      }
      ctx.lineTo(this.sx(point.x_m), this.sy(point.y_m));
    }
    ctx.strokeStyle = '#0B6E4F';
    ctx.lineWidth = 3;
    ctx.stroke();
    if (route.waypoints.length <= 30) {
      for (let i = 0; i < route.waypoints.length; i++) {
        this.dot(route.waypoints[i]);
      }
    }
  }

  private dot(point: Position): void {
    if (point.x_m === null || point.y_m === null) {
      return;
    }
    const ctx = this.context;
    ctx.beginPath();
    ctx.arc(this.sx(point.x_m), this.sy(point.y_m), 3, 0, Math.PI * 2);
    ctx.fillStyle = '#0B6E4F';
    ctx.fill();
  }

  private paintEndpoint(point: Position | null, title: string): void {
    if (point === null || point.x_m === null || point.y_m === null) {
      return;
    }
    const ctx = this.context;
    const x = this.sx(point.x_m);
    const y = this.sy(point.y_m);
    ctx.fillStyle = title === '起' ? '#1D4E89' : '#7A2E0E';
    ctx.fillRect(x - 5, y - 5, 10, 10);
    ctx.font = '12px sans-serif';
    ctx.fillText(title, x + 8, y - 6);
  }

  private zoom(factor: number): void {
    const next = this.scale * factor;
    if (next < 0.02 || next > 8) {
      return;
    }
    this.scale = next;
    this.redraw();
  }

  build() {
    Stack() {
      Drone3DBackground({ scrimColor: '#5907121C' })
      Column() {
        TopBar({ title: '地图', showBack: true })
        if (this.errorText.length > 0) {
          Text(this.errorText)
            .fontSize(12)
            .fontColor('#B42318')
            .backgroundColor('#E6FFF0F0')
            .padding({ left: 16, right: 16, top: 4, bottom: 4 })
        }
        Text(this.summary + '  ·  拖动平移，双指或按钮缩放。坐标是 ENU 米。')
          .fontSize(12)
          .fontColor('#E4F2F7')
          .padding({ left: 16, right: 16, top: 6, bottom: 6 })
        Canvas(this.context)
          .width('100%')
          .layoutWeight(1)
          .backgroundColor('#D9E7EEEA')
          .onReady(() => {
            this.ready = true;
            this.fit();
            this.redraw();
          })
          .onAreaChange((_old: Area, area: Area) => {
            this.viewW = lengthPx(area.width);
            this.viewH = lengthPx(area.height);
            if (this.sceneDoc !== null) {
              this.fit();
            }
            this.redraw();
          })
          .gesture(
            GestureGroup(GestureMode.Parallel,
              PanGesture({ fingers: 1 })
                .onActionStart(() => {
                  this.panCamX = this.camX;
                  this.panCamY = this.camY;
                })
                .onActionUpdate((event: GestureEvent) => {
                  this.camX = this.panCamX - event.offsetX / this.scale;
                  this.camY = this.panCamY + event.offsetY / this.scale;
                  this.redraw();
                }),
              PinchGesture({ fingers: 2 })
                .onActionStart(() => {
                  this.pinchBase = this.scale;
                })
                .onActionUpdate((event: GestureEvent) => {
                  const next = this.pinchBase * event.scale;
                  if (next >= 0.02 && next <= 8) {
                    this.scale = next;
                    this.redraw();
                  }
                })
            )
          )
        Row() {
          Button('缩小')
            .backgroundColor('#355C7D')
            .onClick(() => {
              this.zoom(0.8);
            })
          Button('放大')
            .margin({ left: 8 })
            .backgroundColor('#355C7D')
            .onClick(() => {
              this.zoom(1.25);
            })
          Button('复位')
            .margin({ left: 8 })
            .backgroundColor('#355C7D')
            .onClick(() => {
              this.fit();
              this.redraw();
            })
        }
        .width('100%')
        .padding(12)
        .backgroundColor('#CC0B1A26')
        .justifyContent(FlexAlign.Center)
        Text('灰块障碍 · 红框限制区（填色为快照里已生效） · 绿点空闲备降 · 橙点占用 · 绿线航线')
          .fontSize(11)
          .fontColor('#CFE3EC')
          .backgroundColor('#CC0B1A26')
          .width('100%')
          .padding({ left: 16, right: 16, bottom: 8 })
      }
      .width('100%')
      .height('100%')
    }
    .width('100%')
    .height('100%')
  }
}

function lengthPx(value: number | string): number {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string') {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return 1;
}
