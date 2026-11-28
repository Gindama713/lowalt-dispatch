import { AlertStore } from '../client/AlertStore';
import { LocalAlert } from '../model/types';
import { Drone3DBackground } from '../view/Drone3DBackground';
import { TopBar } from '../view/TopBar';

@Entry
@Component
struct AlertsPage {
  @State alerts: LocalAlert[] = [];
  @State refreshing: boolean = false;

  aboutToAppear(): void {
    this.reload();
  }

  onPageShow(): void {
    this.reload();
  }

  private reload(): void {
    this.alerts = AlertStore.list();
    this.refreshing = false;
  }

  build() {
    Stack() {
      Drone3DBackground({ scrimColor: '#5207121C' })
      Column() {
        TopBar({ title: '告警', showBack: true })
        Refresh({ refreshing: $$this.refreshing }) {
          List({ space: 10 }) {
            ListItem() {
              Text('这些告警由手机端根据规划结果和请求失败汇总。后端没有告警接口。')
                .fontSize(13)
                .fontColor('#5C4033')
                .padding(12)
                .backgroundColor('#E6FFF8F2')
                .borderRadius(12)
            }
            if (this.alerts.length === 0) {
              ListItem() {
                Text('还没有告警。')
                  .fontSize(14)
                  .fontColor('#D9ECF5')
                  .padding(12)
              }
            }
            ForEach(this.alerts, (alert: LocalAlert) => {
              ListItem() {
                Column() {
                  Text(alert.title)
                    .fontSize(16)
                    .fontWeight(FontWeight.Medium)
                    .fontColor(alert.kind === 'plan_not_found' || alert.kind === 'snapshot_stale' ? '#B54708' : '#B42318')
                  Text(alert.at)
                    .fontSize(12)
                    .fontColor('#6B7873')
                    .margin({ top: 4 })
                  Text(alert.scope)
                    .fontSize(12)
                    .fontColor('#3D4A45')
                    .margin({ top: 2 })
                  Text(alert.detail)
                    .fontSize(13)
                    .margin({ top: 6 })
                }
                .width('100%')
                .padding(14)
                .backgroundColor('#D9FFFFFF')
                .border({ width: 1, color: '#66FFFFFF' })
                .borderRadius(12)
                .alignItems(HorizontalAlign.Start)
              }
            }, (alert: LocalAlert) => alert.id)
          }
          .width('100%')
          .height('100%')
          .padding(16)
        }
        .layoutWeight(1)
        .onRefreshing(() => {
          this.refreshing = true;
          this.reload();
        })
      }
      .width('100%')
      .height('100%')
    }
    .width('100%')
    .height('100%')
  }
}
