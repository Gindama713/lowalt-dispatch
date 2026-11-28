import { router } from '@kit.ArkUI';
import { AlertStore } from '../client/AlertStore';
import { Repository } from '../client/Repository';
import { ParseError } from '../model/errors';
import { parseTask } from '../model/parse';
import { showNumber, showText } from '../model/show';
import { taskBody } from '../model/serialize';
import {
  GeoPolygon,
  LandingSite,
  PlanRequest,
  PlanResponse,
  Position,
  SceneDocument,
  Task
} from '../model/types';
import { TopBar } from '../view/TopBar';
import { Drone3DBackground } from '../view/Drone3DBackground';

@Component
struct Field {
  @Prop label: string = '';
  @Link text: string;

  build() {
    Column() {
      Text(this.label)
        .fontSize(13)
        .fontColor('#3D4A45')
      TextInput({ text: this.text })
        .width('100%')
        .height(40)
        .margin({ top: 4 })
        .onChange((value: string) => {
          this.text = value;
        })
    }
    .width('100%')
    .margin({ top: 8 })
    .alignItems(HorizontalAlign.Start)
  }
}

@Component
struct CheckRow {
  @Prop itemId: string = '';
  @Prop label: string = '';
  @Prop checked: boolean = false;
  onToggle: (id: string, on: boolean) => void = (_id: string, _on: boolean) => {
  };

  build() {
    Row() {
      Checkbox()
        .select(this.checked)
        .onChange((on: boolean) => {
          this.onToggle(this.itemId, on);
        })
      Text(this.label)
        .fontSize(14)
        .margin({ left: 8 })
        .layoutWeight(1)
    }
    .width('100%')
    .margin({ bottom: 8 })
  }
}

@Entry
@Component
struct TaskCreatePage {
  @State step: number = 0;
  @State errorText: string = '';
  @State busy: boolean = false;
  @State taskId: string = '';
  @State originX: string = '150';
  @State originY: string = '150';
  @State originAlt: string = '0';
  @State destX: string = '2650';
  @State destY: string = '2750';
  @State destAlt: string = '30';
  @State payload: string = '1';
  @State vehicleType: string = 'placeholder';
  @State initialEnergy: string = '100';
  @State reserveEnergy: string = '20';
  @State timeLimit: string = '';
  @State simulated: boolean = true;
  @State scene: SceneDocument | null = null;
  @State zoneIds: string[] = [];
  @State siteIds: string[] = [];
  @State snapshotId: string = '';
  @State algorithm: string = '';
  @State plan: PlanResponse | null = null;

  private fail(err: Object, recordAlert: boolean): void {
    if (recordAlert) {
      this.errorText = AlertStore.recordFromError('新建任务', err);
    } else if (err instanceof ParseError || err instanceof Error) {
      this.errorText = err.message;
    } else {
      this.errorText = '无法提交';
    }
    this.busy = false;
  }

  private readNumber(text: string, label: string): number {
    const value = Number(text);
    if (!Number.isFinite(value)) {
      throw new ParseError(label + ' 需要填写数字');
    }
    return value;
  }

  private buildTask(): Task {
    const origin: Position = {
      frame: 'enu_m',
      x_m: this.readNumber(this.originX, '起点东向'),
      y_m: this.readNumber(this.originY, '起点北向'),
      alt_m: this.readNumber(this.originAlt, '起点高度'),
      alt_ref: 'rel_takeoff',
      lat_deg: null,
      lon_deg: null
    };
    const destination: Position = {
      frame: 'enu_m',
      x_m: this.readNumber(this.destX, '终点东向'),
      y_m: this.readNumber(this.destY, '终点北向'),
      alt_m: this.readNumber(this.destAlt, '终点高度'),
      alt_ref: 'rel_takeoff',
      lat_deg: null,
      lon_deg: null
    };
    const limitText = this.timeLimit.trim();
    const task: Task = {
      task_id: this.taskId.trim(),
      origin: origin,
      destination: destination,
      payload_kg: this.readNumber(this.payload, '载荷'),
      vehicle_type: this.vehicleType.trim(),
      initial_energy_wh: this.readNumber(this.initialEnergy, '初始能量'),
      reserve_energy_wh: this.readNumber(this.reserveEnergy, '保留能量'),
      time_limit_s: limitText.length === 0 ? null : this.readNumber(limitText, '时限'),
      provenance: {
        source: 'harmony:manual',
        version: '0',
        captured_at: new Date().toISOString(),
        valid_from: null,
        valid_until: null,
        is_simulated: this.simulated,
        uncertainty_note: '示例。手机端手工填写，不是实测任务。'
      }
    };
    return parseTask(taskBody(task));
  }

  private submitTask(): void {
    this.busy = true;
    this.errorText = '';
    let task: Task;
    try {
      task = this.buildTask();
    } catch (err) {
      this.fail(err as Object, false);
      return;
    }
    Repository.get().createTask(task).then(() => {
      this.taskId = task.task_id;
      this.step = 1;
      this.busy = false;
      this.loadScene();
    }).catch((err: Object) => {
      this.fail(err, true);
    });
  }

  private loadScene(): void {
    this.busy = true;
    Repository.get().getScene('v0').then((scene: SceneDocument) => {
      this.scene = scene;
      this.busy = false;
    }).catch((err: Object) => {
      this.fail(err, true);
    });
  }

  private contains(list: string[], id: string): boolean {
    for (let i = 0; i < list.length; i++) {
      if (list[i] === id) {
        return true;
      }
    }
    return false;
  }

  private toggle(list: string[], id: string, on: boolean): string[] {
    const next: string[] = [];
    for (let i = 0; i < list.length; i++) {
      if (list[i] !== id) {
        next.push(list[i]);
      }
    }
    if (on) {
      next.push(id);
    }
    return next;
  }

  private submitScene(): void {
    this.busy = true;
    this.errorText = '';
    Repository.get().snapshotFromScene(this.taskId, {
      scene_id: 'v0',
      active_zone_ids: this.zoneIds,
      occupied_site_ids: this.siteIds
    }).then((result) => {
      this.snapshotId = result.snapshot.snapshot_id;
      this.step = 2;
      this.busy = false;
    }).catch((err: Object) => {
      this.fail(err, true);
    });
  }

  private submitPlan(): void {
    this.busy = true;
    this.errorText = '';
    const request: PlanRequest = {
      snapshot_id: this.snapshotId.length === 0 ? null : this.snapshotId,
      algorithm: this.algorithm.trim().length === 0 ? null : this.algorithm.trim()
    };
    Repository.get().plan(this.taskId, request).then((plan: PlanResponse) => {
      this.plan = plan;
      this.busy = false;
      if (!plan.route.found) {
        const reason = plan.route.reason === null ? 'found=false' : plan.route.reason;
        AlertStore.add('plan_not_found', '规划未找到航线', reason, this.taskId);
      }
    }).catch((err: Object) => {
      this.fail(err, true);
    });
  }

  build() {
    Stack() {
      Drone3DBackground({ scrimColor: '#5207121C' })
      Column() {
        TopBar({ title: '新建任务', showBack: true })
        Scroll() {
          Column() {
            Column() {
              Text(this.step === 0 ? '第 1 步 · 任务单' : (this.step === 1 ? '第 2 步 · 场景 v0' : '第 3 步 · 规划'))
                .fontSize(16)
                .fontWeight(FontWeight.Medium)
              Text('只提交任务、快照和规划请求，不会下发飞控指令。')
                .fontSize(12)
                .fontColor('#5C4033')
                .margin({ top: 4, bottom: 12 })
              if (this.step === 0) {
                this.taskForm()
              }
              if (this.step === 1) {
                this.sceneForm()
              }
              if (this.step === 2) {
                this.planForm()
              }
              if (this.errorText.length > 0) {
                Text(this.errorText)
                  .fontSize(13)
                  .fontColor('#B42318')
                  .margin({ top: 12 })
              }
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

  @Builder
  taskForm() {
    Field({ label: '任务编号', text: $taskId })
    Field({ label: '起点东向 x_m', text: $originX })
    Field({ label: '起点北向 y_m', text: $originY })
    Field({ label: '起点高度 alt_m（相对起飞）', text: $originAlt })
    Field({ label: '终点东向 x_m', text: $destX })
    Field({ label: '终点北向 y_m', text: $destY })
    Field({ label: '终点高度 alt_m（相对起飞）', text: $destAlt })
    Field({ label: '载荷 kg', text: $payload })
    Field({ label: '机型 vehicle_type', text: $vehicleType })
    Field({ label: '初始能量 Wh', text: $initialEnergy })
    Field({ label: '保留能量 Wh', text: $reserveEnergy })
    Field({ label: '时限 秒，留空表示不限', text: $timeLimit })
    Row() {
      Checkbox()
        .select(this.simulated)
        .onChange((on: boolean) => {
          this.simulated = on;
        })
      Text('任务单标记为仿真')
        .margin({ left: 8 })
    }
    .margin({ top: 10 })
    Text('坐标是局部 ENU 米，不是经纬度。默认起终点与接口文档示例相同。')
      .fontSize(12)
      .fontColor('#6B7873')
      .margin({ top: 8 })
    Button(this.busy ? '提交中…' : '提交任务单')
      .width('100%')
      .margin({ top: 12 })
      .backgroundColor('#0B6E4F')
      .enabled(!this.busy)
      .onClick(() => {
        this.submitTask();
      })
  }

  @Builder
  sceneForm() {
    if (this.scene !== null) {
      Text('scene_id：' + this.scene.scene_id + '，status：' + this.scene.geometry_status)
        .fontSize(13)
      Text(this.scene.is_simulated ? '场景标记：仿真' : '场景标记：非仿真')
        .fontSize(13)
        .margin({ top: 4 })
      Text(this.scene.crs_note)
        .fontSize(12)
        .fontColor('#5C4033')
        .margin({ top: 4 })
      Text('障碍 ' + String(this.scene.counts.obstacles) + '，限制区 ' +
        String(this.scene.counts.restriction_zones) + '，备降点 ' + String(this.scene.counts.landing_sites))
        .fontSize(13)
        .margin({ top: 4, bottom: 8 })
      Text('生效限制区（可多选）')
        .fontSize(14)
        .fontWeight(FontWeight.Medium)
      ForEach(this.scene.restriction_zones, (zone: GeoPolygon) => {
        CheckRow({
          itemId: zone.id,
          label: zone.id + '  高度 ' + showNumber(zone.alt_min_m) + '–' + showNumber(zone.alt_max_m) + ' m',
          checked: this.contains(this.zoneIds, zone.id),
          onToggle: (id: string, on: boolean) => {
            this.zoneIds = this.toggle(this.zoneIds, id, on);
          }
        })
      }, (zone: GeoPolygon) => zone.id)
      Text('占用备降点（可多选）')
        .fontSize(14)
        .fontWeight(FontWeight.Medium)
        .margin({ top: 8 })
      ForEach(this.scene.landing_sites, (site: LandingSite) => {
        CheckRow({
          itemId: site.site_id,
          label: site.site_id + '  (' + String(site.position.x_m) + ', ' + String(site.position.y_m) + ') 半径 ' +
            String(site.radius_m) + ' m',
          checked: this.contains(this.siteIds, site.site_id),
          onToggle: (id: string, on: boolean) => {
            this.siteIds = this.toggle(this.siteIds, id, on);
          }
        })
      }, (site: LandingSite) => site.site_id)
      Text('勾选 R04 且终点落在该多边形内时，示例规划会返回 found=false。真实接口还会绕开障碍。')
        .fontSize(12)
        .fontColor('#6B7873')
        .margin({ top: 4 })
    }
    Button(this.busy ? '提交中…' : '生成快照')
      .width('100%')
      .margin({ top: 12 })
      .backgroundColor('#0B6E4F')
      .enabled(!this.busy && this.scene !== null)
      .onClick(() => {
        this.submitScene();
      })
  }

  @Builder
  planForm() {
    Text('快照：' + this.snapshotId)
      .fontSize(13)
    Field({ label: 'algorithm，可留空', text: $algorithm })
    Text('留空则由服务端用当前入口。真实接口不会因为这个名字切换规划器。')
      .fontSize(12)
      .fontColor('#6B7873')
      .margin({ top: 4 })
    Button(this.busy ? '规划中…' : '开始规划')
      .width('100%')
      .margin({ top: 12 })
      .backgroundColor('#0B6E4F')
      .enabled(!this.busy)
      .onClick(() => {
        this.submitPlan();
      })
    if (this.plan !== null) {
      Text(this.plan.route.found ? 'found：true' : 'found：false')
        .fontSize(18)
        .fontColor(this.plan.route.found ? '#0B6E4F' : '#B54708')
        .margin({ top: 12 })
      Text('length_m：' + showNumber(this.plan.route.length_m))
        .fontSize(14)
        .margin({ top: 4 })
      Text('reason：' + showText(this.plan.route.reason))
        .fontSize(14)
        .margin({ top: 4 })
      Text('algorithm：' + this.plan.route.algorithm)
        .fontSize(13)
        .margin({ top: 4 })
      Text('route_plan_status：' + this.plan.route.route_plan_status)
        .fontSize(13)
        .margin({ top: 4 })
      Text(this.plan.route.route_plan_detail)
        .fontSize(12)
        .fontColor('#5C6B66')
      Text('margin_status：' + this.plan.route.margin_status)
        .fontSize(13)
        .margin({ top: 4 })
      Text(this.plan.route.margin_detail)
        .fontSize(12)
        .fontColor('#5C6B66')
      Text('limitations')
        .fontSize(14)
        .margin({ top: 8 })
      ForEach(this.plan.route.limitations, (item: string) => {
        Text(item)
          .fontSize(12)
          .margin({ top: 4 })
      }, (item: string) => item)
      Text('agent.applied：' + String(this.plan.agent.applied) + '，' + this.plan.agent.status)
        .fontSize(12)
        .margin({ top: 8 })
      Button('查看任务')
        .width('100%')
        .margin({ top: 12 })
        .backgroundColor('#355C7D')
        .onClick(() => {
          router.pushUrl({ url: 'pages/TaskDetailPage', params: { taskId: this.taskId } });
        })
      Button('在地图看')
        .width('100%')
        .margin({ top: 8 })
        .backgroundColor('#355C7D')
        .onClick(() => {
          router.pushUrl({
            url: 'pages/MapPage',
            params: { taskId: this.taskId, routeId: this.plan === null ? '' : this.plan.route.route_id }
          });
        })
    }
  }
}
