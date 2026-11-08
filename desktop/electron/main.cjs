/* Electron 主进程：拉起 Python FastAPI Sidecar，再加载本地前端（断网可用）。 */
const { app, BrowserWindow, dialog, ipcMain, shell } = require('electron')
const { spawn } = require('child_process')
const fs = require('fs')
const http = require('http')
const path = require('path')

// dev:      desktop/electron/main.cjs  -> repo root / sidecar + desktop/dist
// packaged: resources/app(.asar)/electron/main.cjs -> resources/sidecar + resources/web
const APP_DIR = path.resolve(__dirname, '..')
const RESOURCE_ROOT = path.resolve(APP_DIR, '..')
const PACKAGED = fs.existsSync(path.join(RESOURCE_ROOT, 'sidecar')) &&
  fs.existsSync(path.join(RESOURCE_ROOT, 'web'))
const ROOT = PACKAGED ? RESOURCE_ROOT : path.resolve(APP_DIR, '..')
const SIDECAR_DIR = path.join(ROOT, 'sidecar')
const SIDECAR_EXE = path.join(SIDECAR_DIR, 'aixian-sidecar.exe')
const WEB_DIST = PACKAGED ? path.join(ROOT, 'web') : path.join(APP_DIR, 'dist')
const PORT = Number(process.env.AIXIAN_PORT || 8756)
const DEV = process.env.AIXIAN_DEV === '1'

let sidecar = null
let mainWindow = null

function startSidecar() {
  if (process.env.AIXIAN_SIDECAR_EXTERNAL === '1') return
  const env = {
    ...process.env,
    AIXIAN_PORT: String(PORT),
    AIXIAN_WEB_DIST: WEB_DIST,
    AIXIAN_BUNDLED_PLUGINS: path.join(ROOT, 'plugins', 'examples'),
    PYTHONUTF8: '1',
  }
  const stdio = ['ignore', 'pipe', 'pipe']
  if (fs.existsSync(SIDECAR_EXE)) {
    // Fully standalone build: the Python sidecar has been frozen into an exe.
    sidecar = spawn(SIDECAR_EXE, ['--port', String(PORT)],
      { cwd: ROOT, env, stdio, windowsHide: true })
  } else {
    const python = process.env.AIXIAN_PYTHON || (process.platform === 'win32' ? 'python' : 'python3')
    sidecar = spawn(python, ['-m', 'aixian', '--port', String(PORT)], {
      cwd: SIDECAR_DIR,
      env: {
        ...env,
        PYTHONPATH: SIDECAR_DIR + (process.env.PYTHONPATH ? path.delimiter + process.env.PYTHONPATH : ''),
      },
      stdio,
      windowsHide: true,
    })
  }
  sidecar.stdout.on('data', (chunk) => process.stdout.write('[sidecar] ' + chunk))
  sidecar.stderr.on('data', (chunk) => process.stderr.write('[sidecar] ' + chunk))
  sidecar.on('error', (error) => console.error('[sidecar] spawn error:', error.message))
  sidecar.on('exit', (code) => console.log('[sidecar] exited', code))
}

function waitHealthy(timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs
  return new Promise((resolve) => {
    const poll = () => {
      const req = http.get(`http://127.0.0.1:${PORT}/api/v1/health`, (res) => {
        res.resume()
        resolve(res.statusCode === 200)
      })
      req.on('error', () => {
        if (Date.now() > deadline) resolve(false)
        else setTimeout(poll, 300)
      })
      req.setTimeout(1000, () => req.destroy())
    }
    poll()
  })
}

ipcMain.handle('dialog:openPath', async (_event, options = {}) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: options.folder ? ['openDirectory'] : ['openFile'],
    filters: options.folder ? [] : [{ name: '数据文件', extensions: ['jsonl', 'json', 'csv', 'parquet', 'txt', 'md'] }],
  })
  return result.canceled ? null : result.filePaths[0]
})

ipcMain.handle('app:info', () => ({ platform: process.platform, version: app.getVersion(), port: PORT, dev: DEV }))
ipcMain.handle('shell:openExternal', (_event, url) => shell.openExternal(url))

async function bootstrap() {
  startSidecar()
  const healthy = await waitHealthy()
  if (!healthy) {
    dialog.showErrorBox('本地服务未就绪',
      `无法连接 http://127.0.0.1:${PORT}/api/v1/health\n\n` +
      `本版本未内置 Python 运行时，请在 Windows 上安装 Python 3.10+ 后重试，\n` +
      `或设置环境变量 AIXIAN_PYTHON 指向 python.exe。\n` +
      `依赖安装：pip install -r sidecar/requirements.txt`)
  }
  mainWindow = new BrowserWindow({
    width: 1480,
    height: 920,
    minWidth: 1080,
    minHeight: 680,
    title: 'AI 训练工作台 · AI Training Studio',
    backgroundColor: '#0d1117',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })
  mainWindow.loadURL(DEV ? 'http://127.0.0.1:5173' : `http://127.0.0.1:${PORT}/`)
  mainWindow.on('closed', () => { mainWindow = null })
}

app.whenReady().then(bootstrap)
app.on('window-all-closed', () => {
  if (sidecar) sidecar.kill()
  app.quit()
})
app.on('before-quit', () => { if (sidecar) sidecar.kill() })
