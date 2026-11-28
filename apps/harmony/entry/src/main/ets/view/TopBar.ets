import { router } from '@kit.ArkUI';
import { SettingsStore } from '../client/SettingsStore';
import { Banner } from './Banner';

@Component
export struct TopBar {
  @Prop title: string = '';
  @Prop showBack: boolean = true;
  @StorageLink('bg3dEnabled') bg3dEnabled: boolean = true;

  build() {
    Column() {
      Banner()
      Row() {
        if (this.showBack) {
          Text('返回')
            .fontSize(16)
            .fontColor('#0B6E4F')
            .onClick(() => {
              router.back();
            })
        }
        Text(this.title)
          .fontSize(20)
          .fontWeight(FontWeight.Medium)
          .fontColor('#10231E')
          .margin({ left: this.showBack ? 12 : 0 })
        Blank()
        Text(this.bg3dEnabled ? '3D背景：开' : '3D背景：关')
          .fontSize(11)
          .fontColor(this.bg3dEnabled ? '#0A5E46' : '#5A6965')
          .backgroundColor(this.bg3dEnabled ? '#D9E6F7F1' : '#D9E9EEEC')
          .borderRadius(12)
          .padding({ left: 10, right: 10, top: 4, bottom: 4 })
          .onClick(() => {
            SettingsStore.setBg3dEnabled(!this.bg3dEnabled);
          })
      }
      .width('100%')
      .padding({ left: 16, right: 16, top: 6, bottom: 10 })
      .alignItems(VerticalAlign.Center)
    }
    .width('100%')
    .backgroundColor('#E6FFFFFF')
    .border({ width: { bottom: 1 }, color: '#33FFFFFF' })
    .alignItems(HorizontalAlign.Start)
  }
}
