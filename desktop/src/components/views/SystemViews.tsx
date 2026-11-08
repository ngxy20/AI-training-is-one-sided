import { useEffect, useState } from 'react'
import { api, qs } from '../../api'
import { tabForItem } from '../../navigation'
import { useApp } from '../../store'
import type { Tab, TreeItem } from '../../types'
import { DataTable, JsonView, MetricCards, StatusPill, useFetch } from '../../ui'

export function SettingsView() {
  const app = useApp()
  const pid = app.activeProject?.id || ''
  const global = useFetch<Record<string, unknown>>('/settings', [app.revision])
  const project = useFetch<Record<string, unknown>>(pid ? `/projects/${pid}/settings` : null, [pid, app.revision])
  const health = useFetch<Record<string, unknown>>('/health')
  const [globalText, setGlobalText] = useState('')
  const [projectText, setProjectText] = useState('')
  useEffect(() => { if (global.data) setGlobalText(JSON.stringify(global.data, null, 2)) }, [global.data])
  useEffect(() => { if (project.data) setProjectText(JSON.stringify(project.data, null, 2)) }, [project.data])

  const save = async (which: 'global' | 'project') => {
    try {
      const text = which === 'global' ? globalText : projectText
      await api.patch(which === 'global' ? '/settings' : `/projects/${pid}/settings`, JSON.parse(text))
      app.notify('设置已保存', 'success'); app.bump()
    } catch (e) { app.notify((e as Error).message, 'error') }
  }

  return <div className="editor-pad">
    <div className="section"><h3>运行环境</h3><JsonView value={health.data || {}} /></div>
    <div className="section"><h3>全局设置</h3>
      <textarea className="mono" style={{ width: '100%', minHeight: 130 }} value={globalText} onChange={(e) => setGlobalText(e.target.value)} />
      <div className="row" style={{ marginTop: 8 }}><button className="btn sm primary" onClick={() => void save('global')}>保存全局设置</button></div>
    </div>
    <div className="section"><h3>项目设置 · {app.activeProject?.name}</h3>
      <textarea className="mono" style={{ width: '100%', minHeight: 110 }} value={projectText} onChange={(e) => setProjectText(e.target.value)} />
      <div className="row" style={{ marginTop: 8 }}><button className="btn sm primary" onClick={() => void save('project')}>保存项目设置</button></div>
    </div>
    <p className="small dim">本地优先：所有状态默认落在 {String(health.data?.app_home || '')}，不外传。</p>
  </div>
}

interface PluginItem {
  id: string; name: string; version: string; sdk_version: string; enabled: boolean;
  high_risk: boolean; permissions: string[]; problems: string[];
  extension_points: { point: string }[]; path: string
}

export function PluginsView() {
  const app = useApp()
  const pid = app.activeProject?.id || ''
  const result = useFetch<{ items: PluginItem[]; extension_points: string[] }>(
    `/plugins${qs({ pid })}`, [pid, app.revision])

  const toggle = async (plugin: PluginItem) => {
    const enabling = !plugin.enabled
    if (enabling && plugin.high_risk && !window.confirm(
      `插件 ${plugin.name} 申请高风险权限：\n${plugin.permissions.join('、')}\n\n确认启用？`)) return
    try {
      await api.post(`/plugins/${encodeURIComponent(plugin.id)}/enable`,
        { pid, enabled: enabling, confirm: plugin.high_risk })
      app.notify(`${plugin.name} 已${enabling ? '启用' : '停用'}`, 'success'); app.bump()
    } catch (e) { app.notify((e as Error).message, 'error') }
  }

  return <div className="editor-pad">
    <div className="row" style={{ marginBottom: 12 }}><h2 style={{ margin: 0, fontSize: 16 }}>插件管理</h2>
      <span className="pill info">SDK {String(result.data?.items?.[0]?.sdk_version || '0.1')}</span>
      <div style={{ flex: 1 }} />
      <button className="btn sm" onClick={async () => {
        try { const r = await api.post<{ scanned: number }>(`/plugins/scan?pid=${pid}`); app.notify(`发现 ${r.scanned} 个插件`, 'success'); app.bump() }
        catch (e) { app.notify((e as Error).message, 'error') }
      }}>扫描插件</button>
    </div>
    <p className="small muted">MIT 开源 · 插件开放。扩展点：{result.data?.extension_points.join('、')}</p>
    <div className="section"><h3>已发现插件</h3>
      <DataTable columns={[
        { key: 'name', label: '名称' }, { key: 'version', label: '版本' },
        { key: 'extension_points', label: '扩展点', render: (r) => (r.extension_points as { point: string }[]).map((e) => e.point).join(', ') },
        { key: 'permissions', label: '权限', render: (r) => (r.permissions as string[]).join(', ') || '—' },
        { key: 'high_risk', label: '风险', render: (r) => r.high_risk ? <span className="pill bad">高风险</span> : <span className="pill ok">低风险</span> },
        { key: 'problems', label: '兼容性', render: (r) => (r.problems as string[]).length
          ? <span className="pill bad">不兼容</span> : <span className="pill ok">通过</span> },
        { key: 'enabled', label: '启用', render: (r) => <input type="checkbox" checked={Boolean(r.enabled)}
          onClick={(e) => { e.stopPropagation(); void toggle(r as unknown as PluginItem) }} readOnly /> },
      ]} rows={(result.data?.items || []) as unknown as Record<string, unknown>[]} empty="未发现插件" />
    </div>
    <p className="small dim">插件目录：用户插件放 ~/.aixian/plugins，示例插件在仓库 plugins/examples。MVP 进程内加载，V2 支持子进程隔离与签名校验。</p>
  </div>
}

export function LineageView() {
  const app = useApp()
  const pid = app.activeProject?.id || ''
  const graph = useFetch<{ nodes: { id: string; type: string; label: string }[]; edges: { source: string; target: string; label: string }[] }>(
    `/projects/${pid}/lineage`, [pid, app.revision])
  return <div className="editor-pad">
    <h3 style={{ marginTop: 0 }}>资产版本与引用关系图</h3>
    <p className="small muted">数据集版本 → 训练实验 → checkpoint → 评测 → 报告，全部可追溯。</p>
    <div className="cards">
      <div className="card"><div className="k">节点</div><div className="v">{graph.data?.nodes.length || 0}</div></div>
      <div className="card"><div className="k">引用边</div><div className="v">{graph.data?.edges.length || 0}</div></div>
    </div>
    <div className="section"><h3>节点</h3><DataTable columns={[
      { key: 'type', label: '类型' }, { key: 'label', label: '名称/版本' }, { key: 'id', label: 'ID' },
    ]} rows={(graph.data?.nodes || []) as unknown as Record<string, unknown>[]} empty="暂无资产" /></div>
    <div className="section"><h3>引用关系</h3><DataTable columns={[
      { key: 'source', label: '来源' }, { key: 'label', label: '关系' }, { key: 'target', label: '目标' },
    ]} rows={(graph.data?.edges || []) as unknown as Record<string, unknown>[]} empty="暂无引用" /></div>
  </div>
}

export function DashboardView() {
  const app = useApp()
  const pid = app.activeProject?.id || ''
  const metrics = useFetch<{ training: { run_count: number; succeeded: number; registered_models: unknown[] }; latest_accuracy: number }>(
    `/projects/${pid}/metrics`, [pid, app.revision])
  const stats = useFetch<{ counts: Record<string, number> }>(`/projects/${pid}/stats`, [pid, app.revision])
  return <div className="editor-pad">
    <h3 style={{ marginTop: 0 }}>指标看板</h3>
    <MetricCards metrics={{
      runs: metrics.data?.training.run_count ?? 0,
      succeeded: metrics.data?.training.succeeded ?? 0,
      models: metrics.data?.training.registered_models?.length ?? 0,
      accuracy: metrics.data?.latest_accuracy ?? 0,
      ...(stats.data?.counts || {}),
    }} />
    <div className="section"><h3>训练实验指标</h3>
      <DataTable columns={[
        { key: 'name', label: '实验' }, { key: 'status', label: '状态', render: (r) => <StatusPill status={String(r.status)} /> },
        { key: 'metrics', label: '指标', render: (r) => JSON.stringify(r.metrics) },
      ]} rows={(metrics.data?.training as unknown as { runs?: Record<string, unknown>[] })?.runs || []} empty="暂无实验" />
    </div>
  </div>
}

export function AuditView() {
  const app = useApp()
  const pid = app.activeProject?.id || ''
  const events = useFetch<{ items: Record<string, unknown>[] }>(`/audit-events${qs({ pid, size: 300 })}`, [pid, app.revision])
  return <div className="editor-pad"><h3 style={{ marginTop: 0 }}>审计事件</h3>
    <DataTable maxHeight={620} columns={[
      { key: 'at', label: '时间' }, { key: 'actor', label: '操作者' }, { key: 'action', label: '动作' },
      { key: 'entity_type', label: '实体' }, { key: 'entity_id', label: 'ID' },
      { key: 'detail_json', label: '详情', render: (r) => <span className="mono small">{JSON.stringify(r.detail_json).slice(0, 120)}</span> },
    ]} rows={events.data?.items || []} empty="暂无审计事件" />
  </div>
}

export function SearchView({ tab }: { tab: Tab }) {
  const app = useApp()
  const pid = app.activeProject?.id || ''
  const query = String(tab.meta?.q || '')
  const result = useFetch<{ items: TreeItem[] }>(`/projects/${pid}/search${qs({ q: query })}`, [pid, query, app.revision])
  return <div className="editor-pad"><h3 style={{ marginTop: 0 }}>全局搜索 · {query}</h3>
    <DataTable columns={[{ key: 'kind', label: '类型' }, { key: 'name', label: '名称' }, { key: 'uri', label: 'URI' }]}
      rows={(result.data?.items || []) as unknown as Record<string, unknown>[]} empty="没有匹配资源"
      onRowClick={(r) => app.openTab(tabForItem(r as unknown as TreeItem, pid))} />
  </div>
}
