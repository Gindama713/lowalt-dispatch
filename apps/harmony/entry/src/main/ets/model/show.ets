import type { Position } from './types';

export function showText(value: string | null): string {
  if (value === null || value.length === 0) {
    return 'null';
  }
  return value;
}

export function showNumber(value: number | null): string {
  if (value === null) {
    return 'null';
  }
  return String(value);
}

export function showBool(value: boolean | null): string {
  if (value === null) {
    return 'null';
  }
  return value ? 'true' : 'false';
}

export function showPosition(position: Position): string {
  if (position.frame === 'enu_m') {
    return 'ENU (' + String(position.x_m) + ', ' + String(position.y_m) + ') m，高度 ' +
      String(position.alt_m) + ' / ' + position.alt_ref;
  }
  return 'WGS84 (' + String(position.lat_deg) + ', ' + String(position.lon_deg) + ')，高度 ' +
    String(position.alt_m) + ' / ' + position.alt_ref;
}
