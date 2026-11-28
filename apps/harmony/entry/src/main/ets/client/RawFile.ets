import { util } from '@kit.ArkTS';
import { AppHost } from './AppHost';

export function readRawText(relativePath: string): string {
  const context = AppHost.requireContext();
  const bytes = context.resourceManager.getRawFileContentSync(relativePath);
  const decoder = util.TextDecoder.create('utf-8', { ignoreBOM: true });
  return decoder.decodeToString(bytes);
}
