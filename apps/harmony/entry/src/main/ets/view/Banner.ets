@Component
export struct Banner {
  @StorageLink('sourceMode') sourceMode: string = 'mock';

  build() {
    Column() {
      Row() {
        Text(this.sourceMode === 'http' ? '真实接口' : 'MOCK')
          .fontSize(12)
          .fontColor(this.sourceMode === 'http' ? '#0B4F6E' : '#7A4E00')
          .backgroundColor(this.sourceMode === 'http' ? '#E6F4FA' : '#FFF4D6')
          .borderRadius(4)
          .padding({ left: 8, right: 8, top: 3, bottom: 3 })
        Text('仿真数据')
          .fontSize(12)
          .fontColor('#7A2E0E')
          .backgroundColor('#FDE7D9')
          .borderRadius(4)
          .padding({ left: 8, right: 8, top: 3, bottom: 3 })
          .margin({ left: 8 })
      }
      .width('100%')

      Text('场景、航线和示例任务都是仿真或构造数据，不是实测飞行。本应用不下发飞控指令。')
        .fontSize(12)
        .fontColor('#5C4033')
        .margin({ top: 6 })
        .width('100%')
    }
    .width('100%')
    .padding({ left: 16, right: 16, top: 10, bottom: 8 })
    .backgroundColor('#EBF7F0E8')
    .alignItems(HorizontalAlign.Start)
  }
}
