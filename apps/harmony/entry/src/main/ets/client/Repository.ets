import { DataSource } from './DataSource';
import { HttpDataSource } from './HttpDataSource';
import { openMockDataSource } from './MockFileSource';
import { AppSettings, SettingsStore } from './SettingsStore';

export class Repository {
  private static source: DataSource | null = null;
  private static signature: string = '';

  static get(): DataSource {
    const settings: AppSettings = SettingsStore.load();
    const signature = settings.mode + '|' + settings.apiBase;
    if (Repository.source !== null && Repository.signature === signature) {
      return Repository.source;
    }
    if (settings.mode === 'http') {
      Repository.source = new HttpDataSource(settings.apiBase);
    } else {
      Repository.source = openMockDataSource();
    }
    Repository.signature = signature;
    SettingsStore.publish(settings);
    return Repository.source;
  }

  static invalidate(): void {
    Repository.source = null;
    Repository.signature = '';
  }
}
