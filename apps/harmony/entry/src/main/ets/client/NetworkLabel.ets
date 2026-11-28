import { connection } from '@kit.NetworkKit';

/** 使用 ohos.permission.GET_NETWORK_INFO，只读默认网络类型。 */
export async function describeDefaultNetwork(): Promise<string> {
  try {
    const net = await connection.getDefaultNet();
    if (net.netId === 0) {
      return '无默认网络';
    }
    const caps = await connection.getNetCapabilities(net);
    let label = '其他网络';
    const bearers = caps.bearerTypes;
    for (let i = 0; i < bearers.length; i++) {
      if (bearers[i] === connection.NetBearType.BEARER_WIFI) {
        label = 'Wi-Fi';
      } else if (bearers[i] === connection.NetBearType.BEARER_CELLULAR && label !== 'Wi-Fi') {
        label = '蜂窝';
      }
    }
    return label;
  } catch (_err) {
    return '无法读取网络信息';
  }
}
