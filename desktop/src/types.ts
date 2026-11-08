export interface Project {
  id: string
  name: string
  description?: string
  workspace_path: string
  status: string
  settings_json?: Record<string, unknown>
  counts?: Record<string, number>
}

export interface TreeItem {
  id: string
  name: string
  uri: string
  kind: string
  status?: string | null
  version?: number | null
  updated_at?: string
}

export interface TreeGroup {
  key: string
  label: string
  count: number
  items: TreeItem[]
}

export type TabKind =
  | 'welcome' | 'code' | 'sql' | 'dataset' | 'records' | 'pipeline'
  | 'annotation' | 'config' | 'run' | 'eval' | 'evalrun' | 'report'
  | 'settings' | 'plugins' | 'lineage' | 'dashboard' | 'audit' | 'search' | 'json'
  | 'registry' | 'model' | 'finetune' | 'agent'
  | 'theme' | 'models' | 'schedules' | 'members'

export interface Tab {
  id: string
  title: string
  kind: TabKind
  projectId?: string
  resourceId?: string
  meta?: Record<string, unknown>
  dirty?: boolean
}

export interface Job {
  id: string
  type: string
  status: string
  runner_type?: string
  progress?: number
  error?: string
  started_at?: string
  finished_at?: string
  payload_json?: Record<string, unknown>
}

export interface LogLine {
  jobId: string
  line: string
  ts: string
}

export interface FieldSpec {
  key: string
  label: string
  type: 'text' | 'number' | 'textarea' | 'json' | 'select' | 'checkbox' | 'path'
  placeholder?: string
  default?: unknown
  options?: { label: string; value: string }[]
  optionsFrom?: { endpoint: string; label: string; value: string }
  required?: boolean
  help?: string
}

export interface DialogCommand {
  id: string
  title: string
  description?: string
  fields: FieldSpec[]
  endpoint: string | ((values: Record<string, unknown>, ctx: Record<string, unknown>) => string)
  method?: 'POST' | 'PUT' | 'PATCH'
  payload?: (values: Record<string, unknown>, ctx: Record<string, unknown>) => unknown
  onDone?: (result: unknown, ctx: Record<string, unknown>) => void | Promise<void>
  needsProject?: boolean
  submitLabel?: string
}

export interface Command {
  id: string
  title: string
  group: string
  shortcut?: string
  needsProject?: boolean
  action: 'dialog' | 'tab' | 'run' | 'palette'
  dialog?: DialogCommand
  tab?: Omit<Tab, 'id'>
  run?: (ctx: Record<string, unknown>) => void | Promise<void>
}

export interface Toast {
  text: string
  tone: 'info' | 'success' | 'error'
}

declare global {
  interface Window {
    aixianDesktop?: {
      openPath: (options?: { folder?: boolean }) => Promise<string | null>
      info: () => Promise<{ platform: string; version: string; port: number; dev: boolean }>
      openExternal: (url: string) => Promise<void>
      isDesktop: boolean
    }
  }
}
