import { router } from '@kit.ArkUI';
import { AlertStore } from '../client/AlertStore';
import { Repository } from '../client/Repository';
import { showPosition } from '../model/show';
import { Task } from '../model/types';
import { Drone3DBackground } from '../view/Drone3DBackground';
import { TopBar } from '../view/TopBar';

@Entry
@Component
struct TaskListPage {
  @State tasks: Task[] = [];
  @State errorText: string = '';
  @State refreshing: boolean = false;

  aboutToAppear(): void {
    this.reload();
  }

  onPageShow(): void {
    this.reload();
  }

  private reload(): void {
    this.errorText = '';
    Repository.get().listTasks().then((tasks: Task[]) => {
      this.tasks = tasks;
      this.refreshing = false;
    }).catch((err: Object) => {
      this.errorText = AlertStore.recordFromError('任务列表', err);
      this.refreshing = false;
    });
  }

  build() {
    Stack() {
      Drone3DBackground({ scrimColor: '#5207121C' })
      Column() {
        TopBar({ title: '任务列表', showBack: true })
        Refresh({ refreshing: $$this.refreshing }) {
          List({ space: 10 }) {
            if (this.errorText.length > 0) {
              ListItem() {
                Text(this.errorText)
                  .fontSize(13)
                  .fontColor('#B42318')
                  .padding(12)
                  .backgroundColor('#E6FFF0F0')
                  .borderRadius(10)
              }
            }
            if (this.tasks.length === 0 && this.errorText.length === 0) {
              ListItem() {
                Text('还没有任务。')
                  .fontSize(14)
                  .fontColor('#D9ECF5')
                  .padding(12)
              }
            }
            ForEach(this.tasks, (task: Task) => {
              ListItem() {
                Column() {
                  Text(task.task_id)
                    .fontSize(16)
                    .fontWeight(FontWeight.Medium)
                  Text('起点 ' + showPosition(task.origin))
                    .fontSize(12)
                    .fontColor('#3D4A45')
                    .margin({ top: 4 })
                  Text('终点 ' + showPosition(task.destination))
                    .fontSize(12)
                    .fontColor('#3D4A45')
                    .margin({ top: 2 })
                  Text(task.provenance.is_simulated ? '任务单标记：仿真' : '任务单标记：非仿真（航线仍可能是仿真）')
                    .fontSize(12)
                    .fontColor('#7A4E00')
                    .margin({ top: 4 })
                }
                .width('100%')
                .padding(14)
                .backgroundColor('#D9FFFFFF')
                .border({ width: 1, color: '#66FFFFFF' })
                .borderRadius(12)
                .alignItems(HorizontalAlign.Start)
                .onClick(() => {
                  router.pushUrl({
                    url: 'pages/TaskDetailPage',
                    params: { taskId: task.task_id }
                  });
                })
              }
            }, (task: Task) => task.task_id)
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

        Button('新建任务')
          .width('90%')
          .margin({ bottom: 16 })
          .backgroundColor('#0B6E4F')
          .onClick(() => {
            router.pushUrl({ url: 'pages/TaskCreatePage' });
          })
      }
      .width('100%')
      .height('100%')
    }
    .width('100%')
    .height('100%')
  }
}
