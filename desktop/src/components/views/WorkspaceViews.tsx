import { useEffect, useState } from 'react'
import { api } from '../../api'
import { useApp } from '../../store'
import { DataTable, Empty, StatusPill, useFetch } from '../../ui'

interface AdapterDef {
  type: string; label: string; description: string; offline: boolean
  fields: { key: string; label: string; default?: unknown; required?: boolean; type?: string }[]
}

export function ModelsView() {
  const app = useApp()
  const pid = app.activeProject?.id || ''
  const catalog = useFetch<{ items: AdapterDef[]; plugins: { id: string; name: string }[]; scorers: string[] }>(
    pid ? `/projects/${pid}/model-adapters` : null, [pid])
  const suites = useFetch<{ items: { id: string; name: string }[] }>(
    pid ? `/projects/${pid}/eval-suites` : null, [pid, app.revision])
  const registered = useFetch<{ items: { id: string; name: string; ref_json: Record<string, unknown> }[] }>(
    pid ? `/projects/${pid}/models` : null, [pid, app.revision])
  const [selected, setSelected] = useState('openai')
  const [registryId, setRegistryId] = useState('')
  const [config, setConfig] = useState('{}')
  const [prompt, setPrompt] = useState('你好，请用一句话介绍自己。')
  const [output, setOutput] = useState('')
  const [suiteId, setSuiteId] = useState('')
  const [busy, setBusy] = useState(false)

  const pick = (type: string) => {
    setSelected(type)
    const def = catalog.data?.items.find((d) => d.type === type)
    const initial: Record<string, unknown> = { type, concurrency: 4 }
    def?.fields.forEach((f) => { if (f.default !== undefined) initial[f.key] = f.default })
    setConfig(JSON.stringify(initial, null, 2))
    setOutput('')
  }

  useEffect(() => { if (catalog.data?.items.length && !config.includes('"type"')) pick('openai') }, [catalog.data]) // eslint-disable-line

  const parseConfig = () => JSON.parse(config || '{}') as Record<string, unknown>

  const test = async () => {
    setBusy(true)
    try {
      const result = await api.post<{ output: string }>(`/projects/${pid}/model-adapters/test`,
        { prompt, model_ref_json: parseConfig() })
      setOutput(result.output)
      app.notify('模型调用成功', 'success')
    } catch (e) { setOutput(`[错误] ${(e as Error).message}`); app.notify((e as Error).message, 'error') }
    finally { setBusy(false) }
  }

  const runEval = async () => {
    if (!suiteId) { app.notify('请先选择评测套件', 'error'); return }
    try {
      await api.post(`/eval-suites/${suiteId}/runs`, {
        model_id: registryId || undefined,
        model_ref_json: registryId ? undefined : parseConfig(),
        scorer_json: { type: 'exact_match' },
      })
      app.notify('评测任务已提交，可在底部日志面板查看', 'success')
      app.refreshJobs(); app.bump()
    } catch (e) { app.notify((e as Error).message, 'error') }
  }

  return <div className="editor-pad">
    <div className="row" style={{ marginBottom: 12 }}><h2 style={{ margin: 0, fontSize: 16 }}>模型推理适配器</h2>
      <span className="pill info">{catalog.data?.items.length || 0} 种</span>
      <div style={{ flex: 1 }} />
      <button className="btn sm" onClick={() => { void catalog.reload(); void suites.reload() }}>刷新</button>
    </div>
    <p className="small muted">评测套件、A/B 测试与 LLM-as-judge 现在可直接调用模型生成输出，而不是只统计预置结果。
      模型路径/端点请在<b>模型注册表</b>里登记一次，之后各处下拉复用。</p>
    <div className="row" style={{ marginBottom: 10 }}>
      <select value={registryId} onChange={(e) => {
        const id = e.target.value
        setRegistryId(id)
        const model = registered.data?.items.find((m) => m.id === id)
        if (model) { setConfig(JSON.stringify(model.ref_json, null, 2)); setSelected(String(model.ref_json.type || 'echo')); setOutput('') }
      }} style={{ minWidth: 230 }}>
        <option value="">— 从模型注册表载入 —</option>
        {(registered.data?.items || []).map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
      </select>
      <button className="btn sm" onClick={() => app.openTab({ title: '模型注册表', kind: 'registry' })}>打开注册表</button>
    </div>
    <div className="cards">
      {(catalog.data?.items || []).map((def) => <div key={def.type}
        className={`card theme-adapter-card ${selected === def.type ? 'active' : ''}`}
        onClick={() => pick(def.type)} style={{ cursor: 'pointer' }}>
        <div className="row"><b>{def.label}</b><span className={`pill ${def.offline ? '' : 'info'}`}>
          {def.offline ? '本地' : '远端'}</span></div>
        <p className="small dim" style={{ margin: '6px 0 0' }}>{def.description}</p>
        <div className="mono small dim" style={{ marginTop: 6 }}>{def.type}</div>
      </div>)}
    </div>
    <div className="section"><h3>配置与连通性测试 · {selected}</h3>
      <textarea className="mono" spellCheck={false} style={{ width: '100%', minHeight: 170 }}
        value={config} onChange={(e) => setConfig(e.target.value)} />
      <div className="row" style={{ marginTop: 8 }}>
        <input className="grow" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="测试提示词" />
        <button className="btn sm primary" disabled={busy} onClick={() => void test()}>{busy ? '调用中…' : '测试调用'}</button>
      </div>
      {output && <pre className="json-view" style={{ marginTop: 8 }}>{output}</pre>}
    </div>
    <div className="section"><h3>用该适配器运行评测套件</h3>
      <div className="row">
        <select value={suiteId} onChange={(e) => setSuiteId(e.target.value)} style={{ minWidth: 220 }}>
          <option value="">— 选择评测套件 —</option>
          {(suites.data?.items || []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <button className="btn sm primary" onClick={() => void runEval()}>提交评测</button>
        <span className="small dim">评分器：exact_match（可在命令面板中用 JSON 指定 llm_judge / plugin）</span>
      </div>
    </div>
    {!!catalog.data?.plugins.length && <div className="section"><h3>插件提供的适配器</h3>
      <p className="small muted">{catalog.data.plugins.map((p) => p.name).join('、')}</p></div>}
  </div>
}

interface ScheduleRow {
  id: string; name: string; type: string; cron_expr: string; target_id: string
  payload_json: Record<string, unknown>; enabled: number; next_run_at: string | null
  last_run_at: string | null; last_job_id: string | null; last_error: string; run_count: number
}

export function SchedulesView() {
  const app = useApp()
  const pid = app.activeProject?.id || ''
  const types = useFetch<{ items: { type: string; label: string; needs_target: boolean; payload_template: Record<string, unknown> }[] }>(
    pid ? `/projects/${pid}/schedule-types` : null, [pid])
  const list = useFetch<{ items: ScheduleRow[] }>(pid ? `/projects/${pid}/schedules` : null, [pid, app.revision])
  const [type, setType] = useState('command')
  const [name, setName] = useState('')
  const [cron, setCron] = useState('*/5 * * * *')
  const [target, setTarget] = useState('')
  const [payload, setPayload] = useState('{"command": "echo hello"}')
  const [error, setError] = useState('')

  useEffect(() => {
    const def = types.data?.items.find((d) => d.type === type)
    if (def) setPayload(JSON.stringify(def.payload_template, null, 2))
  }, [type, types.data]) // eslint-disable-line

  const create = async () => {
    try {
      await api.post(`/projects/${pid}/schedules`, {
        name: name || `${type} 定时任务`, type, cron_expr: cron,
        target_id: target, payload_json: JSON.parse(payload || '{}'),
      })
      setName(''); setError('')
      app.notify('定时任务已创建', 'success'); list.reload(); app.bump()
    } catch (e) { setError((e as Error).message) }
  }

  const runNow = async (id: string) => {
    try { await api.post(`/schedules/${id}/run-now`); app.notify('已立即触发', 'success'); await app.refreshJobs() }
    catch (e) { app.notify((e as Error).message, 'error') }
  }
  const toggle = async (row: ScheduleRow) => {
    try { await api.patch(`/schedules/${row.id}`, { enabled: !row.enabled }); list.reload() }
    catch (e) { app.notify((e as Error).message, 'error') }
  }
  const remove = async (id: string) => {
    try { await api.del(`/schedules/${id}`); list.reload(); app.notify('已删除', 'success') }
    catch (e) { app.notify((e as Error).message, 'error') }
  }

  return <div className="editor-pad">
    <div className="row" style={{ marginBottom: 12 }}><h2 style={{ margin: 0, fontSize: 16 }}>定时调度</h2>
      <span className="pill info">五段 cron：分 时 日 月 周</span>
      <div style={{ flex: 1 }} /><button className="btn sm" onClick={() => void list.reload()}>刷新</button></div>
    <div className="section"><h3>新建定时任务</h3>
      <div className="row">
        <input placeholder="名称" value={name} onChange={(e) => setName(e.target.value)} style={{ width: 180 }} />
        <select value={type} onChange={(e) => setType(e.target.value)} style={{ minWidth: 170 }}>
          {(types.data?.items || []).map((d) => <option key={d.type} value={d.type}>{d.label}</option>)}
        </select>
        <input className="mono" value={cron} onChange={(e) => setCron(e.target.value)} style={{ width: 150 }} />
        <input placeholder="目标资源 ID（脚本/Pipeline/套件）" value={target} onChange={(e) => setTarget(e.target.value)} className="grow" />
        <button className="btn sm primary" onClick={() => void create()}>创建</button>
      </div>
      <textarea className="mono" spellCheck={false} style={{ width: '100%', minHeight: 110, marginTop: 8 }}
        value={payload} onChange={(e) => setPayload(e.target.value)} />
      {error && <div className="small" style={{ color: 'var(--red)', marginTop: 6 }}>{error}</div>}
    </div>
    <div className="section"><h3>已配置</h3>
      <DataTable columns={[
        { key: 'name', label: '名称' }, { key: 'type', label: '类型' },
        { key: 'cron_expr', label: 'cron', render: (r) => <span className="mono">{String(r.cron_expr)}</span> },
        { key: 'enabled', label: '状态', render: (r) => r.enabled ? <StatusPill status="active" /> : <span className="pill">停用</span> },
        { key: 'next_run_at', label: '下次运行' }, { key: 'run_count', label: '已运行' },
        { key: 'last_error', label: '上次错误', render: (r) => <span className="small" style={{ color: 'var(--red)' }}>{String(r.last_error || '')}</span> },
        { key: 'id', label: '操作', render: (r) => <div className="row">
          <button className="btn sm" onClick={() => void runNow(String(r.id))}>立即运行</button>
          <button className="btn sm" onClick={() => void toggle(r as unknown as ScheduleRow)}>{r.enabled ? '停用' : '启用'}</button>
          <button className="btn sm danger" onClick={() => void remove(String(r.id))}>删除</button>
        </div> },
      ]} rows={(list.data?.items || []) as unknown as Record<string, unknown>[]} empty="暂无定时任务" />
    </div>
  </div>
}

interface UserRow { id: string; username: string; display_name: string; global_role: string; active: number; color: string }
interface MemberRow { id: string; user_id: string; username: string; display_name: string; role: string; color: string }

export function MembersView() {
  const app = useApp()
  const pid = app.activeProject?.id || ''
  const users = useFetch<{ items: UserRow[] }>('/users', [app.revision])
  const members = useFetch<{ items: MemberRow[] }>(pid ? `/projects/${pid}/members` : null, [pid, app.revision])
  const roles = useFetch<{ items: { role: string; label: string }[] }>('/roles')
  const me = useFetch<{ user: UserRow; projects: { id: string; name: string; role: string }[] }>('/me', [app.revision])
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [newRole, setNewRole] = useState('viewer')
  const [addUserId, setAddUserId] = useState('')
  const [addRole, setAddRole] = useState('annotator')

  const switchUser = async (id: string) => {
    try { await api.post('/me', { user_id: id }); app.notify('已切换当前身份', 'success'); me.reload(); app.bump() }
    catch (e) { app.notify((e as Error).message, 'error') }
  }
  const createUser = async () => {
    try {
      await api.post('/users', { username, display_name: displayName || username, global_role: newRole })
      setUsername(''); setDisplayName(''); app.notify('用户已创建', 'success'); users.reload()
    } catch (e) { app.notify((e as Error).message, 'error') }
  }
  const addMember = async () => {
    if (!addUserId) { app.notify('请选择用户', 'error'); return }
    try {
      await api.post(`/projects/${pid}/members`, { user_id: addUserId, role: addRole })
      app.notify('成员权限已更新', 'success'); members.reload(); me.reload(); app.bump()
    } catch (e) { app.notify((e as Error).message, 'error') }
  }
  const removeMember = async (userId: string) => {
    try { await api.del(`/projects/${pid}/members/${userId}`); members.reload(); me.reload() }
    catch (e) { app.notify((e as Error).message, 'error') }
  }

  return <div className="editor-pad">
    <div className="row" style={{ marginBottom: 12 }}><h2 style={{ margin: 0, fontSize: 16 }}>成员与权限</h2>
      <span className="pill info">当前身份：{me.data?.user?.display_name || '—'}</span>
      <div style={{ flex: 1 }} /><button className="btn sm" onClick={() => { void users.reload(); void members.reload(); void me.reload() }}>刷新</button></div>
    <div className="section"><h3>切换当前本地身份</h3>
      <div className="row">
        <select value={me.data?.user?.id || ''} onChange={(e) => void switchUser(e.target.value)} style={{ minWidth: 240 }}>
          {(users.data?.items || []).filter((u) => u.active).map((u) =>
            <option key={u.id} value={u.id}>{u.display_name}（{u.username}）</option>)}
        </select>
        <span className="small dim">本项目角色：{me.data?.projects.find((p) => p.id === pid)?.role || '—'}</span>
      </div>
      <p className="small dim">项目未配置成员时沿用本地负责人语义；一旦添加成员，写操作按角色强制校验。</p>
    </div>
    <div className="section"><h3>新建本地用户</h3>
      <div className="row">
        <input placeholder="用户名" value={username} onChange={(e) => setUsername(e.target.value)} />
        <input placeholder="显示名" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        <select value={newRole} onChange={(e) => setNewRole(e.target.value)}>
          {(roles.data?.items || []).map((r) => <option key={r.role} value={r.role}>{r.label}</option>)}
        </select>
        <button className="btn sm primary" onClick={() => void createUser()}>创建</button>
      </div>
    </div>
    <div className="section"><h3>项目成员</h3>
      <div className="row" style={{ marginBottom: 8 }}>
        <select value={addUserId} onChange={(e) => setAddUserId(e.target.value)} style={{ minWidth: 200 }}>
          <option value="">— 选择用户 —</option>
          {(users.data?.items || []).map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}
        </select>
        <select value={addRole} onChange={(e) => setAddRole(e.target.value)}>
          {(roles.data?.items || []).map((r) => <option key={r.role} value={r.role}>{r.label}</option>)}
        </select>
        <button className="btn sm primary" onClick={() => void addMember()}>添加 / 修改角色</button>
      </div>
      <DataTable columns={[
        { key: 'display_name', label: '成员' }, { key: 'username', label: '用户名' },
        { key: 'role', label: '角色', render: (r) => <StatusPill status={String(r.role)} /> },
        { key: 'user_id', label: '操作', render: (r) => <button className="btn sm danger"
          onClick={() => void removeMember(String(r.user_id))}>移除</button> },
      ]} rows={(members.data?.items || []) as unknown as Record<string, unknown>[]}
        empty="暂无成员（当前为本地免登录模式）" />
    </div>
    <div className="section"><h3>全部用户</h3>
      {users.data?.items.length ? <DataTable columns={[
        { key: 'display_name', label: '显示名' }, { key: 'username', label: '用户名' },
        { key: 'global_role', label: '全局角色' },
        { key: 'active', label: '状态', render: (r) => r.active ? <span className="pill ok">启用</span> : <span className="pill">停用</span> },
      ]} rows={users.data.items as unknown as Record<string, unknown>[]} /> : <Empty text="暂无用户" />}
    </div>
  </div>
}
