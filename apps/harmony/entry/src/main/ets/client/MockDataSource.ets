import type { DataSource } from './DataSource';
import { ApiError } from '../model/errors';
import { examplePlan } from '../model/example_plan';
import { marginViewFromRoute } from '../model/parse';
import type {
  DataProvenance,
  GeoPolygon,
  Health,
  LandingSite,
  MarginView,
  PlanRequest,
  PlanResponse,
  Position,
  RiskEvent,
  RiskSnapshot,
  RouteRecord,
  SceneBindRequest,
  SceneBindResult,
  SceneDocument,
  SeedRoutes,
  SeedSnapshot,
  Task
} from '../model/types';

class SnapshotBucket {
  taskId: string = '';
  items: RiskSnapshot[] = [];
}

class RouteBucket {
  taskId: string = '';
  items: RouteRecord[] = [];
}

/**
 * 内存数据源。种子来自 rawfile JSON，交互过程中的新建任务、快照和航线只留在进程内。
 * 规划是示例折线，不是 A*。
 */
export class MockDataSource implements DataSource {
  private health: Health;
  private tasks: Task[];
  private scene: SceneDocument;
  private snapshots: SnapshotBucket[];
  private routes: RouteBucket[];

  private constructor(
    health: Health,
    tasks: Task[],
    scene: SceneDocument,
    snapshots: SeedSnapshot[],
    routes: SeedRoutes[]
  ) {
    this.health = health;
    this.tasks = [];
    for (let i = 0; i < tasks.length; i++) {
      this.tasks.push(tasks[i]);
    }
    this.scene = scene;
    this.snapshots = [];
    this.routes = [];
    for (let i = 0; i < snapshots.length; i++) {
      const bucket = this.bucketFor(this.snapshots, snapshots[i].task_id);
      bucket.items.push(snapshots[i].snapshot);
    }
    for (let i = 0; i < routes.length; i++) {
      const bucket = this.routeBucketFor(routes[i].task_id);
      for (let j = 0; j < routes[i].routes.length; j++) {
        bucket.items.push(routes[i].routes[j]);
      }
    }
  }

  static fromParts(
    health: Health,
    tasks: Task[],
    scene: SceneDocument,
    snapshots: SeedSnapshot[],
    routes: SeedRoutes[]
  ): MockDataSource {
    return new MockDataSource(health, tasks, scene, snapshots, routes);
  }

  async getHealth(): Promise<Health> {
    return this.health;
  }

  async listTasks(): Promise<Task[]> {
    const copy: Task[] = [];
    for (let i = 0; i < this.tasks.length; i++) {
      copy.push(this.tasks[i]);
    }
    return copy;
  }

  async getTask(taskId: string): Promise<Task> {
    return this.requireTask(taskId);
  }

  async createTask(task: Task): Promise<Task> {
    for (let i = 0; i < this.tasks.length; i++) {
      if (this.tasks[i].task_id === task.task_id) {
        throw new ApiError(409, '任务 ' + task.task_id + ' 已存在');
      }
    }
    this.tasks.push(task);
    return task;
  }

  async getScene(sceneId: string): Promise<SceneDocument> {
    if (sceneId !== this.scene.scene_id) {
      throw new ApiError(404, '没有场景 ' + sceneId + '。当前只有草稿场景 v0。');
    }
    return this.scene;
  }

  async snapshotFromScene(taskId: string, request: SceneBindRequest): Promise<SceneBindResult> {
    this.requireTask(taskId);
    if (request.scene_id !== this.scene.scene_id) {
      throw new ApiError(404, '没有场景 ' + request.scene_id + '。当前只有草稿场景 v0。');
    }
    this.requireKnownZones(request.active_zone_ids);
    this.requireKnownSites(request.occupied_site_ids);
    const snapshotId = this.freshSnapshotId(taskId);
    const capturedAt = new Date().toISOString();
    const sites: LandingSite[] = [];
    for (let i = 0; i < this.scene.landing_sites.length; i++) {
      sites.push(this.copySite(this.scene.landing_sites[i], request.occupied_site_ids, capturedAt));
    }
    const events: RiskEvent[] = [];
    for (let i = 0; i < request.active_zone_ids.length; i++) {
      events.push(this.zoneEvent(request.active_zone_ids[i], capturedAt));
    }
    const active = request.active_zone_ids.length === 0 ? '无' : request.active_zone_ids.join('、');
    const note = '仿真草稿。几何来自 scenarios/v0（status=draft，is_simulated=true），不是实测空域。' +
      '障碍物不在 RiskSnapshot 里，规划时仍从 obstacles.geojson 读取。' +
      '本次标为已生效的限制区：' + active + '。示例：由手机端 Mock 生成，不是服务端 bind_scene。';
    const snapshot: RiskSnapshot = {
      snapshot_id: snapshotId,
      captured_at: capturedAt,
      valid_until: null,
      landing_sites: sites,
      events: events,
      note: note
    };
    this.bucketFor(this.snapshots, taskId).items.push(snapshot);
    return {
      snapshot: snapshot,
      scene_id: this.scene.scene_id,
      is_simulated: true,
      note: note
    };
  }

  async getLatestSnapshot(taskId: string): Promise<RiskSnapshot> {
    this.requireTask(taskId);
    const items = this.bucketFor(this.snapshots, taskId).items;
    if (items.length === 0) {
      throw new ApiError(404, '任务 ' + taskId + ' 还没有快照');
    }
    return items[items.length - 1];
  }

  async getSnapshot(taskId: string, snapshotId: string): Promise<RiskSnapshot> {
    this.requireTask(taskId);
    const items = this.bucketFor(this.snapshots, taskId).items;
    for (let i = 0; i < items.length; i++) {
      if (items[i].snapshot_id === snapshotId) {
        return items[i];
      }
    }
    throw new ApiError(404, '任务 ' + taskId + ' 没有快照 ' + snapshotId);
  }

  async plan(taskId: string, request: PlanRequest): Promise<PlanResponse> {
    const task = this.requireTask(taskId);
    let snapshot: RiskSnapshot;
    if (request.snapshot_id === null || request.snapshot_id.length === 0) {
      const items = this.bucketFor(this.snapshots, taskId).items;
      if (items.length === 0) {
        throw new ApiError(400, '任务还没有快照。先加载场景或提交 RiskSnapshot，再规划。');
      }
      snapshot = items[items.length - 1];
    } else {
      snapshot = await this.getSnapshot(taskId, request.snapshot_id);
    }
    const version = this.nextVersion(taskId);
    const response = examplePlan(task, snapshot, this.scene, request, version);
    this.routeBucketFor(taskId).items.push(response.route);
    return response;
  }

  async listRoutes(taskId: string): Promise<RouteRecord[]> {
    this.requireTask(taskId);
    const items = this.routeBucketFor(taskId).items;
    const copy: RouteRecord[] = [];
    for (let i = 0; i < items.length; i++) {
      copy.push(items[i]);
    }
    return copy;
  }

  async getRoute(taskId: string, routeId: string): Promise<RouteRecord> {
    this.requireTask(taskId);
    const items = this.routeBucketFor(taskId).items;
    for (let i = 0; i < items.length; i++) {
      if (items[i].route_id === routeId) {
        return items[i];
      }
    }
    throw new ApiError(404, '任务 ' + taskId + ' 没有路线 ' + routeId);
  }

  async getMargin(taskId: string, routeId: string): Promise<MarginView> {
    const route = await this.getRoute(taskId, routeId);
    return marginViewFromRoute(route);
  }

  private requireTask(taskId: string): Task {
    for (let i = 0; i < this.tasks.length; i++) {
      if (this.tasks[i].task_id === taskId) {
        return this.tasks[i];
      }
    }
    throw new ApiError(404, '没有任务 ' + taskId);
  }

  private bucketFor(buckets: SnapshotBucket[], taskId: string): SnapshotBucket {
    for (let i = 0; i < buckets.length; i++) {
      if (buckets[i].taskId === taskId) {
        return buckets[i];
      }
    }
    const created = new SnapshotBucket();
    created.taskId = taskId;
    buckets.push(created);
    return created;
  }

  private routeBucketFor(taskId: string): RouteBucket {
    for (let i = 0; i < this.routes.length; i++) {
      if (this.routes[i].taskId === taskId) {
        return this.routes[i];
      }
    }
    const created = new RouteBucket();
    created.taskId = taskId;
    this.routes.push(created);
    return created;
  }

  private freshSnapshotId(taskId: string): string {
    const items = this.bucketFor(this.snapshots, taskId).items;
    for (let offset = 1; offset < 1000; offset++) {
      const candidate = taskId + '-snap-' + String(offset);
      let used = false;
      for (let i = 0; i < items.length; i++) {
        if (items[i].snapshot_id === candidate) {
          used = true;
        }
      }
      if (!used) {
        return candidate;
      }
    }
    throw new ApiError(500, '快照编号用尽');
  }

  private nextVersion(taskId: string): string {
    const count = this.routeBucketFor(taskId).items.length + 1;
    return 'v' + String(count);
  }

  private requireKnownZones(ids: string[]): void {
    const unknown: string[] = [];
    for (let i = 0; i < ids.length; i++) {
      if (this.findZone(ids[i]) === null) {
        unknown.push(ids[i]);
      }
    }
    if (unknown.length > 0) {
      const known: string[] = [];
      for (let i = 0; i < this.scene.restriction_zones.length; i++) {
        known.push(this.scene.restriction_zones[i].id);
      }
      known.sort();
      throw new ApiError(422, '未知限制区 ' + unknown.join(', ') + '。场景里有：' + known.join('、'));
    }
  }

  private requireKnownSites(ids: string[]): void {
    const unknown: string[] = [];
    for (let i = 0; i < ids.length; i++) {
      if (this.findSite(ids[i]) === null) {
        unknown.push(ids[i]);
      }
    }
    if (unknown.length > 0) {
      throw new ApiError(422, '未知备降点 ' + unknown.join(', '));
    }
  }

  private findZone(zoneId: string): GeoPolygon | null {
    for (let i = 0; i < this.scene.restriction_zones.length; i++) {
      if (this.scene.restriction_zones[i].id === zoneId) {
        return this.scene.restriction_zones[i];
      }
    }
    return null;
  }

  private findSite(siteId: string): LandingSite | null {
    for (let i = 0; i < this.scene.landing_sites.length; i++) {
      if (this.scene.landing_sites[i].site_id === siteId) {
        return this.scene.landing_sites[i];
      }
    }
    return null;
  }

  private copySite(site: LandingSite, occupiedIds: string[], capturedAt: string): LandingSite {
    let occupied = false;
    for (let i = 0; i < occupiedIds.length; i++) {
      if (occupiedIds[i] === site.site_id) {
        occupied = true;
      }
    }
    const provenance: DataProvenance = {
      source: site.provenance.source,
      version: site.provenance.version,
      captured_at: capturedAt,
      valid_from: site.provenance.valid_from,
      valid_until: site.provenance.valid_until,
      is_simulated: site.provenance.is_simulated,
      uncertainty_note: site.provenance.uncertainty_note
    };
    const position: Position = {
      frame: site.position.frame,
      alt_m: site.position.alt_m,
      alt_ref: site.position.alt_ref,
      x_m: site.position.x_m,
      y_m: site.position.y_m,
      lat_deg: site.position.lat_deg,
      lon_deg: site.position.lon_deg
    };
    return {
      site_id: site.site_id,
      position: position,
      radius_m: site.radius_m,
      compatible_vehicle_types: site.compatible_vehicle_types,
      available_from: site.available_from,
      available_until: site.available_until,
      occupied: occupied,
      provenance: provenance
    };
  }

  private zoneEvent(zoneId: string, capturedAt: string): RiskEvent {
    const zone = this.findZone(zoneId);
    const rings: number[][][] = [];
    let altMin: number | null = null;
    let altMax: number | null = null;
    if (zone !== null) {
      for (let i = 0; i < zone.rings.length; i++) {
        rings.push(zone.rings[i]);
      }
      altMin = zone.alt_min_m;
      altMax = zone.alt_max_m;
    }
    return {
      event_id: 'zone-' + zoneId,
      kind: 'restriction_zone',
      zone_id: zoneId,
      rings: rings,
      alt_min_m: altMin,
      alt_max_m: altMax,
      effective_from: capturedAt,
      effective_until: null,
      provenance: {
        source: 'sim:scenario_v0',
        version: 'v0-draft',
        captured_at: capturedAt,
        valid_from: null,
        valid_until: null,
        is_simulated: true,
        uncertainty_note: '示例。由加载场景时点名，视为当前已经生效。'
      }
    };
  }
}
