import { useState } from 'react'
import { useApp } from '../store'
import { useFetch } from '../ui'

export function TopBar() {
  const app = useApp()
  const [search, setSearch] = useState('')
  const running = app.jobs.filter((j) => j.status === 'running' || j.status === 'queued').length
  const me = useFetch<{ user: { display_name: string; color: string } }>('/me', [app.revision])

  const doSearch = () => {
    if (!search.trim() || !app.activeProject) return
    app.openTab({ title: `搜索 · ${search}`, kind: 'search', projectId: app.activeProject.id, meta: { q: search } })
  }

  return <header className="topbar">
    <div className="brand"><span className="logo">AI</span><span>AI 训练工作台 <small>v0.1</small></span></div>
    <div className="project-select">
      <select value={app.activeProject?.id || ''} onChange={(e) => e.target.value && void app.switchProject(e.target.value)}>
        {!app.projects.length && <option value="">（无项目）</option>}
        {app.projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select>
    </div>
    <button className="btn ghost" onClick={() => app.patch({ paletteOpen: true })} title="Ctrl+Shift+P">
      ⌘ 命令面板
    </button>
    <div className="command-trigger">
      <input id="global-search" className="grow" placeholder="全局搜索资源…" value={search}
        onChange={(e) => setSearch(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') doSearch() }} />
      <button className="btn sm" onClick={doSearch}>搜索</button>
    </div>
    <div className="spacer" />
    <span className="status-chip" title="本地服务 WebSocket 连接状态">
      <span className={`dot ${app.connected ? 'ok' : 'warn'}`} /> {app.connected ? '服务已连接' : '连接中'}
    </span>
    <span className="status-chip"><span className={`dot ${running ? 'ok' : ''}`} /> 运行中 {running}</span>
    <button className="btn sm" title="打开主题编辑器" onClick={() =>
      app.openTab({ title: '主题', kind: 'theme' })}>◐ {app.themeName}</button>
    <button className="btn sm" onClick={() => app.openTab({ title: '设置', kind: 'settings' })}>设置</button>
    <button className="status-chip" title="点击管理成员与切换身份" style={{ cursor: 'pointer' }}
      onClick={() => app.openTab({ title: '成员与权限', kind: 'members' })}>
      <span className="dot ok" style={{ background: me.data?.user?.color || 'var(--green)' }} />
      {me.data?.user?.display_name || '本地账户'}
    </button>
  </header>
}
