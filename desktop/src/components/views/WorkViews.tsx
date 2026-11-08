import { useEffect, useState } from 'react'
import Editor from '@monaco-editor/react'
import { api, fileUrl, reportUrl } from '../../api'
import { useApp } from '../../store'
import type { DialogCommand, Tab } from '../../types'
import { DataTable, Empty, JsonView, MetricCards, StatusPill, useFetch } from '../../ui'

export function ScriptEditor({ tab }: { tab: Tab }) {
  const app = useApp()
  const id = tab.resourceId || ''
  const detail = useFetch<{ name: string; type: string; version: number; content: string; versions: { version: number; name: string }[] }>(
    `/scripts/${id}`, [id, app.revision])
  const [content, setContent] = useState('')
  const [params, setParams] = useState('{}')

  useEffect(() => { if (detail.data) setContent(detail.data.content || '') }, [detail.data?.content, detail.data?.version]) // eslint-disable-line

  const save = async () => {
    try { await api.put(`/scripts/${id}`, { content }); app.notify('脚本已保存，版本快照已生成', 'success'); app.bump() }
    catch (e) { app.notify((e as Error).message, 'error') }
  }
  const run = async () => {
    try {
      await api.post(`/scripts/${id}/run`, { params: JSON.parse(params || '{}') })
      app.notify('收集脚本任务已提交', 'success'); app.refreshJobs(); app.patch({ bottomTab: '日志' })
    } catch (e) { app.notify((e as Error).message, 'error') }
  }

  return <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
    <div className="editor-toolbar">
      <strong>{detail.data?.name || '脚本'}</strong><span className="pill info">v{detail.data?.version}</span>
      <span className="small dim">{detail.data?.type === 'sql' ? 'SQL' : 'Python'}</span>
      <input style={{ width: 200 }} value={params} onChange={(e) => setParams(e.target.value)} placeholder='运行参数 JSON，例如 {"n": 10}' />
      <div style={{ flex: 1 }} />
      <button className="btn sm" onClick={() => void run()}>运行</button>
      <button className="btn sm primary" onClick={() => void save()}>保存</button>
    </div>
    <div className="editor-body">
      <Editor height="100%" language={detail.data?.type === 'sql' ? 'sql' : 'python'} theme="vs-dark"
        value={content} onChange={(v) => setContent(v || '')}
        options={{ minimap: { enabled: false }, fontSize: 13, automaticLayout: true, tabSize: 4 }} />
    </div>
  </div>
}

export function ConfigView({ tab }: { tab: Tab }) {
  const app = useApp()
  const pid = app.activeProject?.id || ''
  const id = tab.resourceId || ''
  const detail = useFetch<{ name: string; version: number; params_json: Record<string, unknown>; params_yaml: string; runner_type: string }>(
    `/configs/${id}`, [id, app.revision])
  const schema = useFetch<{ properties?: Record<string, { type: string; default?: unknown; title?: string }> }>(
    `/configs/${id}/schema`, [id, app.revision])
  const [yaml, setYaml] = useState('')
  useEffect(() => { if (detail.data) setYaml(detail.data.params_yaml || '') }, [detail.data?.params_yaml, detail.data?.version]) // eslint-disable-line

  const save = async () => {
    try { await api.put(`/configs/${id}`, { params_yaml: yaml }); app.notify('参数已保存（配置版本递增）', 'success'); app.bump() }
    catch (e) { app.notify((e as Error).message, 'error') }
  }
  const setFormValue = (key: string, value: unknown) => {
    const next = { ...(detail.data?.params_json || {}), [key]: value }
    setYaml(Object.entries(next).map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join('\n'))
  }

  return <div style={{ display: 'flex', height: '100%', minHeight: 0 }}>
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
      <div className="editor-toolbar">
        <strong>{detail.data?.name || '训练配置'}</strong><span className="pill info">v{detail.data?.version}</span>
        <span className="pill">{detail.data?.runner_type}</span>
        <div style={{ flex: 1 }} />
        <button className="btn sm" onClick={() => app.openDialog({
          id: 'run.fromconfig', title: '提交训练',
          fields: [
            { key: 'name', label: '实验名称', type: 'text', required: true, default: `${detail.data?.name || '实验'} #1` },
            { key: 'version', label: '数据集版本', type: 'select', required: true,
              optionsFrom: { endpoint: `/projects/${pid}/dataset-versions`, label: 'name', value: 'id' } },
          ],
          endpoint: `/projects/${pid}/runs`,
          payload: (v) => ({ name: v.name, config_id: id, dataset_version_ids: [v.version] }),
        })}>提交训练</button>
        <button className="btn sm primary" onClick={() => void save()}>保存</button>
      </div>
      <div className="editor-body"><Editor height="100%" language="yaml" theme="vs-dark" value={yaml}
        onChange={(v) => setYaml(v || '')} options={{ minimap: { enabled: false }, fontSize: 13, automaticLayout: true }} /></div>
    </div>
    <div style={{ width: 250, overflow: 'auto', padding: 12, borderLeft: '1px solid var(--line)', background: 'var(--panel)' }}>
      <h3 style={{ marginTop: 0, fontSize: 12 }}>JSON Schema 表单</h3>
      <p className="small dim">修改表单会同步到左侧 YAML，反之保存后表单按 Schema 重建。</p>
      {Object.entries(schema.data?.properties || {}).map(([key, spec]) => <div className="field" key={key}>
        <label>{spec.title || key}</label>
        <input type={spec.type === 'integer' || spec.type === 'number' ? 'number' : 'text'}
          value={String(detail.data?.params_json?.[key] ?? spec.default ?? '')}
          onChange={(e) => setFormValue(key, spec.type === 'integer' || spec.type === 'number'
            ? Number(e.target.value) : e.target.value)} />
      </div>)}
      {!Object.keys(schema.data?.properties || {}).length && <Empty text="暂无参数 Schema" />}
    </div>
  </div>
}

interface AnnotRecord { id: string; payload_json: Record<string, unknown>; annotation?: { label_json: Record<string, unknown>; status: string } }

export function AnnotationView({ tab }: { tab: Tab }) {
  const app = useApp()
  const id = tab.resourceId || ''
  const task = useFetch<{ name: string; stats_json: Record<string, unknown>; schema: { template_type: string; schema_json: { fields?: { key: string; label: string; type: string; options?: string[]; shortcuts?: string[] }[] } } }>(
    `/annotation-tasks/${id}`, [id, app.revision])
  const records = useFetch<{ items: AnnotRecord[]; total: number }>(`/annotation-tasks/${id}/records?size=200`, [id, app.revision])
  const [index, setIndex] = useState(0)
  const [label, setLabel] = useState<Record<string, unknown>>({})
  const items = records.data?.items || []
  const current = items[index]
  const fields = task.data?.schema?.schema_json?.fields || []

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.target as HTMLElement)?.tagName === 'INPUT') return
      const shortcut = fields.find((f) => f.shortcuts?.includes(event.key))
      if (shortcut?.options?.[shortcut.shortcuts!.indexOf(event.key)]) {
        setLabel((prev) => ({ ...prev, [shortcut.key]: shortcut.options![shortcut.shortcuts!.indexOf(event.key)] }))
      }
      if (event.key === 'ArrowDown') setIndex((i) => Math.min(i + 1, items.length - 1))
      if (event.key === 'ArrowUp') setIndex((i) => Math.max(i - 1, 0))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [fields, items.length]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { setLabel((current?.annotation?.label_json as Record<string, unknown>) || {}) }, [current?.id, current?.annotation?.status]) // eslint-disable-line

  const save = async () => {
    if (!current) return
    try {
      await api.post(`/annotation-tasks/${id}/annotations`, { record_id: current.id, label_json: label })
      app.notify('标注已保存', 'success'); app.bump()
    } catch (e) { app.notify((e as Error).message, 'error') }
  }
  const review = async (decision: 'approve' | 'reject') => {
    if (!current) return
    try {
      await api.post(`/annotation-tasks/${id}/review`, { record_ids: [current.id], decision, reviewer: 'local' })
      app.notify(decision === 'approve' ? '已通过审核' : '已驳回', 'success'); app.bump()
    } catch (e) { app.notify((e as Error).message, 'error') }
  }

  return <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
    <div className="editor-toolbar">
      <strong>{task.data?.name || '标注任务'}</strong>
      <StatusPill status={String(task.data?.stats_json?.approved ? 'approved' : 'open')} />
      <span className="small muted">已标注 {String(task.data?.stats_json?.annotated ?? 0)} / {records.data?.total ?? 0}</span>
      <span className="small muted">Kappa {String(task.data?.stats_json?.cohen_kappa ?? '—')}</span>
      <div style={{ flex: 1 }} />
      <button className="btn sm" onClick={async () => {
        try {
          const r = await api.post<{ path: string; record_count: number }>(`/annotation-tasks/${id}/export`, { only_approved: true })
          window.open(fileUrl(app.activeProject?.id || '', r.path, true), '_blank')
          app.notify(`已导出 ${r.record_count} 条标注`, 'success')
        } catch (e) { app.notify((e as Error).message, 'error') }
      }}>导出结果</button>
      <button className="btn sm" onClick={() => void review('reject')}>驳回</button>
      <button className="btn sm" onClick={() => void review('approve')}>审核通过</button>
      <button className="btn sm primary" onClick={() => void save()}>保存标注</button>
    </div>
    <div className="annot" style={{ flex: 1 }}>
      <div className="annot-col">
        {items.map((item, i) => <div key={item.id} className={`annot-item ${i === index ? 'active' : ''}`}
          onClick={() => setIndex(i)}>
          <div className="small mono">{item.id.slice(0, 8)} · {item.annotation?.status || '未标注'}</div>
          <div className="small dim">{String(item.payload_json?.text ?? JSON.stringify(item.payload_json)).slice(0, 40)}</div>
        </div>)}
        {!items.length && <Empty text="该任务暂无记录" />}
      </div>
      <div className="annot-col">
        <div className="annot-content">{current
          ? JSON.stringify(current.payload_json, null, 2)
          : '选择左侧记录开始标注'}</div>
        <div className="small dim" style={{ padding: '0 22px 20px' }}>↑↓ 切换记录 · 数字键快捷选择标签</div>
      </div>
      <div className="annot-col">
        <div className="annot-actions">
          <h3 style={{ marginTop: 0, fontSize: 12 }}>标签体系 · {task.data?.schema?.template_type}</h3>
          {fields.flatMap((field) => (field.options || []).map((option, i) => <button key={`${field.key}:${option}`}
            className={`opt ${label[field.key] === option ? 'active' : ''}`}
            onClick={() => setLabel((prev) => ({ ...prev, [field.key]: option }))}>
            {field.shortcuts?.[i] && <span className="kbd" style={{ marginRight: 8 }}>{field.shortcuts[i]}</span>}{option}
          </button>))}
          {fields.filter((f) => !f.options).map((field) => <div className="field" key={field.key}>
            <label>{field.label}</label>
            <textarea value={String(label[field.key] ?? '')} onChange={(e) =>
              setLabel((prev) => ({ ...prev, [field.key]: e.target.value }))} />
          </div>)}
          <div className="line" />
          <div className="small dim">当前标签</div><JsonView value={label} />
        </div>
      </div>
    </div>
  </div>
}

export function RunView({ tab }: { tab: Tab }) {
  const app = useApp()
  const id = tab.resourceId || ''
  const run = useFetch<{
    name: string; status: string; code_version: string; runner_type: string;
    dataset_version_ids_json: string[]; metrics_json: Record<string, unknown>;
    artifacts_json: Record<string, unknown>; checkpoints: { id: string; step: number; registered_model_name: string | null }[];
    env_snapshot_json: Record<string, unknown>; job_id: string;
  }>(`/runs/${id}`, [id, app.revision])
  const data = run.data

  return <div className="editor-pad">
    <div className="row" style={{ marginBottom: 12 }}>
      <h2 style={{ margin: 0, fontSize: 16 }}>{data?.name || '训练实验'}</h2>
      <StatusPill status={data?.status} /><span className="pill info">{data?.runner_type}</span>
      <div style={{ flex: 1 }} />
      <button className="btn sm" onClick={() => { app.patch({ bottomTab: '日志' }); app.notify('已切换到日志面板') }}>查看日志</button>
      <button className="btn sm" onClick={async () => {
        try { await api.post(`/runs/${id}/cancel`); app.notify('已请求中断', 'success'); app.bump() }
        catch (e) { app.notify((e as Error).message, 'error') }
      }}>中断</button>
      <button className="btn sm primary" onClick={() => app.openDialog({
        id: 'model.register', title: '登记模型',
        fields: [{ key: 'name', label: '模型名称', type: 'text', required: true, default: 'model-v1' }],
        endpoint: `/runs/${id}/register-model`, payload: (v) => ({ name: v.name }),
      })}>登记模型</button>
    </div>
    <MetricCards metrics={data?.metrics_json} />
    <div className="section"><h3>可复现实验卡片</h3>
      <DataTable columns={[{ key: 'k', label: '项' }, { key: 'v', label: '值' }]} rows={[
        { k: 'code_version', v: data?.code_version },
        { k: 'dataset_versions', v: data?.dataset_version_ids_json?.join(', ') },
        { k: 'runner', v: data?.runner_type },
        { k: 'job_id', v: data?.job_id },
      ] as unknown as Record<string, unknown>[]} />
    </div>
    <div className="section"><h3>Checkpoint</h3>
      <DataTable columns={[
        { key: 'step', label: 'step' }, { key: 'id', label: 'ID' },
        { key: 'registered_model_name', label: '登记名称' },
      ]} rows={(data?.checkpoints || []) as unknown as Record<string, unknown>[]} empty="暂无 checkpoint" />
    </div>
    <div className="section"><h3>环境快照</h3><JsonView value={data?.env_snapshot_json || {}} /></div>
  </div>
}

export function EvalSuiteView({ tab }: { tab: Tab }) {
  const app = useApp()
  const id = tab.resourceId || ''
  const suite = useFetch<{ name: string; type: string; version: number; cases_json: Record<string, unknown>[]; runs: { id: string; status: string; metrics_json: Record<string, unknown> }[] }>(
    `/eval-suites/${id}`, [id, app.revision])
  const cases = suite.data?.cases_json || []
  return <div className="editor-pad">
    <div className="row" style={{ marginBottom: 12 }}>
      <h2 style={{ margin: 0, fontSize: 16 }}>{suite.data?.name}</h2>
      <span className="pill info">{suite.data?.type} · v{suite.data?.version}</span>
      <div style={{ flex: 1 }} />
      <button className="btn sm primary" onClick={() => app.openDialog({
        id: 'eval.fromsuite', title: '运行评测套件',
        fields: [
          { key: 'model_ref_json', label: '模型引用 (JSON)', type: 'json', default: { type: 'inline', field: 'output' }, required: true },
          { key: 'scorer_json', label: '评分器 (JSON)', type: 'json', default: { type: 'exact_match' }, required: true },
        ],
        endpoint: `/eval-suites/${id}/runs`,
        payload: (v) => ({ model_ref_json: v.model_ref_json, scorer_json: v.scorer_json }),
      })}>运行评测</button>
    </div>
    <div className="section"><h3>测试用例（{cases.length}）</h3>
      <DataTable columns={cases.length ? Object.keys(cases[0]).map((k) => ({ key: k, label: k })) : [{ key: 'id', label: 'id' }]}
        rows={cases} empty="该套件暂无用例" />
    </div>
    <div className="section"><h3>评测运行</h3>
      <DataTable columns={[
        { key: 'id', label: 'ID' },
        { key: 'status', label: '状态', render: (r) => <StatusPill status={String(r.status)} /> },
        { key: 'metrics_json', label: '指标', render: (r) => JSON.stringify(r.metrics_json) },
      ]} rows={(suite.data?.runs || []) as unknown as Record<string, unknown>[]} empty="尚未运行"
        onRowClick={(r) => app.openTab({ title: `评测 · ${String(r.id).slice(0, 6)}`, kind: 'evalrun', resourceId: String(r.id) })} />
    </div>
  </div>
}

export function EvalRunView({ tab }: { tab: Tab }) {
  const app = useApp()
  const id = tab.resourceId || ''
  const run = useFetch<{ status: string; metrics_json: Record<string, unknown>; results_json: Record<string, unknown>[]; report_id: string }>(
    `/eval-runs/${id}`, [id, app.revision])
  const reportId = run.data?.report_id
  return <div className="editor-pad">
    <div className="row" style={{ marginBottom: 12 }}><h2 style={{ margin: 0, fontSize: 16 }}>评测运行</h2>
      <StatusPill status={run.data?.status} /><div style={{ flex: 1 }} />
      {reportId && <button className="btn sm primary" onClick={() => app.openTab({
        title: '评测报告', kind: 'report', resourceId: reportId })}>打开报告</button>}
    </div>
    <MetricCards metrics={run.data?.metrics_json} />
    <div className="section"><h3>逐用例结果</h3>
      <DataTable maxHeight={520} columns={[
        { key: 'case_id', label: '用例' }, { key: 'category', label: '类别' },
        { key: 'output', label: '输出' },
        { key: 'score', label: '得分', render: (r) => JSON.stringify(r.score) },
      ]} rows={run.data?.results_json || []} empty="暂无结果" />
    </div>
  </div>
}

export function ReportView({ tab }: { tab: Tab }) {
  const app = useApp()
  const id = tab.resourceId || ''
  const report = useFetch<{ name: string; type: string; linked_entities_json: { type: string; id: string }[]; summary_json: Record<string, unknown> }>(
    `/reports/${id}`, [id, app.revision])
  return <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
    <div className="editor-toolbar">
      <strong>{report.data?.name || '报告'}</strong><span className="pill info">{report.data?.type}</span>
      <div style={{ flex: 1 }} />
      {(['html', 'pdf', 'json', 'md'] as const).map((format) => <a key={format} className="btn sm"
        href={reportUrl(id, format, true)} target="_blank" rel="noreferrer">导出 {format.toUpperCase()}</a>)}
      <button className="btn sm" onClick={async () => {
        try { await api.post(`/reports/${id}/regenerate`); app.bump(); app.notify('报告已重新生成', 'success') }
        catch (e) { app.notify((e as Error).message, 'error') }
      }}>重新生成</button>
    </div>
    <div className="iframe-wrap"><iframe className="report-frame" title="报告预览" src={reportUrl(id, 'html')} /></div>
  </div>
}
