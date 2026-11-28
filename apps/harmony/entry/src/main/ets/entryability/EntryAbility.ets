import { AbilityConstant, UIAbility, Want } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { window } from '@kit.ArkUI';
import { AlertStore } from '../client/AlertStore';
import { AppHost } from '../client/AppHost';
import { SettingsStore } from '../client/SettingsStore';

const TAG = 'LowaltAbility';
const DOMAIN = 0xD001;

export default class EntryAbility extends UIAbility {
  onCreate(_want: Want, _launchParam: AbilityConstant.LaunchParam): void {
    AppHost.init(this.context);
    SettingsStore.publish(SettingsStore.load());
    AlertStore.init();
    hilog.info(DOMAIN, TAG, 'onCreate');
  }

  onDestroy(): void {
    hilog.info(DOMAIN, TAG, 'onDestroy');
  }

  onWindowStageCreate(windowStage: window.WindowStage): void {
    windowStage.loadContent('pages/Index', (err) => {
      if (err.code) {
        hilog.error(DOMAIN, TAG, 'loadContent failed %{public}d', err.code);
      }
    });
  }

  onWindowStageDestroy(): void {
    hilog.info(DOMAIN, TAG, 'onWindowStageDestroy');
  }
}
