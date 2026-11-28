import type {
  Health,
  MarginView,
  PlanRequest,
  PlanResponse,
  RiskSnapshot,
  RouteRecord,
  SceneBindRequest,
  SceneBindResult,
  SceneDocument,
  Task
} from '../model/types';

/** 页面只依赖这个接口。Mock 与 HTTP 返回同一套解析后的对象。 */
export interface DataSource {
  getHealth(): Promise<Health>;
  listTasks(): Promise<Task[]>;
  getTask(taskId: string): Promise<Task>;
  createTask(task: Task): Promise<Task>;
  getScene(sceneId: string): Promise<SceneDocument>;
  snapshotFromScene(taskId: string, request: SceneBindRequest): Promise<SceneBindResult>;
  getLatestSnapshot(taskId: string): Promise<RiskSnapshot>;
  getSnapshot(taskId: string, snapshotId: string): Promise<RiskSnapshot>;
  plan(taskId: string, request: PlanRequest): Promise<PlanResponse>;
  listRoutes(taskId: string): Promise<RouteRecord[]>;
  getRoute(taskId: string, routeId: string): Promise<RouteRecord>;
  getMargin(taskId: string, routeId: string): Promise<MarginView>;
}
