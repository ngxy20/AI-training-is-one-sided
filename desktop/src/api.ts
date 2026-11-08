export const API = '/api/v1'

export interface ApiFailure {
  code: string
  message: string
  detail?: unknown
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(API + path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init.headers || {}) },
  })
  const text = await response.text()
  let body: unknown = null
  try { body = text ? JSON.parse(text) : null } catch { body = text }
  if (!response.ok) {
    const failure = body as ApiFailure | null
    const detail = failure?.detail ? ` · ${JSON.stringify(failure.detail).slice(0, 300)}` : ''
    throw new Error((failure?.message || `HTTP ${response.status}`) + detail)
  }
  return body as T
}

const json = (value: unknown) => JSON.stringify(value ?? {})

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown = {}) => request<T>(path, { method: 'POST', body: json(body) }),
  put: <T>(path: string, body: unknown = {}) => request<T>(path, { method: 'PUT', body: json(body) }),
  patch: <T>(path: string, body: unknown = {}) => request<T>(path, { method: 'PATCH', body: json(body) }),
  del: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}

export const fileUrl = (pid: string, path: string, download = false) =>
  `${API}/files?pid=${encodeURIComponent(pid)}&path=${encodeURIComponent(path)}${download ? '&download=1' : ''}`

export const reportUrl = (id: string, format: 'html' | 'pdf' | 'json' | 'md', download = false) =>
  `${API}/reports/${id}/export?format=${format}${download ? '&download=1' : ''}`

export const wsUrl = () => {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${location.host}/ws`
}

export const qs = (params: Record<string, string | number | boolean | undefined | null>) => {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  })
  const text = search.toString()
  return text ? `?${text}` : ''
}
