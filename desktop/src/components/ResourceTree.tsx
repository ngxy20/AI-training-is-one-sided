import { useEffect, useState } from 'react'
import { api } from '../api'
import { buildCommands } from '../commands'
import { GROUP_ORDER, tabForItem } from '../navigation'
import { useApp } from '../store'
import type { DialogCommand, TreeItem } from '../types'

interface MenuState { x: number; y: number; item: TreeItem }

export function ResourceTree() {
  const app = useApp()
  const [menu, setMenu] = useState<MenuState | null>(null)
  const pid = app.activeProject?.id || ''
  const rank = (key: string) => {
    const index = GROUP_ORDER.indexOf(key)
    return index < 0 ? 999 : index
  }
  const groups = [...app.tree].sort((a, b) => rank(a.key) - rank(b.key))

  useEffect(() => {
    const close = () => setMenu(null)
    window.addEventListener('click', close)
    return () => window.removeEventListener('click', close)
  }, [])

  const command = (id: string) => buildCommands(pid).find((c) => c.id === id)

  const open = (item: TreeItem) => app.openTab(tabForItem(item, pid))

  const runResource = async (item: TreeItem) => {
    try {
      if (item.kind === 'script') {
        await api.post(`/scripts/${item.id}/run`, {})
        app.notify('脚本任务已提交', 'success'); app.refreshJobs()
      } else if (item.kind === 'pipeline') {
        const dialog: DialogCommand = {
          id: 'pipeline.run', title: `运行清洗 Pipeline · ${item.name}`,
          fields: [{ key: 'version', label: '源数据集版本', type: 'select', required: true,
            optionsFrom: { endpoint: `/projects/${pid}/dataset-versions`, label: 'name', value: 'id' } }],
          endpoint: `/pipelines/${item.id}/run`,
          payload: (v) => ({ source_version_id: v.version }),
        }
        app.openDialog(dialog)
      } else if (item.kind === 'eval_suite') {
        const cmd = command('eval.run')
        if (cmd?.dialog) app.openDialog({
          ...cmd.dialog,
          fields: cmd.dialog.fields.filter((field) => field.key !== 'suite_id'),
          endpoint: `/eval-suites/${item.id}/runs`,
        })
      } else app.notify('该资源类型请在标签页内操作', 'info')
    } catch (e) { app.notify((e as Error).message, 'error') }
  }

  const exportResource = (item: TreeItem) => {
    const cmd = command('dataset.export')
    if (item.kind === 'dataset' && cmd?.dialog) app.openDialog(cmd.dialog)
    else app.notify('请在数据集版本标签页内导出', 'info')
  }

  return <aside className="side">
    <div className="panel-head"><span>资源树 · {app.activeProject?.name || '未打开项目'}</span>
      <span className="actions">
        <button className="icon-btn" title="刷新" onClick={() => app.refreshTree()}>⟳</button>
        <button className="icon-btn" title="新建项目" onClick={() => {
          const cmd = buildCommands(pid).find((c) => c.id === 'project.create')
          if (cmd) void app.runCommand(cmd)
        }}>＋</button>
      </span>
    </div>
    <div className="tree-scroll">
      {!app.activeProject && <div className="tree-empty">尚未创建项目。<br />点击右上角 ＋ 新建项目。</div>}
      {groups.map((group) => <details className="tree-group" key={group.key} open={group.items.length > 0}>
        <summary><span className="caret">▶</span>{group.label}<span className="count">{group.count}</span></summary>
        {group.items.length === 0 && <div className="tree-empty small" style={{ padding: '4px 12px 8px 26px' }}>（空）</div>}
        {group.items.map((item) => <div key={item.id} className="tree-item" onDoubleClick={() => open(item)}
          onContextMenu={(e) => { e.preventDefault(); setMenu({ x: e.clientX, y: e.clientY, item }) }}
          title={`${item.name}\n${item.uri}`}>
          <span className="bullet" /><span className="name">{item.name}</span>
          {item.status && <span className="tag">{item.status}</span>}
          {item.version ? <span className="tag">v{item.version}</span> : null}
        </div>)}
      </details>)}
    </div>
    {menu && <div className="context-menu" style={{ left: menu.x, top: menu.y }}>
      <button onClick={() => { open(menu.item); setMenu(null) }}>打开到标签页</button>
      <button onClick={() => { void runResource(menu.item); setMenu(null) }}>运行</button>
      <button onClick={() => { exportResource(menu.item); setMenu(null) }}>导出</button>
      <button onClick={() => { open(menu.item); setMenu(null) }}>查看版本</button>
      <button onClick={() => { void navigator.clipboard?.writeText(menu.item.uri); app.notify('URI 已复制', 'success'); setMenu(null) }}>复制 URI</button>
    </div>}
  </aside>
}
