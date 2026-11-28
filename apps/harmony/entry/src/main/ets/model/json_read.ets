import { ParseError } from './errors';

export function asObject(value: ESObject, label: string): ESObject {
  if (value === undefined || value === null || Array.isArray(value) || typeof value !== 'object') {
    throw new ParseError(label + ' 不是对象');
  }
  return value;
}

/** mock JSON 外面包一层 example，避免把「示例」写进会被后端 extra=forbid 拒绝的字段。 */
export function unwrapPayload(text: string): ESObject {
  const root = asObject(JSON.parse(text) as ESObject, 'mock 文件');
  if (root['example'] !== true) {
    throw new ParseError('mock 文件必须标注 example: true');
  }
  const note = root['example_note'];
  if (typeof note !== 'string' || note.indexOf('示例') < 0) {
    throw new ParseError('mock 文件的 example_note 必须写明这是示例');
  }
  const payload = root['payload'] as ESObject;
  if (payload === undefined || payload === null) {
    throw new ParseError('mock 文件缺少 payload');
  }
  return payload;
}

export function stringField(obj: ESObject, key: string, label: string): string {
  const value = obj[key] as ESObject;
  if (typeof value !== 'string') {
    throw new ParseError(label + '.' + key + ' 必须是字符串');
  }
  return value;
}

export function reqString(obj: ESObject, key: string, label: string): string {
  const value = stringField(obj, key, label);
  if (value.length === 0) {
    throw new ParseError(label + '.' + key + ' 不能为空');
  }
  return value;
}

export function nullString(obj: ESObject, key: string, label: string): string | null {
  const value = obj[key] as ESObject;
  if (value === undefined || value === null) {
    return null;
  }
  if (typeof value !== 'string') {
    throw new ParseError(label + '.' + key + ' 必须是字符串或 null');
  }
  return value;
}

export function reqNumber(obj: ESObject, key: string, label: string): number {
  const value = obj[key] as ESObject;
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new ParseError(label + '.' + key + ' 必须是有限数字');
  }
  return value;
}

export function nullNumber(obj: ESObject, key: string, label: string): number | null {
  const value = obj[key] as ESObject;
  if (value === undefined || value === null) {
    return null;
  }
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new ParseError(label + '.' + key + ' 必须是数字或 null');
  }
  return value;
}

export function reqBool(obj: ESObject, key: string, label: string): boolean {
  const value = obj[key] as ESObject;
  if (typeof value !== 'boolean') {
    throw new ParseError(label + '.' + key + ' 必须是布尔值');
  }
  return value;
}

export function nullBool(obj: ESObject, key: string, label: string): boolean | null {
  const value = obj[key] as ESObject;
  if (value === undefined || value === null) {
    return null;
  }
  if (typeof value !== 'boolean') {
    throw new ParseError(label + '.' + key + ' 必须是布尔值或 null');
  }
  return value;
}

export function stringList(obj: ESObject, key: string, label: string): string[] {
  const value = obj[key] as ESObject;
  if (!Array.isArray(value)) {
    throw new ParseError(label + '.' + key + ' 必须是数组');
  }
  const out: string[] = [];
  for (let i = 0; i < value.length; i++) {
    const item = value[i] as ESObject;
    if (typeof item !== 'string') {
      throw new ParseError(label + '.' + key + ' 含有非字符串');
    }
    out.push(item);
  }
  return out;
}

export function objectList(value: ESObject, label: string): ESObject[] {
  if (!Array.isArray(value)) {
    throw new ParseError(label + ' 必须是数组');
  }
  const out: ESObject[] = [];
  for (let i = 0; i < value.length; i++) {
    out.push(asObject(value[i] as ESObject, label + '[' + String(i) + ']'));
  }
  return out;
}
