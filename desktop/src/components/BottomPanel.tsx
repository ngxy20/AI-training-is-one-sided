import { useEffect, useMemo, useRef, useState } from 'react'
import { api, qs } from '../api'
import { useApp } from '../store'
import { DataTable, Empty, StatusPill, useFetch } from '../ui'

const TABS = ['任务队列', '日志', '终端', '问题', '审计']

export function BottomPanel() {
  const app = useApp()
  const pid = app.activeProject?.id || ''
  const [jobFilter, setJobFilter] = useState('')
  const [filterText, setFilterText] = useState('')
  const [follow, setFollow] = useState(true)
  const [command, setCommand] = useState('')
  const [terminalOutput, setTerminalOutput] = useState('')
  const logRef = useRef<HTMLDivElement>(null)
  const audit = useFetch<{ items: Record<string, unknown>[] }>(
    pid && app.bottomTab === '审计' ? `/audit-events${qs({ pid, size: 100 })}` : null,
    [pid, app.bottomTab, app.revision])

  useEffect(() => { if (follow && logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight },
    [app.logs.length, follow, app.bottomTab])

  const jobs = useMemo(() => app.jobs.filter((job) => !jobFilter || job.id === jobFilter), [app.jobs, jobFilter])
  const lines = useMemo(() => app.logs.filter((line) =>
    (!jobFilter || line.jobId === jobFilter) && (!filterText || line.line.toLowerCase().includes(filterText.toLowerCase()))),
    [app.logs, jobFilter, filterText])
  const problems = useMemo(() => app.logs.filter((line) =>
    /error|traceback|failed|exception/i.test(line.line)).slice(-200), [app.logs])

  const runTerminal = async () => {
    if (!command.trim()) return
    try {
      const result = await api.post<{ output: string; exit_code: number }>('/terminal/exec', { pid, command })
      setTerminalOutput((prev) => `${prev}$ aixian> ${command}\n${result.output}\n[exit ${result.exit_code}]\n\n`)
      setCommand('')
    } catch (e) { setTerminalOutput((prev) => `${prev}[错误] ${(e as Error).message}\n`) }
  }

  return <section className="bottom">
    <div className="bottom-tabs">
      {TABS.map((name) => <button key={name} className={app.bottomTab === name ? 'active' : ''}
        onClick={() => app.patch({ bottomTab: name })}>{name}</button>)}
      <div style={{ flex: 1 }} />
      <span className="small dim" style={{ marginRight: 10 }}>{app.logs.length} 行日志</span>
      <button className="icon-btn" title="折叠/展开（当前固定）" onClick={() => app.refreshJobs()}>⟳</button>
    </div>
    <div className="bottom-content">
      {app.bottomTab === '任务队列' && <div style={{ flex: 1, overflow: 'auto', padding: 10 }}>
        <DataTable columns={[
          { key: 'type', label: '类型' },
          { key: 'status', label: '状态', render: (r) => <StatusPill status={String(r.status)} /> },
          { key: 'progress', label: '进度', render: (r) => `${Math.round(Number(r.progress || 0) * 100)}%` },
          { key: 'runner_type', label: 'Runner' },
          { key: 'id', label: '操作', render: (r) => <button className="btn sm danger"
            onClick={async (e) => { e.stopPropagation(); await api.post(`/jobs/${r.id}/cancel`); app.refreshJobs() }}>取消</button> },
        ]} rows={app.jobs as unknown as Record<string, unknown>[]} empty="暂无任务" />
      </div>}

      {app.bottomTab === '日志' && <>
        <div className="log-side">
          <div className={!jobFilter ? 'active' : ''} onClick={() => setJobFilter('')}>全部任务</div>
          {app.jobs.map((job) => <div key={job.id} className={jobFilter === job.id ? 'active' : ''}
            onClick={() => setJobFilter(job.id)} title={job.id}>{job.type} · {job.id.slice(0, 6)}</div>)}
        </div>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <div className="row" style={{ padding: '6px 10px', borderBottom: '1px solid var(--line)' }}>
            <input className="grow" placeholder="过滤日志…" value={filterText} onChange={(e) => setFilterText(e.target.value)} />
            <label className="row small"><input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> 跟随</label>
            <button className="btn sm" onClick={() => void navigator.clipboard?.writeText(lines.map((l) => l.line).join('\n'))}>复制</button>
            <button className="btn sm" onClick={() => app.patch({ logs: [] })}>清空</button>
          </div>
          <div className="log-lines" ref={logRef}>
            {lines.map((line, index) => <div key={index}
              className={`line ${/error|traceback|failed/i.test(line.line) ? 'err' : ''} ${line.line.startsWith('[aixian]') ? 'sys' : ''}`}>{line.line}</div>)}
            {!lines.length && <span className="dim">等待日志流…（运行脚本 / 清洗 / 训练后实时推送）</span>}
          </div>
        </div>
      </>}

      {app.bottomTab === '终端' && <div style={{ flex: 1, display: 'flex', flexDirection: 'column', padding: 10, minWidth: 0 }}>
        <div className="row">
          <span className="mono small" style={{ color: 'var(--green)' }}>{app.activeProject?.workspace_path || '~'} $</span>
          <input className="grow" value={command} placeholder="在项目工作区内执行本地命令，例如：dir / python --version"
            onChange={(e) => setCommand(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void runTerminal() }} />
          <button className="btn sm primary" onClick={() => void runTerminal()}>执行</button>
        </div>
        <pre className="json-view" style={{ flex: 1, marginTop: 8, color: '#c8d6e5' }}>{terminalOutput || '本地终端已就绪。命令在隔离的项目工作区内执行，超时 45s。'}</pre>
      </div>}

      {app.bottomTab === '问题' && <div className="log-lines">
        {problems.length ? problems.map((line, index) => <div className="line err" key={index}>{line.line}</div>)
          : <span className="dim">没有检测到问题。</span>}
        {app.jobs.filter((j) => j.status === 'failed').map((job) =>
          <div className="line err" key={job.id}>[Job {job.id.slice(0, 8)}] {job.error}</div>)}
      </div>}

      {app.bottomTab === '审计' && <div style={{ flex: 1, overflow: 'auto', padding: 10 }}>
        <DataTable columns={[
          { key: 'at', label: '时间' }, { key: 'actor', label: '操作者' },
          { key: 'action', label: '动作' }, { key: 'entity_type', label: '实体' },
          { key: 'entity_id', label: 'ID' },
        ]} rows={audit.data?.items || []} empty="暂无审计事件" />
      </div>}
    </div>
  </section>
}
