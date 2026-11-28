import { ApiError, ParseError } from '../model/errors';
import { parseAlerts } from '../model/parse';
import { LocalAlert } from '../model/types';
import { SettingsStore } from './SettingsStore';

const MAX_ALERTS = 50;

/** 后端没有告警接口。这里只汇总本机观察到的失败和降级。 */
export class AlertStore {
  private static items: LocalAlert[] = [];
  private static sequence: number = 1;

  static init(): void {
    try {
      const text = SettingsStore.readAlerts();
      const parsed = JSON.parse(text) as ESObject;
      AlertStore.items = parseAlerts(parsed);
    } catch (_err) {
      AlertStore.items = [];
    }
    AlertStore.publishCount();
  }

  static list(): LocalAlert[] {
    const copy: LocalAlert[] = [];
    for (let i = 0; i < AlertStore.items.length; i++) {
      copy.push(AlertStore.items[i]);
    }
    return copy;
  }

  static add(kind: string, title: string, detail: string, scope: string): void {
    if (AlertStore.items.length > 0) {
      const last = AlertStore.items[0];
      if (last.kind === kind && last.detail === detail && last.scope === scope) {
        return;
      }
    }
    const alert: LocalAlert = {
      id: 'A-' + String(Date.now()) + '-' + String(AlertStore.sequence),
      at: new Date().toISOString(),
      kind: kind,
      title: title,
      detail: detail,
      scope: scope
    };
    AlertStore.sequence++;
    const next: LocalAlert[] = [];
    next.push(alert);
    for (let i = 0; i < AlertStore.items.length && next.length < MAX_ALERTS; i++) {
      next.push(AlertStore.items[i]);
    }
    AlertStore.items = next;
    AlertStore.persist();
    AlertStore.publishCount();
  }

  static recordFromError(scope: string, err: Object): string {
    if (err instanceof ApiError) {
      if (err.status === 409 && err.detailText.indexOf('快照') >= 0) {
        AlertStore.add('snapshot_stale', '快照已过期', err.detailText, scope);
        return err.detailText;
      }
      if (err.status === 0 && err.detailText.indexOf('超时') >= 0) {
        AlertStore.add('timeout', '请求超时', err.detailText, scope);
        return err.detailText;
      }
      const text = scope + '：' + err.detailText;
      AlertStore.add('request_failed', '请求失败', text, scope);
      return err.detailText;
    }
    if (err instanceof ParseError) {
      const text = '响应无法解析：' + err.message;
      AlertStore.add('request_failed', '响应无法解析', scope + '：' + text, scope);
      return text;
    }
    const message = err instanceof Error ? err.message : '未知错误';
    AlertStore.add('request_failed', '请求失败', scope + '：' + message, scope);
    return message;
  }

  private static persist(): void {
    try {
      SettingsStore.writeAlerts(JSON.stringify(AlertStore.items));
    } catch (_err) {
      // 偏好写入失败时，列表仍留在内存里。
    }
  }

  private static publishCount(): void {
    AppStorage.setOrCreate('alertCount', AlertStore.items.length);
  }
}
