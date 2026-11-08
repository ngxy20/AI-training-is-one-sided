import { useEffect } from 'react'
import { useApp } from '../store'
import { DataTable, Empty, JsonView, MetricCards, StatusPill, useFetch } from '../ui'

const TABS = ['属性', '参数', '指标', '标签']

export function RightPanel() {
  const app = useApp()
  const pid = app.activeProject?.id || ''
  const tab = app.tabs.find((t) => t.id === app.activeTabId)
  const stats = useFetch<{ counts: Record<string, number> }>(pid ? `/projects/${pid}/stats` : null, [pid, app.revision])
  const schema = useFetch<Record<string, unknown>>(
    tab?.kind === 'config' && tab.resourceId ? `/configs/${tab.resourceId}/schema` : null, [tab?.resourceId])
  const runData = useFetch<{ metrics_json?: Record<string, unknown>; status?: string }>(
    tab?.kind === 'run' && tab.resourceId ? `/runs/${tab.resourceId}` : null, [tab?.resourceId, app.revision])
  const templates = useFetch<{ items: { template_type: string; name: string }[] }>(
    pid ? `/projects/${pid}/annotation-templates` : null, [pid])

  useEffect(() => { if (!TABS.includes(app.rightTab)) app.patch({ rightTab: '属性' }) }, [app.rightTab]) // eslint-disable-line

  return <aside className="right">
    <div className="panel-head"><span>右侧面板</span><span>{app.activeProject?.name || '—'}</span></div>
    <div className="bottom-tabs" style={{ flex: 'none' }}>
      {TABS.map((name) => <button key={name} className={app.rightTab === name ? 'active' : ''}
        onClick={() => app.patch({ rightTab: name })}>{name}</button>)}
    </div>
    <div style={{ padding: 14, overflow: 'auto', flex: 1 }}>
      {app.rightTab === '属性' && <>
        <div className="section"><h3>当前项目</h3>
          <div className="card"><div className="k">名称</div><div className="v" style={{ fontSize: 15 }}>{app.activeProject?.name || '—'}</div></div>
          <div className="small mono dim" style={{ marginTop: 8, wordBreak: 'break-all' }}>{app.activeProject?.workspace_path}</div>
          <div className="row" style={{ marginTop: 10 }}><StatusPill status={app.activeProject?.status} /><span className="pill info">项目级 SQLite</span></div>
        </div>
        <div className="section"><h3>资源数量</h3><MetricCards metrics={stats.data?.counts} /></div>
        <div className="section"><h3>当前标签</h3>
          {tab ? <JsonView value={{ title: tab.title, kind: tab.kind, resourceId: tab.resourceId, ...(tab.meta || {}) }} /> : <Empty text="未打开标签" />}
        </div>
      </>}
      {app.rightTab === '参数' && <div className="section"><h3>参数 Schema（表单 ↔ YAML 双向同步）</h3>
        {tab?.kind === 'config' ? <>
          <JsonView value={schema.data || {}} />
          <p className="small muted">在编辑器中直接修改 YAML 并保存，表单会依据此 Schema 重新生成。</p>
        </> : <Empty text="打开一个训练配置标签页后可查看参数 Schema。" />}
      </div>}
      {app.rightTab === '指标' && <div className="section"><h3>指标卡</h3>
        {tab?.kind === 'run' ? <><StatusPill status={runData.data?.status} /><MetricCards metrics={runData.data?.metrics_json} /></>
          : <><p className="small muted">项目概览</p><MetricCards metrics={stats.data?.counts} /></>}
        <p className="small muted" style={{ marginTop: 12 }}>指标看板可在命令面板中打开，聚合训练 / 评测 / A/B 指标。</p>
      </div>}
      {app.rightTab === '标签' && <div className="section"><h3>标注模板</h3>
        <DataTable columns={[{ key: 'name', label: '模板' }, { key: 'template_type', label: '类型' }]}
          rows={(templates.data?.items || []) as unknown as Record<string, unknown>[]} empty="暂无模板" />
      </div>}
    </div>
  </aside>
}
