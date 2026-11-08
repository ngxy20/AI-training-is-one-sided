import { useEffect, useState } from 'react'
import { api } from '../../api'
import { useApp } from '../../store'
import type { Tab } from '../../types'
import { DataTable, JsonView, StatusPill, useFetch } from '../../ui'

interface AdapterField {
  key: string; label: string; default?: unknown; required?: boolean; type?: string
}
interface AdapterDef {
  type: string; label: string; description: string; offline: boolean; fields: AdapterField[]
}
interface ModelRow {
  id: string; name: string; kind: string; adapter_type: string
  ref_json: Record<string, unknown>; description: string
  status: string; version: number; path_status: string
  base_model_id: string | null; source_run_id: string | null
  tags_json: string[]; last_tested_at: string | null
  usage: { eval_runs: number; ab_tests: number; derived_models: number }
}

const KIND_LABELS: Record<string, string> = {
  base: '基座模型', finetuned: '微调产物', adapter: 'Adapter',
  endpoint: '推理端点', external: '外部模型',
}

function refSummary(ref: Record<string, unknown> | undefined) {
  if (!ref) return '—'
  const value = ref.model || ref.url || ref.base_url || ref.command || ref.dataset_version_id || ''
  return `${ref.type || '?'} · ${String(Array.isArray(value) ? value[0] : value).slice(0, 52)}`
}

export function ModelRegistryView() {
  const app = useApp()
  const pid = app.activeProject?.id || ''
  const list = useFetch<{ items: ModelRow[]; total: number }>(
    pid ? `/projects/${pid}/models` : null, [pid, app.revision])
  const kinds = useFetch<{ kinds: string[]; adapters: AdapterDef[] }>(
    pid ? `/projects/${pid}/model-kinds` : null, [pid])

  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState<ModelRow | null>(null)
  const [name, setName] = useState('')
  const [kind, setKind] = useState('base')
  const [adapterType, setAdapterType] = useState('transformers')
  const [fields, setFields] = useState<Record<string, unknown>>({})
  const [description, setDescription] = useState('')
  const [tags, setTags] = useState('')
  const [baseId, setBaseId] = useState('')
  const [advanced, setAdvanced] = useState(false)
  const [rawJson, setRawJson] = useState('')
  const [busy, setBusy] = useState(false)
  const [testId, setTestId] = useState('')
  const [testPrompt, setTestPrompt] = useState('你好，请用一句话介绍自己。')
  const [testOutput, setTestOutput] = useState('')

  const defs = kinds.data?.adapters || []
  const current = defs.find((d) => d.type === adapterType)

  const initFields = (type: string, preset?: Record<string, unknown>) => {
    const def = defs.find((d) => d.type === type)
    const initial: Record<string, unknown> = {}
    def?.fields.forEach((f) => {
      if (f.default !== undefined) initial[f.key] = f.default
    })
    if (preset) Object.entries(preset).forEach(([k, v]) => { if (k !== 'type') initial[k] = v })
    setFields(initial)
  }

  useEffect(() => { if (defs.length && !showForm) initFields('transformers') }, [defs.length]) // eslint-disable-line

  const openCreate = () => {
    setEditing(null); setName(''); setKind('base'); setDescription(''); setTags(''); setBaseId('')
    setAdapterType('transformers'); initFields('transformers'); setAdvanced(false); setRawJson('')
    setShowForm(true)
  }

  const openEdit = (row: ModelRow) => {
    setEditing(row); setName(row.name); setKind(row.kind); setDescription(row.description)
    setTags((row.tags_json || []).join(', ')); setBaseId(row.base_model_id || '')
    const type = String(row.ref_json?.type || 'echo')
    setAdapterType(type); initFields(type, row.ref_json); setAdvanced(false)
    setRawJson(JSON.stringify(row.ref_json, null, 2)); setShowForm(true)
  }

  const buildRef = (): Record<string, unknown> => {
    if (advanced) return JSON.parse(rawJson || '{}')
    const ref: Record<string, unknown> = { type: adapterType }
    Object.entries(fields).forEach(([key, value]) => {
      if (value !== '' && value !== undefined) ref[key] = value
    })
    return ref
  }

  const save = async () => {
    setBusy(true)
    try {
      const ref = buildRef()
      const payload = {
        name, kind, description, adapter_type: kind === 'finetuned' ? 'full' : '',
        ref_json: ref, tags_json: tags.split(',').map((t) => t.trim()).filter(Boolean),
        base_model_id: baseId || undefined,
      }
      const result = editing
        ? await api.put(`/models/${editing.id}`, payload)
        : await api.post(`/projects/${pid}/models`, payload)
      const warnings = (result as { warnings?: string[] }).warnings || []
      app.notify(warnings.length ? warnings.join('；') : (editing ? '模型已更新' : '模型已注册'), 'success')
      setShowForm(false); list.reload(); app.bump()
    } catch (e) { app.notify((e as Error).message, 'error') }
    finally { setBusy(false) }
  }

  const test = async (id: string) => {
    setTestId(id); setTestOutput('调用中…')
    try {
      const result = await api.post<{ output: string; ok: boolean }>(`/models/${id}/test`, { prompt: testPrompt })
      setTestOutput(result.output)
      app.notify(result.ok ? '模型调用成功' : '模型调用失败，请检查路径或端点', result.ok ? 'success' : 'error')
      list.reload()
    } catch (e) { setTestOutput(`[错误] ${(e as Error).message}`) }
  }

  const archive = async (row: ModelRow) => {
    try {
      await api.del(`/models/${row.id}`)
      app.notify(`已归档「${row.name}」`, 'success'); list.reload(); app.bump()
    } catch (e) { app.notify((e as Error).message, 'error') }
  }

  return <div className="editor-pad">
    <div className="row" style={{ marginBottom: 12 }}>
      <h2 style={{ margin: 0, fontSize: 16 }}>模型注册表</h2>
      <span className="pill info">{list.data?.total ?? 0} 个</span>
      <div style={{ flex: 1 }} />
      <button className="btn sm" onClick={() => list.reload()}>刷新</button>
      <button className="btn sm primary" onClick={openCreate}>＋ 注册模型</button>
    </div>
    <p className="small muted">
      模型权重留在训练师自己的磁盘 / 推理服务上，平台只保存<strong>路径或端点引用</strong>与版本血缘。
      注册一次后，评测、A/B、LLM 裁判、微调都可直接选择使用。
    </p>

    {showForm && <div className="card" style={{ margin: '12px 0', padding: 16 }}>
      <div className="row" style={{ marginBottom: 10 }}>
        <strong>{editing ? `编辑 · ${editing.name}` : '注册模型'}</strong>
        <div style={{ flex: 1 }} />
        <button className="btn sm ghost" onClick={() => setAdvanced(!advanced)}>
          高级：{advanced ? 'JSON 编辑' : '表单'}
        </button>
        <button className="btn sm ghost" onClick={() => setShowForm(false)}>取消</button>
      </div>
      {!advanced ? <>
        <div className="row" style={{ alignItems: 'flex-start', flexWrap: 'wrap' }}>
          <div className="field" style={{ width: 220 }}>
            <label>名称 *</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="例如：客服意图 LoRA v2" />
          </div>
          <div className="field" style={{ width: 170 }}>
            <label>类型</label>
            <select value={kind} onChange={(e) => setKind(e.target.value)}>
              {(kinds.data?.kinds || ['base']).map((k) => <option key={k} value={k}>{KIND_LABELS[k] || k}</option>)}
            </select>
          </div>
          <div className="field" style={{ width: 220 }}>
            <label>适配器（怎么调用）</label>
            <select value={adapterType} onChange={(e) => { setAdapterType(e.target.value); initFields(e.target.value) }}>
              {defs.map((d) => <option key={d.type} value={d.type}>{d.label}</option>)}
            </select>
          </div>
          <div className="field" style={{ width: 200 }}>
            <label>基座模型（可选）</label>
            <select value={baseId} onChange={(e) => setBaseId(e.target.value)}>
              <option value="">— 无 —</option>
              {(list.data?.items || []).filter((m) => m.id !== editing?.id).map((m) =>
                <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
          </div>
          <div className="field grow">
            <label>描述 / 标签</label>
            <div className="row">
              <input className="grow" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="说明" />
              <input style={{ width: 160 }} value={tags} onChange={(e) => setTags(e.target.value)} placeholder="标签，逗号分隔" />
            </div>
          </div>
        </div>
        <p className="small dim" style={{ margin: '2px 0 8px' }}>{current?.description}</p>
        <div className="row" style={{ alignItems: 'flex-start', flexWrap: 'wrap' }}>
          {current?.fields.map((f) => <div className="field" key={f.key} style={{ width: 230 }}>
            <label>{f.label}{f.required ? ' *' : ''}</label>
            {f.type === 'checkbox' ?
              <label className="row" style={{ fontWeight: 400 }}>
                <input type="checkbox" checked={Boolean(fields[f.key])}
                  onChange={(e) => setFields((p) => ({ ...p, [f.key]: e.target.checked }))} /> 启用
              </label> :
              <div className="row">
                <input className="grow" type={f.type === 'number' ? 'number' : 'text'}
                  value={String(fields[f.key] ?? '')}
                  onChange={(e) => setFields((p) => ({ ...p, [f.key]: f.type === 'number' ? Number(e.target.value) : e.target.value }))} />
                {(f.key === 'model' || f.key === 'command' || f.key === 'path') &&
                  <button className="btn sm" title="选择本地路径" onClick={async () => {
                    const picked = await window.aixianDesktop?.openPath?.({ folder: f.key === 'model' })
                    if (picked) setFields((p) => ({ ...p, [f.key]: picked }))
                  }}>…</button>}
              </div>}
          </div>)}
        </div>
      </> : <textarea className="mono" spellCheck={false} style={{ width: '100%', minHeight: 180 }}
        value={rawJson || JSON.stringify({ type: adapterType, ...fields }, null, 2)}
        onChange={(e) => setRawJson(e.target.value)} />}
      <div className="row" style={{ marginTop: 10 }}>
        <button className="btn sm primary" disabled={busy || !name.trim()} onClick={() => void save()}>
          {busy ? '保存中…' : editing ? '保存修改' : '注册'}
        </button>
        <span className="small dim">本地路径暂不存在也可先注册，之后放好权重即可；状态会标为「路径缺失」。</span>
      </div>
    </div>}

    <div className="section"><h3>已注册模型</h3>
      <DataTable columns={[
        { key: 'name', label: '名称', render: (r) => <button className="btn sm ghost" onClick={() =>
          app.openTab({ title: `模型 · ${r.name}`, kind: 'model', resourceId: String(r.id) })}>{String(r.name)}</button> },
        { key: 'kind', label: '类型', render: (r) => KIND_LABELS[String(r.kind)] || String(r.kind) },
        { key: 'ref_json', label: '路径 / 端点', render: (r) => <span className="mono small">{refSummary(r.ref_json as Record<string, unknown>)}</span> },
        { key: 'status', label: '状态', render: (r) => <StatusPill status={String(r.status)} /> },
        { key: 'version', label: '版本', render: (r) => `v${r.version}` },
        { key: 'usage', label: '引用', render: (r) => {
          const u = r.usage as ModelRow['usage']
          return `评测 ${u.eval_runs} / A/B ${u.ab_tests} / 派生 ${u.derived_models}`
        } },
        { key: 'id', label: '操作', render: (r) => <div className="row">
          <button className="btn sm" onClick={() => void test(String(r.id))}>测试</button>
          <button className="btn sm" onClick={() => openEdit(r as unknown as ModelRow)}>编辑</button>
          <button className="btn sm danger" onClick={() => void archive(r as unknown as ModelRow)}>归档</button>
        </div> },
      ]} rows={(list.data?.items || []) as unknown as Record<string, unknown>[]}
        empty="还没有注册模型。点击「注册模型」，填入自己的权重路径或推理端点即可。" />
    </div>

    {testOutput && <div className="section"><h3>调用结果 · {testId.slice(0, 8)}</h3>
      <div className="row" style={{ marginBottom: 8 }}>
        <input className="grow" value={testPrompt} onChange={(e) => setTestPrompt(e.target.value)} />
        <button className="btn sm" onClick={() => void test(testId)}>重测</button>
      </div>
      <pre className="json-view" style={{ maxHeight: 200 }}>{testOutput}</pre>
    </div>}
  </div>
}

export function ModelDetailView({ tab }: { tab: Tab }) {
  const app = useApp()
  const id = tab.resourceId || ''
  const detail = useFetch<ModelRow & {
    usage: ModelRow['usage']; base_model: { id: string; name: string } | null
    source_run: { id: string; name: string } | null; params_json: Record<string, unknown>
  }>(`/models/${id}`, [id, app.revision])
  const [prompt, setPrompt] = useState('你好')
  const [output, setOutput] = useState('')
  const row = detail.data

  const test = async () => {
    try {
      const result = await api.post<{ output: string }>(`/models/${id}/test`, { prompt })
      setOutput(result.output); app.notify('调用完成', 'success')
    } catch (e) { app.notify((e as Error).message, 'error') }
  }

  return <div className="editor-pad">
    <div className="row" style={{ marginBottom: 12 }}>
      <h2 style={{ margin: 0, fontSize: 16 }}>{row?.name || '模型详情'}</h2>
      {row && <><span className="pill info">{KIND_LABELS[row.kind] || row.kind}</span>
        <span className="pill">v{row.version}</span><StatusPill status={row.status} /></>}
      <div style={{ flex: 1 }} />
      <button className="btn sm" onClick={() => app.openTab({ title: '模型注册表', kind: 'registry' })}>返回注册表</button>
    </div>
    {row && <>
      <div className="cards">
        <div className="card"><div className="k">评测引用</div><div className="v">{row.usage.eval_runs}</div></div>
        <div className="card"><div className="k">A/B 引用</div><div className="v">{row.usage.ab_tests}</div></div>
        <div className="card"><div className="k">派生模型</div><div className="v">{row.usage.derived_models}</div></div>
        <div className="card"><div className="k">路径状态</div>
          <div className="v" style={{ fontSize: 15 }}>{row.path_status === 'ok' ? '可用' : '路径缺失'}</div></div>
      </div>
      <div className="section"><h3>引用配置（平台不复制权重）</h3><JsonView value={row.ref_json} /></div>
      <div className="section"><h3>血缘</h3>
        <p className="small muted">基座：{row.base_model?.name || '—'} · 来源实验：{row.source_run?.name || '—'}</p>
      </div>
      <div className="section"><h3>调用测试</h3>
        <div className="row">
          <input className="grow" value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          <button className="btn sm primary" onClick={() => void test()}>调用</button>
        </div>
        {output && <pre className="json-view" style={{ marginTop: 8, maxHeight: 200 }}>{output}</pre>}
      </div>
    </>}
  </div>
}
