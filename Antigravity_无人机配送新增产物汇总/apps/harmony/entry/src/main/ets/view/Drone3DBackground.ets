import { webview } from '@kit.ArkWeb';
import { AppHost } from '../client/AppHost';

const VIRTUAL_ORIGIN = 'https://local.aeris.app/drone3d/';
const ENTRY_URL = VIRTUAL_ORIGIN + 'index.html';

function resolveMimeType(path: string): string {
  const lower = path.toLowerCase();
  if (lower.endsWith('.html')) {
    return 'text/html';
  }
  if (lower.endsWith('.js') || lower.endsWith('.mjs')) {
    return 'application/javascript';
  }
  if (lower.endsWith('.wasm')) {
    return 'application/wasm';
  }
  if (lower.endsWith('.glb')) {
    return 'model/gltf-binary';
  }
  if (lower.endsWith('.json')) {
    return 'application/json';
  }
  if (lower.endsWith('.css')) {
    return 'text/css';
  }
  return 'application/octet-stream';
}

function sanitizeRelativePath(rawUrl: string): string {
  const withoutOrigin = rawUrl.substring(VIRTUAL_ORIGIN.length);
  const queryIdx = withoutOrigin.indexOf('?');
  const hashIdx = withoutOrigin.indexOf('#');
  let clean = withoutOrigin;
  if (queryIdx >= 0) {
    clean = clean.substring(0, queryIdx);
  }
  if (hashIdx >= 0 && (queryIdx < 0 || hashIdx < queryIdx)) {
    clean = clean.substring(0, hashIdx);
  }
  if (clean.length === 0) {
    return 'index.html';
  }
  if (clean.indexOf('..') >= 0) {
    return '';
  }
  return clean;
}

/**
 * 全屏 3D 无人机背景层：加载 rawfile/drone3d/ 下的离线 CR30 模型，
 * 持续平稳旋转并循环执行 318 零件爆炸拆解/复原动画。
 * 通过 HitTestMode.None 与 focusable(false) 保证绝不拦截前景点击、滚动或输入。
 */
@Component
export struct Drone3DBackground {
  @Prop scrimColor: string = '#4D07121C';
  @StorageLink('bg3dEnabled') @Watch('onBgToggle') bg3dEnabled: boolean = true;
  private controller: webview.WebviewController = new webview.WebviewController();
  private pageReady: boolean = false;

  onBgToggle(): void {
    if (!this.bg3dEnabled) {
      this.pageReady = false;
      return;
    }
    this.syncPausedState();
  }

  private syncPausedState(): void {
    if (!this.pageReady) {
      return;
    }
    const flag = this.bg3dEnabled ? 'false' : 'true';
    try {
      this.controller.runJavaScript(
        'window.__aerisDrone3d && window.__aerisDrone3d.setPaused(' + flag + ');'
      );
    } catch (_err) {
      // Ignore if WebView is being torn down
    }
  }

  private handleIntercept(url: string): WebResourceResponse | null {
    if (!url.startsWith(VIRTUAL_ORIGIN)) {
      return null;
    }
    const relPath = sanitizeRelativePath(url);
    const response = new WebResourceResponse();
    if (relPath.length === 0) {
      response.setResponseCode(400);
      response.setReasonMessage('Bad Request');
      response.setResponseIsReady(true);
      return response;
    }
    try {
      const ctx = AppHost.requireContext();
      const bytes: Uint8Array = ctx.resourceManager.getRawFileContentSync('drone3d/' + relPath);
      const buffer: ArrayBuffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
      const mime = resolveMimeType(relPath);
      const headers: Array<Header> = [
        { headerKey: 'Access-Control-Allow-Origin', headerValue: '*' },
        { headerKey: 'Cache-Control', headerValue: 'max-age=3600' }
      ];
      response.setResponseHeader(headers);
      response.setResponseData(buffer);
      response.setResponseMimeType(mime);
      if (mime.startsWith('text/') || mime === 'application/javascript' || mime === 'application/json') {
        response.setResponseEncoding('utf-8');
      }
      response.setResponseCode(200);
      response.setReasonMessage('OK');
      response.setResponseIsReady(true);
      return response;
    } catch (_err) {
      response.setResponseCode(404);
      response.setReasonMessage('Not Found');
      response.setResponseIsReady(true);
      return response;
    }
  }

  build() {
    Stack() {
      // 底层深空渐变底色（WebGL 初始化前与关闭 3D 背景时兜底）
      Column()
        .width('100%')
        .height('100%')
        .linearGradient({
          direction: GradientDirection.Bottom,
          colors: [['#0A1926', 0.0], ['#0F2436', 0.48], ['#07111A', 1.0]]
        })

      if (this.bg3dEnabled) {
        Web({ src: ENTRY_URL, controller: this.controller })
          .width('100%')
          .height('100%')
          .backgroundColor('#07111A')
          .javaScriptAccess(true)
          .domStorageAccess(true)
          .fileAccess(false)
          .zoomAccess(false)
          .overviewModeAccess(true)
          .focusable(false)
          .hitTestBehavior(HitTestMode.None)
          .onInterceptRequest((event) => {
            if (event && event.request) {
              return this.handleIntercept(event.request.getRequestUrl());
            }
            return null;
          })
          .onPageEnd(() => {
            this.pageReady = true;
            this.syncPausedState();
          })
      }

      // 柔和暗色遮罩，确保前景卡片与文字在零件拆解运动时依然清晰易读
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.scrimColor)
        .hitTestBehavior(HitTestMode.None)
    }
    .width('100%')
    .height('100%')
    .hitTestBehavior(HitTestMode.None)
    .focusable(false)
  }
}
