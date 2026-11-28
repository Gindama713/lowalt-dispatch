import { AlertStore } from '../client/AlertStore';
import { HttpDataSource } from '../client/HttpDataSource';
import { Repository } from '../client/Repository';
import { AppSettings, DEFAULT_API_BASE, SettingsStore } from '../client/SettingsStore';
import { Health } from '../model/types';
import { Drone3DBackground } from '../view/Drone3DBackground';
import { TopBar } from '../view/TopBar';

@Entry
@Component
struct SettingsPage {
  @State mode: string = 'mock';
  @State apiBase: string = DEFAULT_API_BASE;
  @StorageLink('bg3dEnabled') bg3dEnabled: boolean = true;
  @State message: string = '';
  @State errorText: string = '';
  @State testing: boolean = false;

  aboutToAppear(): void {
    const settings = SettingsStore.load();
    this.mode = settings.mode;
    this.apiBase = settings.apiBase;
    SettingsStore.publish(settings);
  }

  private save(): void {
    const settings = new AppSettings();
    settings.mode = this.mode === 'http' ? 'http' : 'mock';
    settings.apiBase = this.apiBase.trim().length === 0 ? DEFAULT_API_BASE : this.apiBase.trim();
    settings.bg3dEnabled = this.bg3dEnabled;
    this.apiBase = settings.apiBase;
    SettingsStore.save(settings);
    Repository.invalidate();
    this.errorText = '';
    this.message = '已保存。下次进入页面会按这个数据源请求。';
  }

  private testConnection(): void {
    this.testing = true;
    this.message = '';
    this.errorText = '';
    let source: HttpDataSource;
    try {
      source = new HttpDataSource(this.apiBase);
    } catch (err) {
      this.errorText = AlertStore.recordFromError('测试连接', err as Object);
      this.testing = false;
      return;
    }
    source.getHealth().then((health: Health) => {
      this.testing = false;
      this.message = '已连通。status=' + health.status + '，storage_backend=' + health.storage_backend +
        '，service=' + health.service;
      if (health.status === 'degraded') {
        AlertStore.add('health_degraded', '服务降级', '测试连接时 /health 为 degraded。' + health.storage_note, '设置');
      }
    }).catch((err: Object) => {
      this.testing = false;
      this.errorText = AlertStore.recordFromError('测试连接', err);
    });
  }

  build() {
    Stack() {
      Drone3DBackground({ scrimColor: '#5207121C' })
      Column() {
        TopBar({ title: '设置', showBack: true })
        Scroll() {
          Column() {
            Column() {
              Text('3D 无人机背景动效')
                .fontSize(16)
                .fontWeight(FontWeight.Medium)
              Row() {
                Text('开启 CR30 旋转与零件循环拆解背景')
                  .fontSize(13)
                  .fontColor('#3D4A45')
                  .layoutWeight(1)
                Toggle({ type: ToggleType.Switch, isOn: this.bg3dEnabled })
                  .onChange((isOn: boolean) => {
                    this.bg3dEnabled = isOn;
                    SettingsStore.setBg3dEnabled(isOn);
                  })
              }
              .width('100%')
              .margin({ top: 8 })
              .alignItems(VerticalAlign.Center)
            }
            .width('100%')
            .padding(14)
            .margin({ bottom: 12 })
            .backgroundColor('#D9FFFFFF')
            .border({ width: 1, color: '#66FFFFFF' })
            .borderRadius(12)
            .alignItems(HorizontalAlign.Start)

            Column() {
              Text('数据源')
                .fontSize(16)
                .fontWeight(FontWeight.Medium)
              Row() {
                Radio({ value: 'mock', group: 'source' })
                  .checked(this.mode === 'mock')
                  .onChange((on: boolean) => {
                    if (on) {
                      this.mode = 'mock';
                    }
                  })
                Text('Mock 示例')
                  .margin({ left: 8 })
              }
              .margin({ top: 8 })
              Row() {
                Radio({ value: 'http', group: 'source' })
                  .checked(this.mode === 'http')
                  .onChange((on: boolean) => {
                    if (on) {
                      this.mode = 'http';
                    }
                  })
                Text('真实接口')
                  .margin({ left: 8 })
              }
              .margin({ top: 8 })

              Text('API 地址')
                .fontSize(16)
                .fontWeight(FontWeight.Medium)
                .margin({ top: 16 })
              Text('手机和后端怎么连通还没定，同 Wi-Fi 或公网都可以。把地址改成手机实际能访问的主机，默认只是占位。')
                .fontSize(13)
                .fontColor('#3D4A45')
                .margin({ top: 4 })
              TextInput({ text: this.apiBase, placeholder: DEFAULT_API_BASE })
                .width('100%')
                .height(44)
                .margin({ top: 8 })
                .backgroundColor('#F2FFFFFF')
                .onChange((value: string) => {
                  this.apiBase = value;
                })

              Text('测试连接会请求这个地址的 GET /health，跟当前是 Mock 还是真实接口无关。')
                .fontSize(13)
                .fontColor('#3D4A45')
                .margin({ top: 8 })
              Text('工程允许明文 HTTP，方便局域网调试。公网请改成 https。')
                .fontSize(13)
                .fontColor('#7A4E00')
                .margin({ top: 4 })

              Button(this.testing ? '正在测试…' : '测试连接')
                .width('100%')
                .margin({ top: 12 })
                .backgroundColor('#355C7D')
                .enabled(!this.testing)
                .onClick(() => {
                  this.testConnection();
                })
              Button('保存')
                .width('100%')
                .margin({ top: 8 })
                .backgroundColor('#0B6E4F')
                .onClick(() => {
                  this.save();
                })

              if (this.message.length > 0) {
                Text(this.message)
                  .fontSize(13)
                  .fontColor('#0B6E4F')
                  .margin({ top: 12 })
              }
              if (this.errorText.length > 0) {
                Text(this.errorText)
                  .fontSize(13)
                  .fontColor('#B42318')
                  .margin({ top: 12 })
              }
              Text('保存后，首页、任务和地图都会改用所选数据源。测试连接只访问上面的地址。')
                .fontSize(12)
                .fontColor('#6B7873')
                .margin({ top: 16 })
            }
            .width('100%')
            .padding(14)
            .backgroundColor('#D9FFFFFF')
            .border({ width: 1, color: '#66FFFFFF' })
            .borderRadius(12)
            .alignItems(HorizontalAlign.Start)
          }
          .width('100%')
          .padding(16)
          .alignItems(HorizontalAlign.Start)
        }
        .layoutWeight(1)
      }
      .width('100%')
      .height('100%')
    }
    .width('100%')
    .height('100%')
  }
}
