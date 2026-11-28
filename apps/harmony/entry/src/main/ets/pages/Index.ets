import { router } from '@kit.ArkUI';
import { AlertStore } from '../client/AlertStore';
import { describeDefaultNetwork } from '../client/NetworkLabel';
import { Repository } from '../client/Repository';
import { Health } from '../model/types';
import { Drone3DBackground } from '../view/Drone3DBackground';
import { TopBar } from '../view/TopBar';

@Entry
@Component
struct Index {
  @State health: Health | null = null;
  @State errorText: string = '';
  @State refreshing: boolean = false;
  @State networkLabel: string = '正在读取网络…';
  @State refreshedAt: string = '';
  @StorageLink('alertCount') alertCount: number = 0;
  @StorageLink('sourceMode') sourceMode: string = 'mock';
  @StorageLink('apiBase') apiBase: string = '';
  private timerId: number = -1;

  aboutToAppear(): void {
    this.reload();
    this.readNetwork();
  }

  onPageShow(): void {
    this.stopPoll();
    this.timerId = setInterval(() => {
      this.reload();
    }, 10000);
  }

  onPageHide(): void {
    this.stopPoll();
  }

  aboutToDisappear(): void {
    this.stopPoll();
  }

  private stopPoll(): void {
    if (this.timerId >= 0) {
      clearInterval(this.timerId);
      this.timerId = -1;
    }
  }

  private readNetwork(): void {
    describeDefaultNetwork().then((label: string) => {
      this.networkLabel = label;
    });
  }

  private reload(): void {
    this.errorText = '';
    Repository.get().getHealth().then((health: Health) => {
      this.health = health;
      this.refreshedAt = new Date().toISOString();
      this.refreshing = false;
      if (health.status === 'degraded') {
        AlertStore.add('health_degraded', '服务降级', 'GET /health 返回 degraded。' + health.storage_note, '首页');
      }
    }).catch((err: Object) => {
      this.errorText = AlertStore.recordFromError('首页 /health', err);
      this.refreshing = false;
    });
  }

  build() {
    Stack() {
      Drone3DBackground({ scrimColor: '#4207121C' })
      Column() {
        TopBar({ title: '低空调度', showBack: false })
        Refresh({ refreshing: $$this.refreshing }) {
          Scroll() {
            Column() {
              // 顶部留白视窗，让旋转拆解中的 CR30 无人机主机清晰呈现
              Column() {
                Text('AERIS · CR30 应急配送调度终端')
                  .fontSize(13)
                  .fontWeight(FontWeight.Medium)
                  .fontColor('#E6F7FF')
                Text('实时 3D 机体结构巡展（旋转 / 爆炸拆解循环）')
                  .fontSize(11)
                  .fontColor('#B8DCEB')
                  .margin({ top: 3 })
              }
              .width('100%')
              .padding({ left: 14, right: 14, top: 10, bottom: 10 })
              .margin({ bottom: 120 })
              .backgroundColor('#66091724')
              .borderRadius(12)
              .border({ width: 1, color: '#337CE0FF' })
              .alignItems(HorizontalAlign.Start)

              this.healthCard()
              this.menu()
            }
            .width('100%')
            .padding(16)
            .alignItems(HorizontalAlign.Start)
          }
          .width('100%')
          .height('100%')
          .align(Alignment.TopStart)
        }
        .layoutWeight(1)
        .onRefreshing(() => {
          this.refreshing = true;
          this.reload();
          this.readNetwork();
        })
      }
      .width('100%')
      .height('100%')
    }
    .width('100%')
    .height('100%')
  }

  @Builder
  healthCard() {
    Column() {
      Text('连接状态')
        .fontSize(16)
        .fontWeight(FontWeight.Medium)
      Text(this.sourceMode === 'http' ? '数据源：真实接口  ' + this.apiBase : '数据源：Mock 示例')
        .fontSize(13)
        .fontColor('#3D4A45')
        .margin({ top: 6 })
      Text('网络：' + this.networkLabel)
        .fontSize(13)
        .fontColor('#3D4A45')
        .margin({ top: 4 })
      if (this.errorText.length > 0) {
        Text(this.errorText)
          .fontSize(13)
          .fontColor('#B42318')
          .margin({ top: 8 })
      }
      if (this.health !== null) {
        Text('status：' + this.health.status)
          .fontSize(18)
          .fontColor(this.health.status === 'ok' ? '#0B6E4F' : '#B54708')
          .margin({ top: 8 })
        Text('storage_backend：' + this.health.storage_backend)
          .fontSize(14)
          .margin({ top: 4 })
        Text(this.health.storage_note)
          .fontSize(13)
          .fontColor('#3D4A45')
          .margin({ top: 4 })
        Text('schema_version：' + this.health.schema_version)
          .fontSize(13)
          .margin({ top: 8 })
        Text('service：' + this.health.service)
          .fontSize(13)
          .margin({ top: 2 })
        Text('git_commit：' + this.health.git_commit)
          .fontSize(13)
          .margin({ top: 2 })
        Text('planner_entry：' + this.health.planner_entry)
          .fontSize(13)
          .margin({ top: 2 })
        Text('postgres：' + this.health.postgres.name + ' configured=' + String(this.health.postgres.configured) +
          ' connected=' + String(this.health.postgres.connected))
          .fontSize(13)
          .margin({ top: 8 })
        Text(this.health.postgres.note)
          .fontSize(12)
          .fontColor('#5C6B66')
        Text('redis：' + this.health.redis.name + ' configured=' + String(this.health.redis.configured) +
          ' connected=' + String(this.health.redis.connected))
          .fontSize(13)
          .margin({ top: 6 })
        Text(this.health.redis.note)
          .fontSize(12)
          .fontColor('#5C6B66')
        Text('agent：' + this.health.agent.status)
          .fontSize(13)
          .margin({ top: 6 })
        Text(this.health.agent.detail)
          .fontSize(12)
          .fontColor('#5C6B66')
      }
      if (this.refreshedAt.length > 0) {
        Text('上次刷新：' + this.refreshedAt)
          .fontSize(12)
          .fontColor('#6B7873')
          .margin({ top: 8 })
      }
      Text('前台每 10 秒请求一次 /health，也可以下拉刷新。')
        .fontSize(12)
        .fontColor('#6B7873')
        .margin({ top: 4 })
    }
    .width('100%')
    .padding(14)
    .backgroundColor('#D9FFFFFF')
    .border({ width: 1, color: '#66FFFFFF' })
    .borderRadius(12)
    .alignItems(HorizontalAlign.Start)
  }

  @Builder
  menu() {
    Column() {
      Button('任务列表')
        .width('100%')
        .margin({ top: 12 })
        .backgroundColor('#0B6E4F')
        .onClick(() => {
          router.pushUrl({ url: 'pages/TaskListPage' });
        })
      Button('新建任务')
        .width('100%')
        .margin({ top: 8 })
        .backgroundColor('#0B6E4F')
        .onClick(() => {
          router.pushUrl({ url: 'pages/TaskCreatePage' });
        })
      Button('告警（' + String(this.alertCount) + '）')
        .width('100%')
        .margin({ top: 8 })
        .backgroundColor('#8A4B08')
        .onClick(() => {
          router.pushUrl({ url: 'pages/AlertsPage' });
        })
      Button('设置')
        .width('100%')
        .margin({ top: 8 })
        .backgroundColor('#355C7D')
        .onClick(() => {
          router.pushUrl({ url: 'pages/SettingsPage' });
        })
    }
    .width('100%')
  }
}
