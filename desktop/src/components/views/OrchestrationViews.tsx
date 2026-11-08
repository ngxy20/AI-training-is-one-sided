import { useEffect, useState } from 'react'
import { api } from '../../api'
import { useApp } from '../../store'
import { DataTable, Empty, JsonView, StatusPill, useFetch } from '../../ui'

interface Template {
  id: string; name: string; method: string; description: string
  dataset_format: string; defaults_json: Record<string, unknown>; builtin: number
}
interface NamedItem { id: string; name: string }

export function FineTuneView() {
  const app = useApp()
  const pid = app.activeProject?.id || ''
  const templates = useFetch<{ items: Template[]; methods: string[]; formats: string[] }>(
    pid ? `/projects/${pid}/finetune-templates` : null, [pid, app.revision])
  const models = useFetch<{ items: NamedItem[] }>(pid ? `/projects/${pid}/models` : null, [pid, app.revision])
  const scripts = useFetch<{ items: NamedItem[] }>(pid ? `/projects/${pid}/scripts` : null, [pid, app.revision])
  const versions = useFetch<{ items: NamedItem[] }>(pid ? `/projects/${pid}/dataset-versions` : null, [pid, app.revision])
  const runs = useFetch<{ items: { id: string; name: string; status: string; artifacts_json: Record<string, unknown> }[] }>(
    pid ? `/projects/${pid}/finetune-runs` : null, [pid, app.revision])

  const [templateId, setTemplateId] = useState('builtin:lora')
  const [baseId, setBaseId] = useState('')
  const [scriptId, setScriptId] = useState('')
  const [versionId, setVersionId] = useState('')
  const [name, setName] = useState('微调实验')
  const [params, setParams] = useState('{}')
  const [warnings, setWarnings] = useState<string[]>([])
  const [busy, setBusy] = useState(false)

  const current = templates.data?.items.find((t) => t.id === templateId)
  useEffect(() => {
    if (current) setParams(JSON.stringify(current.defaults_json || {}, null, 2))
  }, [templateId, templates.data]) // eslint-disable-line

  const submit = async () => {
    if (!scriptId || !versionId) { app.notify('请选择训练脚本与数据集版本', 'error'); return }
    setBusy(true)
    try {
      const parsed = JSON.parse(params || '{}')
      const result = await api.post<{ job_id: string; format_warnings: { message: string }[] }>(
        `/projects/${pid}/finetune-runs`, {
          name, template_id: templateId, base_model_id: baseId || undefined,
          script_id: scriptId, dataset_version_ids: [versionId], params: parsed,
        })
      setWarnings((result.format_warnings || []).map((w) => w.message))
      app.notify('微调任务已提交，可在底部日志面板查看', 'success')
      app.refreshJobs(); app.bump()
    } catch (e) { app.notify((e as Error).message, 'error') }
    finally { setBusy(false) }
  }

  return <div className="editor-pad">
    <div className="row" style={{ marginBottom: 10 }}>
      <h2 style={{ margin: 0, fontSize: 16 }}>微调工作台</h2>
      <span className="pill info">{templates.data?.items.length || 0} 个模板</span>
      <div style={{ flex: 1 }} />
      <button className="btn sm" onClick={() => { void templates.reload(); void runs.reload() }}>刷新</button>
    </div>
    <p className="small muted">
      平台不实现训练算法：选模板 + 基座模型（注册表里的路径）+ 自己的训练脚本 + 数据集版本，
      平台注入环境变量并启动 Runner；脚本产出的 adapter / checkpoint 会<b>自动登记回模型注册表</b>。
    </p>

    <div className="section"><h3>选择模板</h3>
      <div className="cards">
        {(templates.data?.items || []).map((t) => <div key={t.id}
          className={`card theme-adapter-card ${templateId === t.id ? 'active' : ''}`}
          style={{ cursor: 'pointer' }} onClick={() => setTemplateId(t.id)}>
          <div className="row"><b>{t.name}</b><span className="pill">{t.method}</span></div>
          <p className="small dim" style={{ margin: '6px 0 0' }}>{t.description || '自定义模板'}</p>
          <div className="small dim" style={{ marginTop: 6 }}>训练格式：{t.dataset_format}</div>
        </div>)}
      </div>
    </div>

    <div className="section"><h3>一键配置</h3>
      <div className="row" style={{ alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <div className="field" style={{ width: 190 }}><label>实验名称</label>
          <input value={name} onChange={(e) => setName(e.target.value)} /></div>
        <div className="field" style={{ width: 210 }}><label>基座模型（注册表）</label>
          <select value={baseId} onChange={(e) => setBaseId(e.target.value)}>
            <option value="">— 可不选 —</option>
            {(models.data?.items || []).map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select></div>
        <div className="field" style={{ width: 210 }}><label>训练脚本（自己写的）</label>
          <select value={scriptId} onChange={(e) => setScriptId(e.target.value)}>
            <option value="">— 选择脚本 —</option>
            {(scripts.data?.items || []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select></div>
        <div className="field" style={{ width: 230 }}><label>数据集版本</label>
          <select value={versionId} onChange={(e) => setVersionId(e.target.value)}>
            <option value="">— 选择版本 —</option>
            {(versions.data?.items || []).map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
          </select></div>
      </div>
      <div className="field"><label>微调参数（JSON，来自模板可覆盖）</label>
        <textarea className="mono" spellCheck={false} style={{ minHeight: 130 }} value={params}
          onChange={(e) => setParams(e.target.value)} /></div>
      <div className="row">
        <button className="btn sm primary" disabled={busy} onClick={() => void submit()}>
          {busy ? '提交中…' : '提交微调任务'}
        </button>
        <span className="small dim">脚本可用 AIXIAN_BASE_MODEL / AIXIAN_FINETUNE_PARAMS / AIXIAN_ADAPTER_OUTPUT</span>
      </div>
      {!!warnings.length && <div className="small" style={{ color: 'var(--amber)', marginTop: 8 }}>
        格式提示：{warnings.join('；')}（已继续提交）</div>}
    </div>

    <div className="section"><h3>微调实验</h3>
      <DataTable columns={[
        { key: 'name', label: '实验' },
        { key: 'status', label: '状态', render: (r) => <StatusPill status={String(r.status)} /> },
        { key: 'artifacts_json', label: '已登记产物', render: (r) => {
          const a = r.artifacts_json as { registered_adapters?: unknown[] }
          return `${a?.registered_adapters?.length || 0} 个`
        } },
        { key: 'id', label: '操作', render: (r) => <button className="btn sm" onClick={() =>
          app.openTab({ title: `实验 · ${r.name}`, kind: 'run', resourceId: String(r.id) })}>详情</button> },
      ]} rows={(runs.data?.items || []) as unknown as Record<string, unknown>[]} empty="尚无微调实验" />
    </div>
  </div>
}

interface AgentStep { tool: string; args: Record<string, unknown>; reason?: string; status?: string }
interface AgentSession {
  id: string; goal: string; source: string; status: string
  plan_json: AgentStep[]; result_json: Record<string, unknown>[]; error: string
}

export function AgentView() {
  const app = useApp()
  const pid = app.activeProject?.id || ''
  const tools = useFetch<{ items: { name: string; label: string; risk: string; fields: string[] }[]; high_risk: string[] }>(
    pid ? `/projects/${pid}/agent/tools` : null, [pid])
  const models = useFetch<{ items: NamedItem[] }>(pid ? `/projects/${pid}/models` : null, [pid, app.revision])
  const sessions = useFetch<{ items: AgentSession[] }>(
    pid ? `/projects/${pid}/agent/sessions` : null, [pid, app.revision])
  const [goal, setGoal] = useState('帮我做一次评测并生成报告')
  const [modelId, setModelId] = useState('')
  const [sessionId, setSessionId] = useState('')
  const [stepsText, setStepsText] = useState('[]')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const session = sessions.data?.items.find((s) => s.id === sessionId)

  const makePlan = async () => {
    setBusy(true)
    try {
      const result = await api.post<AgentSession & { warnings: string[] }>(
        `/projects/${pid}/agent/plan`, { goal, model_id: modelId || undefined })
      setSessionId(result.id)
      setStepsText(JSON.stringify(result.plan_json, null, 2))
      setMessage(result.warnings?.join('；') || `已生成 ${result.plan_json.length} 步计划（${result.source === 'llm' ? '模型规划' : '内置流程'}）`)
      sessions.reload()
    } catch (e) { app.notify((e as Error).message, 'error') }
    finally { setBusy(false) }
  }

  const savePlan = async () => {
    try {
      await api.put(`/agent/sessions/${sessionId}/plan`, { steps: JSON.parse(stepsText) })
      app.notify('计划已更新', 'success'); sessions.reload()
    } catch (e) { app.notify((e as Error).message, 'error') }
  }

  const execute = async (confirmed: boolean) => {
    try {
      await savePlan()
      await api.post(`/agent/sessions/${sessionId}/execute`, { confirmed })
      app.notify(confirmed ? '已确认并执行' : '已执行（高风险步骤将等待确认）', 'success')
      app.refreshJobs(); app.bump()
      window.setTimeout(() => { void sessions.reload() }, 1500)
    } catch (e) { app.notify((e as Error).message, 'error') }
  }

  const hasHighRisk = (() => {
    try {
      const steps = JSON.parse(stepsText) as AgentStep[]
      return steps.some((s) => (tools.data?.high_risk || []).includes(s.tool))
    } catch { return false }
  })()

  return <div className="editor-pad">
    <div className="row" style={{ marginBottom: 10 }}>
      <h2 style={{ margin: 0, fontSize: 16 }}>Agent 编排</h2>
      <span className="pill info">{tools.data?.items.length || 0} 个工具</span>
      <div style={{ flex: 1 }} />
      <button className="btn sm" onClick={() => { void sessions.reload(); void tools.reload() }}>刷新</button>
    </div>
    <p className="small muted">
      把自然语言目标转成对现有端点的调用计划，人工可逐步编辑确认后再执行。
      大脑可选注册表里的任意模型；不填则用内置规则流程（完全离线）。高风险动作（微调 / A/B / 定时任务）默认拦截。
    </p>

    <div className="section"><h3>目标</h3>
      <div className="row">
        <input className="grow" value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="描述你想完成的工作" />
        <select value={modelId} onChange={(e) => setModelId(e.target.value)} style={{ minWidth: 170 }}>
          <option value="">— 内置规则规划 —</option>
          {(models.data?.items || []).map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
        </select>
        <button className="btn sm primary" disabled={busy} onClick={() => void makePlan()}>
          {busy ? '规划中…' : '生成计划'}
        </button>
      </div>
      {message && <p className="small dim" style={{ marginTop: 8 }}>{message}</p>}
    </div>

    <div className="section"><h3>执行计划（可编辑）</h3>
      <textarea className="mono" spellCheck={false} style={{ width: '100%', minHeight: 180 }}
        value={stepsText} onChange={(e) => setStepsText(e.target.value)} />
      <div className="row" style={{ marginTop: 8 }}>
        <button className="btn sm" disabled={!sessionId} onClick={() => void savePlan()}>保存计划</button>
        <button className="btn sm primary" disabled={!sessionId} onClick={() => void execute(hasHighRisk)}>
          {hasHighRisk ? '确认并执行（含高风险）' : '执行'}
        </button>
        <button className="btn sm" disabled={!sessionId} onClick={() => void execute(false)}>仅执行低风险</button>
        {session && <><StatusPill status={session.status} /><span className="small dim">{session.id.slice(0, 8)}</span></>}
      </div>
    </div>

    {session?.result_json?.length ? <div className="section"><h3>执行结果</h3>
      <DataTable columns={[
        { key: 'step', label: '步骤' }, { key: 'tool', label: '工具' },
        { key: 'status', label: '状态', render: (r) => <StatusPill status={String(r.status)} /> },
        { key: 'http_status', label: 'HTTP' },
        { key: 'result', label: '结果', render: (r) => <span className="mono small">{JSON.stringify(r.result).slice(0, 90)}</span> },
      ]} rows={session.result_json} />
    </div> : null}

    <div className="section"><h3>历史会话</h3>
      <DataTable maxHeight={240} columns={[
        { key: 'goal', label: '目标' },
        { key: 'source', label: '规划方式' },
        { key: 'status', label: '状态', render: (r) => <StatusPill status={String(r.status)} /> },
        { key: 'id', label: '操作', render: (r) => <button className="btn sm" onClick={() => {
          const found = sessions.data?.items.find((s) => s.id === r.id)
          if (found) { setSessionId(found.id); setStepsText(JSON.stringify(found.plan_json, null, 2)); setGoal(found.goal) }
        }}>载入</button> },
      ]} rows={(sessions.data?.items || []) as unknown as Record<string, unknown>[]} empty="暂无会话" />
    </div>

    <div className="section"><h3>可用工具</h3>
      <div className="row" style={{ flexWrap: 'wrap', gap: 6 }}>
        {(tools.data?.items || []).map((t) => <span key={t.name}
          className={`pill ${t.risk === 'high' ? 'bad' : t.risk === 'medium' ? 'warn' : ''}`}
          title={t.fields.join(', ')}>{t.label} · {t.name}</span>)}
      </div>
    </div>
  </div>
}
