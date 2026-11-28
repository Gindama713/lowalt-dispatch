import { common } from '@kit.AbilityKit';

export class AppHost {
  static context: common.UIAbilityContext | null = null;

  static init(context: common.UIAbilityContext): void {
    AppHost.context = context;
  }

  static requireContext(): common.UIAbilityContext {
    if (AppHost.context === null) {
      throw new Error('UIAbility 尚未初始化');
    }
    return AppHost.context;
  }
}
