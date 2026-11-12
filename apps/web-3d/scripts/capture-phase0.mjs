/**
 * 阶段 0 自检截图。输出到 _shots/（已 gitignore）。
 * 用法：先启动 npm run dev，再执行 node scripts/capture-phase0.mjs [baseUrl]
 */
import { chromium } from 'playwright'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(__dirname, '..')
const outDir = path.join(root, '_shots')
const base = process.argv[2] || 'http://127.0.0.1:5173'

await mkdir(outDir, { recursive: true })

const browser = await chromium.launch({
  headless: true,
  args: [
    '--use-gl=swiftshader',
    '--use-angle=swiftshader',
    '--enable-webgl',
    '--ignore-gpu-blocklist',
    '--disable-gpu-sandbox',
  ],
})

const page = await browser.newPage({
  viewport: { width: 1920, height: 1080 },
  deviceScaleFactor: 1,
})

const notes = []

async function shot(name, extra = '') {
  const file = path.join(outDir, name)
  await page.screenshot({ path: file, fullPage: false })
  notes.push(`${name}${extra ? ` — ${extra}` : ''}`)
  console.log('saved', file)
}

try {
  await page.goto(base + '/', { waitUntil: 'networkidle', timeout: 30_000 })
  await page.waitForSelector('text=阶段 0 占位', { timeout: 15_000 })
  await shot('01-placeholder-home.png', '新工程占位首页')

  const demoUrl = base + '/legacy/demo-baseline.html'
  const demoResp = await page.goto(demoUrl, { waitUntil: 'domcontentloaded', timeout: 30_000 })
  notes.push(`demo HTTP ${demoResp?.status()} ${demoUrl}`)
  await page.waitForSelector('#home', { timeout: 15_000 })
  await page.waitForTimeout(800)
  await shot('02-legacy-home.png', 'demo 存档 · 主页')

  await page.click('#enter-btn')
  await page.waitForFunction(
    () => {
      const home = document.getElementById('home')
      const cons = document.getElementById('console')
      return home && cons && home.style.display === 'none' && !cons.classList.contains('off')
    },
    { timeout: 8_000 },
  )
  await page.waitForTimeout(600)
  await shot('03-legacy-ops.png', 'demo 存档 · 调度任务台')

  await page.click('#nav-sar')
  await page.waitForSelector('#view-sar.on', { timeout: 8_000 })
  // 给 Three.js CDN / WebGL 一点时间；失败则如实记录
  const webglInfo = await page.evaluate(async () => {
    const started = Date.now()
    while (Date.now() - started < 8000) {
      if (window.SAR3D) {
        return { ok: true, reason: 'window.SAR3D 已挂载' }
      }
      await new Promise((r) => setTimeout(r, 200))
    }
    const tag = document.getElementById('tag3d')
    return {
      ok: false,
      reason: tag ? tag.textContent : '超时仍无 SAR3D，且未读到失败提示',
    }
  })
  await page.waitForTimeout(400)
  await shot(
    '04-legacy-sar.png',
    webglInfo.ok
      ? `demo 存档 · 搜救态势（3D: ${webglInfo.reason}）`
      : `demo 存档 · 搜救态势（3D 未就绪: ${webglInfo.reason}）`,
  )
  console.log('WEBGL_STATUS', JSON.stringify(webglInfo, null, 2))
} catch (err) {
  notes.push(`ERROR: ${err instanceof Error ? err.stack || err.message : String(err)}`)
  try {
    await shot('99-error.png', '捕获失败时的页面')
  } catch {
    /* ignore */
  }
  console.error(err)
  process.exitCode = 1
} finally {
  const report = path.join(outDir, 'NOTES.txt')
  const body = [
    `base: ${base}`,
    `time: ${new Date().toISOString()}`,
    ...notes,
    '',
  ].join('\n')
  await import('node:fs/promises').then((fs) => fs.writeFile(report, body, 'utf8'))
  console.log('notes', report)
  console.log(body)
  await browser.close()
}
