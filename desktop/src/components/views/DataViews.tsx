import { useEffect, useMemo, useState } from 'react'
import Editor from '@monaco-editor/react'
import { api, fileUrl, qs } from '../../api'
import { buildCommands } from '../../commands'
import { useApp } from '../../store'
import type { DialogCommand, Tab } from '../../types'
import { DataTable, Empty, JsonView, StatusPill, useFetch } from '../../ui'

export function WelcomeView() {
  const app = useApp()
  const pid = app.activeProject?.id || ''
  const tiles = [
    { id: 'datasource.create', title: '连接现有数据库', text: 'SQLite / PostgreSQL / MySQL，浏览 Schema、执行 SQL、导出数据集' },
    { id: 'dataset.create', title: '数据集与版本', text: '不可变版本 + manifest + 变更说明，支持训练格式转换' },
    { id: 'pipeline.create', title: '清洗 Pipeline', text: '节点化规则与自定义 Python 算子，可复跑并生成新版本' },
    { id: 'annotationtask.create', title: '文本标注工作台', text: '分类 / NER / QA / 偏好排序，审核与 Cohen\'s Kappa' },
    { id: 'run.create', title: '提交训练实验', text: '本地 / SSH / Docker Runner，参数、代码、数据版本全关联' },
    { id: 'suite.create', title: '评测与报告', text: 'A/B、能力边界、准确性测试，HTML/PDF/JSON/MD 报告' },
  ]
  return <div className="welcome">
    <h1>AI 训练工作台</h1>
    <p className="muted">本地优先 · 项目制 · IDE 式 · LLM 文本生成训练全生命周期管理</p>
    <p className="small dim">当前项目：{app.activeProject?.name || '—'} · 工作区：{app.activeProject?.workspace_path}</p>
    <div className="line" />
    <div className="row"><button className="btn primary" onClick={() => app.patch({ paletteOpen: true })}>打开命令面板 (Ctrl+Shift+P)</button>
      <button className="btn" onClick={() => app.openTab({ title: '指标看板', kind: 'dashboard' })}>查看指标看板</button></div>
    <div className="grid">
      {tiles.map((tile) => <div className="tile" key={tile.id} onClick={() => {
        const cmd = buildCommands(pid).find((c) => c.id === tile.id)
        if (cmd) void app.runCommand(cmd)
      }}><h4>{tile.title}</h4><p>{tile.text}</p></div>)}
    </div>
    <p className="small dim" style={{ marginTop: 24 }}>MIT 开源 · 插件开放（Python 后端扩展点 SDK v0.1） · 断网可用</p>
  </div>
}

interface QueryResult { columns: string[]; rows: Record<string, unknown>[]; row_count: number; truncated: boolean }

export function SqlEditor({ tab }: { tab: Tab }) {
  const app = useApp()
  const id = tab.resourceId || ''
  const source = useFetch<{ name: string; type: string; status: string }>(`/datasources/${id}`, [id])
  const schema = useFetch<{ tables: { name: string; columns: { name: string; type: string }[] }[] }>(
    `/datasources/${id}/schema`, [id])
  const [sql, setSql] = useState('SELECT * FROM ')
  const [result, setResult] = useState<QueryResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [showSchema, setShowSchema] = useState(true)

  const run = async () => {
    setBusy(true)
    try { setResult(await api.post<QueryResult>(`/datasources/${id}/query`, { sql })) }
    catch (e) { app.notify((e as Error).message, 'error') }
    finally { setBusy(false) }
  }

  const importDialog: DialogCommand = {
    id: 'sql.import', title: 'SQL 结果导入数据集版本',
    fields: [
      { key: 'dataset_name', label: '数据集名称', type: 'text', required: true, default: `${source.data?.name || 'SQL'} 结果` },
      { key: 'changelog', label: '变更说明', type: 'text' },
    ],
    endpoint: `/datasources/${id}/import`,
    payload: (v) => ({ sql, dataset_name: v.dataset_name, changelog: v.changelog }),
  }

  return <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
    <div className="editor-toolbar">
      <strong>{source.data?.name || '数据源'}</strong><StatusPill status={source.data?.status} />
      <button className="btn sm" onClick={() => setShowSchema((s) => !s)}>{showSchema ? '隐藏' : '显示'} Schema</button>
      <button className="btn sm" onClick={async () => {
        try { await api.post(`/datasources/${id}/test`); app.notify('连接正常', 'success'); app.refreshTree() }
        catch (e) { app.notify((e as Error).message, 'error') }
      }}>测试连接</button>
      <div style={{ flex: 1 }} />
      <button className="btn sm" onClick={() => app.openDialog(importDialog)} disabled={!result?.rows.length}>导入为数据集</button>
      <button className="btn sm primary" onClick={() => void run()} disabled={busy}>{busy ? '执行中…' : '运行 SQL'}</button>
    </div>
    <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
      {showSchema && <div style={{ width: 220, overflow: 'auto', borderRight: '1px solid var(--line)', background: 'var(--panel)' }}>
        {(schema.data?.tables || []).map((table) => <details key={table.name} open>
          <summary className="tree-group" style={{ padding: '7px 10px', cursor: 'pointer' }}>{table.name}</summary>
          {table.columns.map((col) => <div key={col.name} className="small mono" style={{ padding: '3px 18px', color: 'var(--muted)' }}>
            {col.name} <span className="dim">{col.type}</span></div>)}
        </details>)}
        {!schema.data?.tables?.length && <Empty text="未读取到表" />}
      </div>}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <div style={{ height: '45%', minHeight: 160 }}><Editor height="100%" language="sql" theme="vs-dark" value={sql}
          onChange={(v) => setSql(v || '')} options={{ minimap: { enabled: false }, fontSize: 13, automaticLayout: true }} /></div>
        <div style={{ flex: 1, overflow: 'auto', padding: 10, borderTop: '1px solid var(--line)' }}>
          {result ? <>
            <div className="row small muted" style={{ marginBottom: 8 }}>
              <span>{result.row_count} 行</span>{result.truncated && <span className="pill warn">结果已截断</span>}
            </div>
            <DataTable columns={result.columns.map((c) => ({ key: c, label: c }))} rows={result.rows} />
          </> : <Empty text="运行 SQL 后在此预览结果（只读）" />}
        </div>
      </div>
    </div>
  </div>
}

interface Version { id: string; version: number; record_count: number; changelog: string; content_hash: string; stats_json: Record<string, unknown> }

export function DatasetView({ tab }: { tab: Tab }) {
  const app = useApp()
  const pid = app.activeProject?.id || ''
  const id = tab.resourceId || ''
  const detail = useFetch<{ name: string; versions: Version[]; schema_json: Record<string, unknown> }>(
    `/datasets/${id}`, [id, app.revision])
  const rows = detail.data?.versions || []

  return <div className="editor-pad">
    <div className="row" style={{ marginBottom: 12 }}>
      <h2 style={{ margin: 0, fontSize: 16 }}>{detail.data?.name || '数据集'}</h2>
      <span className="pill info">{rows.length} 个不可变版本</span>
      <div style={{ flex: 1 }} />
      <button className="btn sm" onClick={() => {
        const cmd = buildCommands(pid).find((c) => c.id === 'dataset.export')
        if (cmd?.dialog) app.openDialog(cmd.dialog)
      }}>导出训练格式</button>
      <button className="btn sm primary" onClick={() => {
        const cmd = buildCommands(pid).find((c) => c.id === 'dataset.import')
        if (cmd?.dialog) app.openDialog({ ...cmd.dialog,
          fields: cmd.dialog.fields.filter((f) => f.key !== 'dataset_id'), endpoint: `/datasets/${id}/versions` })
      }}>新建版本</button>
    </div>
    <div className="section"><h3>版本清单</h3>
      <DataTable columns={[
        { key: 'version', label: '版本', render: (r) => `v${r.version}` },
        { key: 'record_count', label: '记录数' },
        { key: 'changelog', label: '变更说明' },
        { key: 'content_hash', label: '内容指纹', render: (r) => String(r.content_hash || '').slice(0, 12) },
        { key: 'id', label: '操作', render: (r) => <button className="btn sm" onClick={() =>
          app.openTab({ title: `记录 · v${r.version}`, kind: 'records', resourceId: String(r.id), projectId: pid })}>预览记录</button> },
      ]} rows={rows as unknown as Record<string, unknown>[]} empty="尚无版本，点击「新建版本」导入数据" />
    </div>
    <div className="section"><h3>Schema（自动推断）</h3><JsonView value={detail.data?.schema_json || {}} /></div>
  </div>
}

export function RecordsView({ tab }: { tab: Tab }) {
  const app = useApp()
  const id = tab.resourceId || ''
  const [page, setPage] = useState(1)
  const [split, setSplit] = useState('')
  const [search, setSearch] = useState('')
  const [exported, setExported] = useState('')
  const result = useFetch<{ items: { id: string; split: string; payload_json: Record<string, unknown>; label_json: Record<string, unknown> }[]; total: number }>(
    `/dataset-versions/${id}/records${qs({ page, size: 50, split, search })}`, [id, page, split, search])

  const doExport = async (format: string) => {
    try {
      const r = await api.post<{ path: string; record_count: number }>(`/dataset-versions/${id}/export`, { format })
      setExported(r.path); app.notify(`已导出 ${r.record_count} 条（${format}）`, 'success')
    } catch (e) { app.notify((e as Error).message, 'error') }
  }

  return <div className="editor-pad">
    <div className="row" style={{ marginBottom: 12 }}>
      <input placeholder="搜索记录内容…" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1) }} style={{ width: 240 }} />
      <select value={split} onChange={(e) => { setSplit(e.target.value); setPage(1) }}>
        <option value="">全部 split</option><option value="train">train</option>
        <option value="val">val</option><option value="test">test</option>
      </select>
      <span className="small muted">共 {result.data?.total ?? 0} 条</span>
      <div style={{ flex: 1 }} />
      {(['alpaca', 'sharegpt', 'jsonl', 'csv'] as const).map((format) =>
        <button key={format} className="btn sm" onClick={() => void doExport(format)}>导出 {format}</button>)}
    </div>
    {exported && <div className="small" style={{ marginBottom: 10 }}>
      产物：<a href={fileUrl(app.activeProject?.id || '', exported, true)} className="mono">{exported}</a></div>}
    <DataTable maxHeight={560} columns={[
      { key: 'id', label: 'ID', render: (r) => String(r.id).slice(0, 8) },
      { key: 'split', label: 'split' },
      { key: 'payload_json', label: '内容', render: (r) => <span className="mono">{JSON.stringify(r.payload_json)}</span> },
      { key: 'label_json', label: '标签', render: (r) => <span className="mono">{JSON.stringify(r.label_json)}</span> },
    ]} rows={(result.data?.items || []) as unknown as Record<string, unknown>[]} empty="暂无记录" />
    <div className="pager">
      <button className="btn sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>上一页</button>
      <span>第 {page} 页</span>
      <button className="btn sm" disabled={(result.data?.total || 0) <= page * 50} onClick={() => setPage((p) => p + 1)}>下一页</button>
    </div>
  </div>
}

export function PipelineView({ tab }: { tab: Tab }) {
  const app = useApp()
  const pid = app.activeProject?.id || ''
  const id = tab.resourceId || ''
  const detail = useFetch<{ name: string; version: number; nodes_json: unknown[]; operators?: { op: string; label: string; source: string }[] }>(
    `/pipelines/${id}`, [id, app.revision])
  const runs = useFetch<{ stats_json: { input: number; output: number }; output_version_id: string; status: string }[]>(
    `/pipelines/${id}/runs`, [id, app.revision])
  const [nodes, setNodes] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (detail.data) setNodes(JSON.stringify(detail.data.nodes_json, null, 2))
  }, [detail.data?.name, detail.data?.version, app.revision]) // eslint-disable-line react-hooks/exhaustive-deps

  const text = nodes || (detail.data ? JSON.stringify(detail.data.nodes_json, null, 2) : '[]')

  const save = async () => {
    try { await api.put(`/pipelines/${id}`, { nodes_json: JSON.parse(text) }); app.notify('Pipeline 已保存（版本递增）', 'success'); app.bump() }
    catch (e) { setError((e as Error).message) }
  }

  return <div className="editor-pad">
    <div className="row" style={{ marginBottom: 12 }}>
      <strong>{detail.data?.name}</strong><span className="pill info">v{detail.data?.version}</span>
      <div style={{ flex: 1 }} />
      <button className="btn sm" onClick={() => app.openDialog({
        id: 'pipeline.run', title: `运行 ${detail.data?.name || 'Pipeline'}`,
        fields: [{ key: 'version', label: '源数据集版本', type: 'select', required: true,
          optionsFrom: { endpoint: `/projects/${pid}/dataset-versions`, label: 'name', value: 'id' } }],
        endpoint: `/pipelines/${id}/run`, payload: (v) => ({ source_version_id: v.version }),
      })}>运行</button>
      <button className="btn sm primary" onClick={() => void save()}>保存</button>
    </div>
    <div className="section"><h3>节点配置（JSON）</h3>
      <textarea className="mono" style={{ width: '100%', minHeight: 180 }} value={text}
        onChange={(e) => { setNodes(e.target.value); setError('') }} />
      {error && <div className="small" style={{ color: 'var(--red)' }}>{error}</div>}
      <p className="small muted">可用算子：{(detail.data?.operators || []).map((o) => o.op).join('、') || '在右侧面板查看'}</p>
    </div>
    <div className="section"><h3>执行历史</h3>
      <DataTable columns={[
        { key: 'status', label: '状态', render: (r) => <StatusPill status={String(r.status)} /> },
        { key: 'stats_json', label: '输入 → 输出', render: (r) => {
          const s = r.stats_json as { input?: number; output?: number }
          return `${s?.input ?? 0} → ${s?.output ?? 0}`
        } },
        { key: 'output_version_id', label: '产物版本' },
      ]} rows={(runs.data || []) as unknown as Record<string, unknown>[]} empty="尚未运行" />
    </div>
  </div>
}

export function JsonResourceView({ tab }: { tab: Tab }) {
  const endpoint = (tab.meta?.endpoint as string) || null
  const result = useFetch<unknown>(endpoint, [tab.resourceId])
  return <div className="editor-pad"><h3 style={{ marginTop: 0 }}>{tab.title}</h3>
    <JsonView value={result.data || tab.meta?.item || tab.meta || {}} /></div>
}
