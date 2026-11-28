/** HTTP 与 mock 共用的错误。detail 文本已经转成可读字符串。 */

export class ApiError extends Error {
  status: number;
  detailText: string;

  constructor(status: number, detailText: string) {
    super(detailText);
    this.name = 'ApiError';
    this.status = status;
    this.detailText = detailText;
  }
}

export class ParseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ParseError';
  }
}

/** FastAPI：业务错误 detail 是字符串；422 时 detail 是对象数组。 */
export function formatDetail(bodyText: string): string {
  if (bodyText.length === 0) {
    return '请求失败';
  }
  try {
    const raw = JSON.parse(bodyText) as ESObject;
    if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) {
      return bodyText;
    }
    const detail = raw['detail'] as ESObject;
    if (typeof detail === 'string') {
      return detail;
    }
    if (Array.isArray(detail)) {
      const lines: string[] = [];
      for (let i = 0; i < detail.length; i++) {
        lines.push(formatValidationItem(detail[i] as ESObject));
      }
      if (lines.length === 0) {
        return '请求体未通过校验';
      }
      return lines.join('\n');
    }
  } catch (_err) {
    return bodyText;
  }
  return bodyText;
}

function formatValidationItem(item: ESObject): string {
  if (item === null || typeof item !== 'object' || Array.isArray(item)) {
    return '字段不合法';
  }
  const locRaw = item['loc'] as ESObject;
  const parts: string[] = [];
  if (Array.isArray(locRaw)) {
    for (let i = 0; i < locRaw.length; i++) {
      parts.push(String(locRaw[i]));
    }
  }
  const msg = item['msg'];
  const message = typeof msg === 'string' ? msg : '字段不合法';
  if (parts.length === 0) {
    return message;
  }
  return parts.join('.') + '：' + message;
}
