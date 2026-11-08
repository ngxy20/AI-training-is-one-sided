import React, { useEffect, useState } from 'react'
import { api } from './api'
import type { FieldSpec } from './types'

export function Modal({ title, description, children, footer, onClose }: {
  title: string; description?: string; children: React.ReactNode; footer: React.ReactNode; onClose: () => void
}) {
  return <div className="overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
    <div className="modal">
      <header><h2>{title}</h2>{description && <p>{description}</p>}</header>
      <div className="content">{children}</div>
      <footer>{footer}</footer>
    </div>
  </div>
}

export function Empty({ text }: { text: string }) {
  return <div className="tree-empty">{text}</div>
}

export function StatusPill({ status }: { status?: string | null }) {
  if (!status) return null
  const ok = ['succeeded', 'ok', 'completed', 'active', 'approved'].includes(status)
  const bad = ['failed', 'rejected', 'cancelled', 'error'].includes(status)
  return <span className={`pill ${ok ? 'ok' : bad ? 'bad' : 'warn'}`}>{status}</span>
}

export interface Column {
  key: string
  label: string
  render?: (row: Record<string, unknown>) => React.ReactNode
  width?: number
}

export function DataTable({ columns, rows, onRowClick, empty = '暂无数据', maxHeight }: {
  columns: Column[]; rows: Record<string, unknown>[]; onRowClick?: (row: Record<string, unknown>) => void
  empty?: string; maxHeight?: number
}) {
  if (!rows.length) return <Empty text={empty} />
  return <div className="table-wrap" style={maxHeight ? { maxHeight } : undefined}>
    <table className="grid">
      <thead><tr>{columns.map((c) => <th key={c.key} style={{ width: c.width }}>{c.label}</th>)}</tr></thead>
      <tbody>{rows.map((row, i) => <tr key={String(row.id ?? i)} className={onRowClick ? 'clickable' : ''}
        onClick={() => onRowClick?.(row)}>
        {columns.map((c) => <td key={c.key} title={String(row[c.key] ?? '')}>
          {c.render ? c.render(row) : String(row[c.key] ?? '')}
        </td>)}
      </tr>)}</tbody>
    </table>
  </div>
}

export function MetricCards({ metrics }: { metrics?: Record<string, unknown> | null }) {
  const entries = Object.entries(metrics || {}).filter(([, v]) => typeof v === 'number' || typeof v === 'boolean')
  if (!entries.length) return null
  return <div className="cards">{entries.map(([key, value]) => <div className="card" key={key}>
    <div className="k">{key}</div>
    <div className={`v ${typeof value === 'number' && value < 0.5 ? 'warn' : ''}`}>{String(value)}</div>
  </div>)}</div>
}

export function JsonView({ value }: { value: unknown }) {
  return <pre className="json-view">{JSON.stringify(value, null, 2)}</pre>
}

export function useFetch<T>(url: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [nonce, setNonce] = useState(0)
  useEffect(() => {
    if (!url) { setLoading(false); return }
    let cancelled = false
    setLoading(true)
    api.get<T>(url).then((result) => {
      if (!cancelled) { setData(result); setError('') }
    }).catch((e: Error) => { if (!cancelled) setError(e.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [url, nonce, ...deps]) // eslint-disable-line react-hooks/exhaustive-deps
  return { data, error, loading, reload: () => setNonce((n) => n + 1) }
}

export function FieldControl({ spec, value, onChange }: {
  spec: FieldSpec; value: unknown; onChange: (value: unknown) => void
}) {
  const [options, setOptions] = useState<{ label: string; value: string }[]>(spec.options || [])
  const [error, setError] = useState('')

  useEffect(() => {
    if (!spec.optionsFrom) return
    const endpoint = spec.optionsFrom.endpoint
    api.get<unknown>(endpoint).then((result) => {
      const list = Array.isArray(result) ? result : (result as { items?: unknown[] }).items || []
      setOptions((list as Record<string, unknown>[]).map((row) => ({
        label: String(row[spec.optionsFrom!.label] ?? row.name ?? row.id ?? ''),
        value: String(row[spec.optionsFrom!.value] ?? row.id ?? ''),
      })))
    }).catch((e: Error) => setError(e.message))
  }, [spec.optionsFrom?.endpoint]) // eslint-disable-line react-hooks/exhaustive-deps

  const setValue = (raw: string) => {
    if (spec.type === 'number') onChange(raw === '' ? '' : Number(raw))
    else if (spec.type === 'json') {
      try { onChange(raw.trim() ? JSON.parse(raw) : {}); setError('') }
      catch { setError('JSON 格式无效'); onChange(raw) }
    } else onChange(raw)
  }

  const text = spec.type === 'json'
    ? (typeof value === 'string' ? value : JSON.stringify(value ?? spec.default ?? {}, null, 2))
    : String(value ?? '')

  return <div className="field">
    <label>{spec.label}{spec.required && <span style={{ color: 'var(--red)' }}> *</span>}</label>
    {spec.type === 'select' ? <select value={String(value ?? '')} onChange={(e) => onChange(e.target.value)}>
      <option value="">— 请选择 —</option>
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select> : spec.type === 'checkbox' ? <label className="row" style={{ fontWeight: 400 }}>
      <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} /> 启用
    </label> : spec.type === 'textarea' || spec.type === 'json' ?
      <textarea value={text} placeholder={spec.placeholder} spellCheck={false} onChange={(e) => setValue(e.target.value)} /> :
      spec.type === 'path' ? <div className="row">
        <input className="grow" value={text} placeholder={spec.placeholder || '文件绝对路径'} onChange={(e) => onChange(e.target.value)} />
        <button className="btn sm" onClick={async () => {
          const picked = await window.aixianDesktop?.openPath?.({ folder: false })
          if (picked) onChange(picked)
        }}>选择…</button>
      </div> :
        <input type={spec.type === 'number' ? 'number' : 'text'} value={text} placeholder={spec.placeholder}
          onChange={(e) => setValue(e.target.value)} />}
    {spec.help && <span className="help">{spec.help}</span>}
    {error && <span className="help" style={{ color: 'var(--red)' }}>{error}</span>}
  </div>
}
