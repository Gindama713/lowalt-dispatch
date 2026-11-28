import { http } from '@kit.NetworkKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { DataSource } from './DataSource';
import { ApiError, ParseError, formatDetail } from '../model/errors';
import {
  parseBind,
  parseHealth,
  parseMargin,
  parsePlan,
  parseRoute,
  parseRoutes,
  parseScene,
  parseSnapshot,
  parseTask,
  parseTasks
} from '../model/parse';
import { bindToJson, planToJson, taskToJson } from '../model/serialize';
import {
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

const CONNECT_TIMEOUT_MS = 8000;
const READ_TIMEOUT_MS = 8000;

/**
 * 直连 FastAPI。无鉴权。
 * 只调用任务、场景、快照、规划和余量查询，不发送执行或飞控指令。
 */
export class HttpDataSource implements DataSource {
  private readonly base: string;

  constructor(apiBase: string) {
    const trimmed = apiBase.trim().replace(/\/+$/, '');
    if (trimmed.indexOf('http://') !== 0 && trimmed.indexOf('https://') !== 0) {
      throw new ApiError(0, 'API 地址需要以 http:// 或 https:// 开头');
    }
    this.base = trimmed;
  }

  getHealth(): Promise<Health> {
    return this.send('GET', '/health', null).then((text: string) => parseHealth(this.body(text)));
  }

  listTasks(): Promise<Task[]> {
    return this.send('GET', '/tasks', null).then((text: string) => parseTasks(this.body(text)));
  }

  getTask(taskId: string): Promise<Task> {
    return this.send('GET', '/tasks/' + encodeURIComponent(taskId), null)
      .then((text: string) => parseTask(this.body(text)));
  }

  createTask(task: Task): Promise<Task> {
    return this.send('POST', '/tasks', taskToJson(task)).then((text: string) => parseTask(this.body(text)));
  }

  getScene(sceneId: string): Promise<SceneDocument> {
    return this.send('GET', '/scenes/' + encodeURIComponent(sceneId), null)
      .then((text: string) => parseScene(this.body(text)));
  }

  snapshotFromScene(taskId: string, request: SceneBindRequest): Promise<SceneBindResult> {
    const path = '/tasks/' + encodeURIComponent(taskId) + '/snapshots/from-scene';
    return this.send('POST', path, bindToJson(request)).then((text: string) => parseBind(this.body(text)));
  }

  getLatestSnapshot(taskId: string): Promise<RiskSnapshot> {
    const path = '/tasks/' + encodeURIComponent(taskId) + '/snapshot';
    return this.send('GET', path, null).then((text: string) => parseSnapshot(this.body(text)));
  }

  getSnapshot(taskId: string, snapshotId: string): Promise<RiskSnapshot> {
    const path = '/tasks/' + encodeURIComponent(taskId) + '/snapshots/' + encodeURIComponent(snapshotId);
    return this.send('GET', path, null).then((text: string) => parseSnapshot(this.body(text)));
  }

  plan(taskId: string, request: PlanRequest): Promise<PlanResponse> {
    const path = '/tasks/' + encodeURIComponent(taskId) + '/plan';
    return this.send('POST', path, planToJson(request)).then((text: string) => parsePlan(this.body(text)));
  }

  listRoutes(taskId: string): Promise<RouteRecord[]> {
    const path = '/tasks/' + encodeURIComponent(taskId) + '/routes';
    return this.send('GET', path, null).then((text: string) => parseRoutes(this.body(text)));
  }

  getRoute(taskId: string, routeId: string): Promise<RouteRecord> {
    const path = '/tasks/' + encodeURIComponent(taskId) + '/routes/' + encodeURIComponent(routeId);
    return this.send('GET', path, null).then((text: string) => parseRoute(this.body(text)));
  }

  getMargin(taskId: string, routeId: string): Promise<MarginView> {
    const path = '/tasks/' + encodeURIComponent(taskId) + '/routes/' + encodeURIComponent(routeId) + '/margin';
    return this.send('GET', path, null).then((text: string) => parseMargin(this.body(text)));
  }

  private body(text: string): ESObject {
    try {
      return JSON.parse(text) as ESObject;
    } catch (_err) {
      throw new ApiError(0, '响应不是 JSON');
    }
  }

  private async send(method: string, path: string, payload: string | null): Promise<string> {
    const httpRequest = http.createHttp();
    const verb = method === 'POST' ? http.RequestMethod.POST : http.RequestMethod.GET;
    try {
      const options: http.HttpRequestOptions = {
        method: verb,
        header: { 'Content-Type': 'application/json' },
        expectDataType: http.HttpDataType.STRING,
        connectTimeout: CONNECT_TIMEOUT_MS,
        readTimeout: READ_TIMEOUT_MS,
        usingCache: false,
        usingProtocol: http.HttpProtocol.HTTP1_1
      };
      if (payload !== null) {
        options.extraData = payload;
      }
      const response = await httpRequest.request(this.base + path, options);
      const text = responseText(response.result);
      if (response.responseCode < 200 || response.responseCode >= 300) {
        throw new ApiError(response.responseCode, formatDetail(text));
      }
      return text;
    } catch (err) {
      if (err instanceof ApiError) {
        throw err;
      }
      if (err instanceof ParseError) {
        throw new ApiError(0, '响应无法解析：' + err.message);
      }
      throw networkError(err);
    } finally {
      httpRequest.destroy();
    }
  }
}

function responseText(result: string | Object | ArrayBuffer): string {
  if (typeof result === 'string') {
    return result;
  }
  return JSON.stringify(result);
}

function networkError(err: Object): ApiError {
  const business = err as BusinessError;
  const code = typeof business.code === 'number' ? business.code : 0;
  const message = err instanceof Error ? err.message : '网络请求失败';
  if (code === 2300028) {
    return new ApiError(0, '请求超时');
  }
  if (code === 2300997) {
    return new ApiError(0, '明文 HTTP 被系统拒绝。请确认已允许明文，或把地址改成 https。');
  }
  return new ApiError(0, '请求失败：' + message);
}
