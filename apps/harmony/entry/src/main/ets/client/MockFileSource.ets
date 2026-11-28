import { MockDataSource } from './MockDataSource';
import { unwrapPayload } from '../model/json_read';
import {
  parseHealth,
  parseSeedRoutes,
  parseSeedSnapshots,
  parseScene,
  parseTasks
} from '../model/parse';
import { readRawText } from './RawFile';

/** 从 resources/rawfile/mock 读示例 JSON，再交给 MockDataSource。 */
export function openMockDataSource(): MockDataSource {
  const health = parseHealth(unwrapPayload(readRawText('mock/health.json')));
  const tasks = parseTasks(unwrapPayload(readRawText('mock/tasks.json')));
  const scene = parseScene(unwrapPayload(readRawText('mock/scene_v0.json')));
  const snapshots = parseSeedSnapshots(unwrapPayload(readRawText('mock/snapshots.json')));
  const routes = parseSeedRoutes(unwrapPayload(readRawText('mock/routes.json')));
  return MockDataSource.fromParts(health, tasks, scene, snapshots, routes);
}
