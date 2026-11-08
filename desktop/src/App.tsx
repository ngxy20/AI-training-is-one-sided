import { useEffect } from 'react'
import { BottomPanel } from './components/BottomPanel'
import { CommandPalette } from './components/CommandPalette'
import { DynamicDialog } from './components/DynamicDialog'
import { ResourceTree } from './components/ResourceTree'
import { RightPanel } from './components/RightPanel'
import { TabArea } from './components/TabArea'
import { TopBar } from './components/TopBar'
import { buildCommands } from './commands'
import { useApp } from './store'

export default function App() {
  const app = useApp()

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === 'p') {
        event.preventDefault(); app.patch({ paletteOpen: !app.paletteOpen }); return
      }
      if (event.ctrlKey && event.key.toLowerCase() === 'n') {
        event.preventDefault()
        const command = buildCommands(app.activeProject?.id || '').find((c) => c.id === 'project.create')
        if (command) void app.runCommand(command)
        return
      }
      if (event.ctrlKey && event.key.toLowerCase() === 'w' && app.activeTabId) {
        event.preventDefault(); app.closeTab(app.activeTabId)
      }
      if (event.key === 'Escape') app.patch({ paletteOpen: false, dialog: null })
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [app])

  useEffect(() => {
    const timer = window.setInterval(() => { void app.refreshJobs() }, 6000)
    return () => window.clearInterval(timer)
  }, [app.refreshJobs])

  return <div className="app">
    <TopBar />
    <div className="body"><ResourceTree /><TabArea /><RightPanel /></div>
    <BottomPanel />
    <footer className="statusbar">
      <span>{app.connected ? '● 本地服务已连接' : '○ 正在连接本地服务'}</span>
      <span>项目：{app.activeProject?.name || '—'}</span>
      <span>运行任务：{app.jobs.filter((j) => j.status === 'running' || j.status === 'queued').length}</span>
      <span>标签：{app.tabs.length}</span>
      <div className="spacer" />
      <span>Ctrl+Shift+P 命令面板 · Ctrl+N 新建项目 · Ctrl+W 关闭标签</span>
      <span>AI Training Studio v0.1</span>
    </footer>
    <CommandPalette />
    <DynamicDialog />
    {app.toast && <div className={`toast ${app.toast.tone}`}>{app.toast.text}</div>}
  </div>
}
