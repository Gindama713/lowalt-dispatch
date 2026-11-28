import { router } from '@kit.ArkUI';
import { AlertStore } from '../client/AlertStore';
import { Repository } from '../client/Repository';
import { ApiError } from '../model/errors';
import { showBool, showNumber, showPosition, showText } from '../model/show';
import {
  LandingSite,
  MarginView,
  PlanRequest,
  RiskEvent,
  RiskSnapshot,
  RouteRecord,
  Task
} from '../model/types';
import { TopBar } from '../view/TopBar';
import { Drone3DBackground } from '../view/Drone3DBackground';

interface DetailParams {
  taskId?: string;
}

@Entry
@Component
struct TaskDetailPage {
  @State taskId: string = '';
  @State task: Task | null = null;
  @State snapshot: RiskSnapshot | null = null;
  @State snapshotNote: string = '';
  @State routes: RouteRecord[] = [];
  @State selectedRouteId: string = '';
  @State margin: MarginView | null = null;
  @State errorText: string = '';
  @State busy: boolean = false;

  aboutToAppear(): void {
    const raw = router.getParams() as DetailParams;
    if (raw !== undefined && raw !== null && raw.taskId !== undefined) {
      this.taskId = raw.taskId;
    }
    this.reload();
  }

  private reload(): void {
    if (this.taskId.length === 0) {
      this.errorText = '缺少任务编号';
      return;
    }
    this.errorText = '';
    const source = Repository.get();
    source.getTask(this.taskId).then((task: Task) => {
      this.task = task;
    }).catch((err: Object) => {
      this.errorText = AlertStore.recordFromError('任务详情', err);
    });
    source.getLatestSnapshot(this.taskId).then((snapshot: RiskSnapshot) => {
      this.snapshot = snapshot;
      this.snapshotNote = '';
    }).catch((err: Object) => {
      this.snapshot = null;
      if (err instanceof ApiError && err.status === 404) {
        this.snapshotNote = err.detailText;
        return;
      }
      this.errorText = AlertStore.recordFromError('最新快照', err);
    });
    source.listRoutes(this.taskId).then((routes: RouteRecord[]) => {
      this.routes = routes;
      if (routes.length > 0) {
        this.selectedRouteId = routes[routes.length - 1].route_id;
        this.loadMargin(this.selectedRouteId);
      } else {
        this.selectedRouteId = '';
        this.margin = null;
      }
    }).catch((err: Object) => {
      this.errorText = AlertStore.recordFromError('航线列表', err);
    });
  }

  private loadMargin(routeId: string): void {
    Repository.get().getMargin(this.taskId, routeId).then((margin: MarginView) => {
      this.margin = margin;
    }).catch((err: Object) => {
      this.errorText = AlertStore.recordFromError('备降余量', err);
    });
  }

  private replan(): void {
    this.busy = true;
    this.errorText = '';
    const request: PlanRequest = {
      snapshot_id: this.snapshot === null ? null : this.snapshot.snapshot_id,
      algorithm: null
    };
    Repository.get().plan(this.taskId, request).then((plan) => {
      this.busy = false;
      if (!plan.route.found) {
        const reason = plan.route.reason === null ? 'found=false' : plan.route.reason;
        AlertStore.add('plan_not_found', '规划未找到航线', reason, this.taskId);
      }
      this.reload();
    }).catch((err: Object) => {
      this.busy = false;
      this.errorText = AlertStore.recordFromError('重新规划', err);
    });
  }

  build() {
    Stack() {
      Drone3DBackground({ scrimColor: '#5207121C' })
      Column() {
        TopBar({ title: '任务详情', showBack: true })
        Scroll() {
          Column() {
            if (this.errorText.length > 0) {
              Text(this.errorText)
                .fontSize(13)
                .fontColor('#B42318')
                .backgroundColor('#E6FFF0F0')
                .padding(10)
                .borderRadius(10)
                .margin({ bottom: 8 })
            }
            this.taskCard()
            this.snapshotCard()
            this.routeCard()
            this.marginCard()
            Button(this.busy ? '规划中…' : '重新规划')
              .width('100%')
              .margin({ top: 12 })
              .backgroundColor('#0B6E4F')
              .enabled(!this.busy)
              .onClick(() => {
                this.replan();
              })
            Button('在地图看')
              .width('100%')
              .margin({ top: 8 })
              .backgroundColor('#355C7D')
              .onClick(() => {
                router.pushUrl({
                  url: 'pages/MapPage',
                  params: { taskId: this.taskId, routeId: this.selectedRouteId }
                });
              })
            Text('重新规划只请求 POST /plan，不会下发执行指令。')
              .fontSize(12)
              .fontColor('#D9ECF5')
              .margin({ top: 8 })
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

  @Builder
  taskCard() {
    Column() {
      Text('任务单')
        .fontSize(16)
        .fontWeight(FontWeight.Medium)
      if (this.task !== null) {
        Text(this.task.task_id)
          .fontSize(15)
          .margin({ top: 6 })
        Text('起点 ' + showPosition(this.task.origin))
          .fontSize(13)
          .margin({ top: 4 })
        Text('终点 ' + showPosition(this.task.destination))
          .fontSize(13)
          .margin({ top: 2 })
        Text('载荷 ' + String(this.task.payload_kg) + ' kg，机型 ' + this.task.vehicle_type)
          .fontSize(13)
          .margin({ top: 4 })
        Text('初始能量 ' + String(this.task.initial_energy_wh) + ' Wh，保留 ' +
          String(this.task.reserve_energy_wh) + ' Wh')
          .fontSize(13)
          .margin({ top: 2 })
        Text('时限 ' + showNumber(this.task.time_limit_s) + ' 秒')
          .fontSize(13)
          .margin({ top: 2 })
        Text(this.task.provenance.is_simulated ? 'is_simulated：true' : 'is_simulated：false')
          .fontSize(13)
          .margin({ top: 4 })
        Text(showText(this.task.provenance.uncertainty_note))
          .fontSize(12)
          .fontColor('#5C6B66')
          .margin({ top: 2 })
      }
    }
    .width('100%')
    .padding(14)
    .backgroundColor('#D9FFFFFF')
    .border({ width: 1, color: '#66FFFFFF' })
    .borderRadius(12)
    .alignItems(HorizontalAlign.Start)
  }

  @Builder
  snapshotCard() {
    Column() {
      Text('最新快照')
        .fontSize(16)
        .fontWeight(FontWeight.Medium)
        .margin({ top: 12 })
      if (this.snapshotNote.length > 0) {
        Text(this.snapshotNote)
          .fontSize(13)
          .fontColor('#5C6B66')
          .margin({ top: 6 })
      }
      if (this.snapshot !== null) {
        Text(this.snapshot.snapshot_id)
          .fontSize(14)
          .margin({ top: 6 })
        Text('captured_at：' + this.snapshot.captured_at)
          .fontSize(12)
          .margin({ top: 2 })
        Text('valid_until：' + showText(this.snapshot.valid_until))
          .fontSize(12)
          .margin({ top: 2 })
        Text(showText(this.snapshot.note))
          .fontSize(12)
          .fontColor('#5C6B66')
          .margin({ top: 4 })
        ForEach(this.snapshot.events, (event: RiskEvent) => {
          Text(event.event_id + ' · ' + event.kind + ' · ' + showText(event.zone_id))
            .fontSize(12)
            .margin({ top: 4 })
        }, (event: RiskEvent) => event.event_id)
        ForEach(this.snapshot.landing_sites, (site: LandingSite) => {
          Text(site.site_id + (site.occupied ? ' 占用' : ' 空闲'))
            .fontSize(12)
            .margin({ top: 2 })
        }, (site: LandingSite) => site.site_id)
      }
    }
    .width('100%')
    .padding(14)
    .margin({ top: 10 })
    .backgroundColor('#D9FFFFFF')
    .border({ width: 1, color: '#66FFFFFF' })
    .borderRadius(12)
    .alignItems(HorizontalAlign.Start)
  }

  @Builder
  routeCard() {
    Column() {
      Text('航线版本')
        .fontSize(16)
        .fontWeight(FontWeight.Medium)
      if (this.routes.length === 0) {
        Text('还没有航线。')
          .fontSize(13)
          .fontColor('#5C6B66')
          .margin({ top: 6 })
      }
      ForEach(this.routes, (route: RouteRecord) => {
        Column() {
          Text(route.route_id + '  ' + route.algorithm + '  found=' + String(route.found))
            .fontSize(14)
          Text('length_m：' + showNumber(route.length_m) + '  reason：' + showText(route.reason))
            .fontSize(12)
            .margin({ top: 2 })
          Text('route_plan_status：' + route.route_plan_status + '  margin_status：' + route.margin_status)
            .fontSize(12)
            .margin({ top: 2 })
          Text(route.is_simulated ? '航线标记：仿真' : '航线标记：非仿真')
            .fontSize(12)
            .margin({ top: 2 })
        }
        .width('100%')
        .padding(8)
        .margin({ top: 8 })
        .backgroundColor(this.selectedRouteId === route.route_id ? '#E7F4EF' : '#F7F8F7')
        .borderRadius(8)
        .alignItems(HorizontalAlign.Start)
        .onClick(() => {
          this.selectedRouteId = route.route_id;
          this.loadMargin(route.route_id);
        })
      }, (route: RouteRecord) => route.route_id)
    }
    .width('100%')
    .padding(14)
    .margin({ top: 10 })
    .backgroundColor('#D9FFFFFF')
    .border({ width: 1, color: '#66FFFFFF' })
    .borderRadius(12)
    .alignItems(HorizontalAlign.Start)
  }

  @Builder
  marginCard() {
    Column() {
      Text('备降余量')
        .fontSize(16)
        .fontWeight(FontWeight.Medium)
      if (this.margin === null) {
        Text('选择一条航线后显示。没有航线时这里是空的。')
          .fontSize(13)
          .fontColor('#5C6B66')
          .margin({ top: 6 })
      } else {
        Text('status：' + this.margin.status)
          .fontSize(15)
          .fontColor(this.margin.status === 'available' ? '#0B6E4F' : '#B54708')
          .margin({ top: 6 })
        Text(this.margin.detail)
          .fontSize(13)
          .margin({ top: 4 })
        Text('min_margin_wh：' + showNumber(this.margin.min_margin_wh))
          .fontSize(13)
          .margin({ top: 6 })
        Text('negative_sample_count：' + showNumber(this.margin.negative_sample_count))
          .fontSize(13)
          .margin({ top: 2 })
        Text('is_feasible：' + showBool(this.margin.is_feasible))
          .fontSize(13)
          .margin({ top: 2 })
        if (this.margin.status === 'unavailable') {
          Text('不可用时这三个值保持 null，页面不会写成 0。')
            .fontSize(12)
            .fontColor('#7A4E00')
            .margin({ top: 6 })
        }
      }
    }
    .width('100%')
    .padding(14)
    .margin({ top: 10 })
    .backgroundColor('#D9FFFFFF')
    .border({ width: 1, color: '#66FFFFFF' })
    .borderRadius(12)
    .alignItems(HorizontalAlign.Start)
  }
}
