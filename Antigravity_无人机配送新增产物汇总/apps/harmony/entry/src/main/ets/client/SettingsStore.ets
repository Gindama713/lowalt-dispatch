import { preferences } from '@kit.ArkData';
import { AppHost } from './AppHost';

export const DEFAULT_API_BASE = 'http://192.168.1.10:8000';
const FILE_NAME = 'lowalt_settings';
const KEY_MODE = 'source_mode';
const KEY_BASE = 'api_base';
const KEY_ALERTS = 'alerts_json';
const KEY_BG3D = 'bg3d_enabled';

export class AppSettings {
  mode: string = 'mock';
  apiBase: string = DEFAULT_API_BASE;
  bg3dEnabled: boolean = true;
}

export class SettingsStore {
  static load(): AppSettings {
    const settings = new AppSettings();
    try {
      const pref = preferences.getPreferencesSync(AppHost.requireContext(), { name: FILE_NAME });
      const mode = pref.getSync(KEY_MODE, 'mock');
      const base = pref.getSync(KEY_BASE, DEFAULT_API_BASE);
      const bg3d = pref.getSync(KEY_BG3D, true);
      if (typeof mode === 'string' && (mode === 'mock' || mode === 'http')) {
        settings.mode = mode;
      }
      if (typeof base === 'string' && base.length > 0) {
        settings.apiBase = base;
      }
      if (typeof bg3d === 'boolean') {
        settings.bg3dEnabled = bg3d;
      }
    } catch (_err) {
      settings.mode = 'mock';
      settings.apiBase = DEFAULT_API_BASE;
      settings.bg3dEnabled = true;
    }
    return settings;
  }

  static save(settings: AppSettings): void {
    const pref = preferences.getPreferencesSync(AppHost.requireContext(), { name: FILE_NAME });
    const mode = settings.mode === 'http' ? 'http' : 'mock';
    pref.putSync(KEY_MODE, mode);
    pref.putSync(KEY_BASE, settings.apiBase.trim());
    pref.putSync(KEY_BG3D, settings.bg3dEnabled);
    pref.flushSync();
    SettingsStore.publish(settings);
  }

  static setBg3dEnabled(enabled: boolean): void {
    const current = SettingsStore.load();
    current.bg3dEnabled = enabled;
    SettingsStore.save(current);
  }

  static publish(settings: AppSettings): void {
    AppStorage.setOrCreate('sourceMode', settings.mode);
    AppStorage.setOrCreate('apiBase', settings.apiBase);
    AppStorage.setOrCreate('bg3dEnabled', settings.bg3dEnabled);
  }

  static readAlerts(): string {
    try {
      const pref = preferences.getPreferencesSync(AppHost.requireContext(), { name: FILE_NAME });
      const raw = pref.getSync(KEY_ALERTS, '[]');
      if (typeof raw === 'string') {
        return raw;
      }
    } catch (_err) {
      return '[]';
    }
    return '[]';
  }

  static writeAlerts(json: string): void {
    const pref = preferences.getPreferencesSync(AppHost.requireContext(), { name: FILE_NAME });
    pref.putSync(KEY_ALERTS, json);
    pref.flushSync();
  }
}
