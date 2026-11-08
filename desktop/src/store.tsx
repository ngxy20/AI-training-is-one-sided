import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { api, wsUrl } from './api'
import { applyTheme } from './theme'
import type { ThemeState } from './theme'
import type { Command, DialogCommand, Job, LogLine, Project, Tab, Toast, TreeGroup } from './types'

interface AppState {
  projects: Project[]
  activeProject: Project | null
  tree: TreeGroup[]
  tabs: Tab[]
  activeTabId: string | null
  jobs: Job[]
  logs: LogLine[]
  paletteOpen: boolean
  dialog: DialogCommand | null
  toast: Toast | null
  bottomTab: string
  rightTab: string
  bottomHeight: number
  revision: number
  connected: boolean
  settings: Record<string, unknown>
  search: string
  themeName: string
}

interface AppContextValue extends AppState {
  patch: (value: Partial<AppState>) => void
  notify: (text: string, tone?: Toast['tone']) => void
  refreshProjects: () => Promise<void>
  switchProject: (id: string) => Promise<void>
  refreshTree: () => Promise<void>
  refreshJobs: () => Promise<void>
  openTab: (tab: Omit<Tab, 'id'>) => void
  closeTab: (id: string) => void
  activateTab: (id: string) => void
  updateTab: (id: string, value: Partial<Tab>) => void
  openDialog: (dialog: DialogCommand) => void
  runCommand: (command: Command) => Promise<void>
  bump: () => void
  reloadTheme: () => Promise<void>
  themeName: string
}

const AppContext = createContext<AppContextValue | null>(null)

const initial: AppState = {
  projects: [], activeProject: null, tree: [], tabs: [
    { id: 'welcome', title: '欢迎', kind: 'welcome', meta: {} },
  ],
  activeTabId: 'welcome', jobs: [], logs: [], paletteOpen: false, dialog: null,
  toast: null, bottomTab: '日志', rightTab: '属性', bottomHeight: 200,
  revision: 0, connected: false, settings: {}, search: '', themeName: '深色默认',
}

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AppState>(initial)
  const stateRef = useRef(state)
  stateRef.current = state

  const patch = useCallback((value: Partial<AppState>) => setState((prev) => ({ ...prev, ...value })), [])
  const bump = useCallback(() => setState((prev) => ({ ...prev, revision: prev.revision + 1 })), [])

  const notify = useCallback((text: string, tone: Toast['tone'] = 'info') => {
    setState((prev) => ({ ...prev, toast: { text, tone } }))
    window.setTimeout(() => setState((prev) => (prev.toast?.text === text ? { ...prev, toast: null } : prev)), 4200)
  }, [])

  const refreshProjects = useCallback(async () => {
    const projects = await api.get<Project[]>('/projects')
    const settings = await api.get<Record<string, unknown>>('/settings').catch(() => ({} as Record<string, unknown>))
    const activeId = (settings.active_project_id as string) || projects[0]?.id || null
    const activeProject = projects.find((p) => p.id === activeId) || null
    setState((prev) => ({ ...prev, projects, settings, activeProject }))
  }, [])

  const refreshTree = useCallback(async () => {
    const pid = stateRef.current.activeProject?.id
    if (!pid) { setState((prev) => ({ ...prev, tree: [] })); return }
    const tree = await api.get<{ groups: TreeGroup[] }>(`/projects/${pid}/tree`)
    setState((prev) => ({ ...prev, tree: tree.groups }))
  }, [])

  const refreshJobs = useCallback(async () => {
    const pid = stateRef.current.activeProject?.id
    if (!pid) return
    const result = await api.get<{ items: Job[] }>(`/jobs?pid=${pid}&size=50`)
    setState((prev) => ({ ...prev, jobs: result.items }))
  }, [])

  const switchProject = useCallback(async (id: string) => {
    await api.post(`/projects/${id}/open`)
    const projects = await api.get<Project[]>('/projects')
    const activeProject = projects.find((p) => p.id === id) || null
    setState((prev) => ({
      ...prev, projects, activeProject,
      tabs: [{ id: 'welcome', title: '欢迎', kind: 'welcome' }], activeTabId: 'welcome', logs: [],
    }))
    await refreshTree()
    await refreshJobs()
  }, [refreshTree, refreshJobs])

  const openTab = useCallback((tab: Omit<Tab, 'id'>) => {
    const id = `${tab.kind}:${tab.resourceId || tab.title}`
    setState((prev) => {
      const exists = prev.tabs.some((t) => t.id === id)
      return {
        ...prev,
        tabs: exists ? prev.tabs.map((t) => (t.id === id ? { ...t, ...tab } : t)) : [...prev.tabs, { ...tab, id }],
        activeTabId: id,
      }
    })
  }, [])

  const closeTab = useCallback((id: string) => {
    setState((prev) => {
      const tabs = prev.tabs.filter((t) => t.id !== id)
      return { ...prev, tabs, activeTabId: prev.activeTabId === id ? (tabs.at(-1)?.id || null) : prev.activeTabId }
    })
  }, [])

  const activateTab = useCallback((id: string) => setState((prev) => ({ ...prev, activeTabId: id })), [])
  const updateTab = useCallback((id: string, value: Partial<Tab>) => setState((prev) => ({
    ...prev, tabs: prev.tabs.map((t) => (t.id === id ? { ...t, ...value } : t)),
  })), [])
  const openDialog = useCallback((dialog: DialogCommand) => setState((prev) => ({ ...prev, dialog, paletteOpen: false })), [])
  const reloadTheme = useCallback(async () => {
    try {
      const theme = await api.get<ThemeState>('/themes')
      applyTheme(theme.tokens)
      const active = [...theme.presets, ...theme.custom].find((t) => t.id === theme.active_id)
      setState((prev) => ({ ...prev, themeName: active?.name || '深色默认' }))
    } catch { /* offline first paint: keep CSS defaults */ }
  }, [])

  const runCommand = useCallback(async (command: Command) => {
    const pid = stateRef.current.activeProject?.id
    if (command.needsProject !== false && !pid && command.action !== 'tab') {
      notify('请先创建或切换项目', 'error')
      return
    }
    if (command.action === 'dialog' && command.dialog) {
      openDialog(command.dialog)
    } else if (command.action === 'tab' && command.tab) {
      openTab(command.tab)
    } else if (command.action === 'palette') {
      setState((prev) => ({ ...prev, paletteOpen: true }))
    } else if (command.action === 'run' && command.run) {
      try {
        await command.run({
          pid, notify, openTab, bump, refreshTree, refreshJobs, refreshProjects,
          switchProject, patch, openDialog, reloadTheme, state: stateRef.current,
        })
      } catch (error) {
        notify((error as Error).message, 'error')
      }
    }
    setState((prev) => ({ ...prev, paletteOpen: false }))
  }, [notify, openTab, openDialog, bump, refreshTree, refreshJobs, refreshProjects, switchProject, patch, reloadTheme])

  useEffect(() => {
    refreshProjects().then(async () => {
      try {
        const settings = await api.get<Record<string, unknown>>('/settings')
        let pid = settings.active_project_id as string | undefined
        if (!pid) {
          const projects = await api.get<Project[]>('/projects')
          if (!projects.length) {
            const created = await api.post<Project>('/projects', { name: '默认项目', description: '首次启动自动创建' })
            pid = created.id
            await api.post(`/projects/${pid}/open`)
          } else pid = projects[0].id
        }
        await switchProject(pid)
        await reloadTheme()
        setState((prev) => ({ ...prev, settings }))
      } catch (error) { notify((error as Error).message, 'error') }
    }).catch((error) => notify((error as Error).message, 'error'))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let socket: WebSocket | null = null
    let retry = 0
    const connect = () => {
      try {
        socket = new WebSocket(wsUrl())
        socket.onopen = () => { retry = 0; setState((prev) => ({ ...prev, connected: true })) }
        socket.onclose = () => {
          setState((prev) => ({ ...prev, connected: false }))
          retry = Math.min(retry + 1, 6)
          window.setTimeout(connect, 800 * retry)
        }
        socket.onmessage = (event) => {
          let message: { type: string; payload?: Record<string, unknown>; ts?: string }
          try { message = JSON.parse(event.data) } catch { return }
          const payload = message.payload || {}
          if (message.type === 'job.log') {
            const line: LogLine = { jobId: String(payload.job_id || ''), line: String(payload.line || ''), ts: message.ts || '' }
            setState((prev) => ({ ...prev, logs: [...prev.logs.slice(-3000), line] }))
          } else if (message.type === 'job.status' || message.type === 'job.progress') {
            refreshJobs().catch(() => undefined)
            bump()
          } else if (message.type === 'resource.changed' || message.type === 'audit.created') {
            refreshTree().catch(() => undefined)
            bump()
          }
        }
      } catch { setState((prev) => ({ ...prev, connected: false })) }
    }
    connect()
    return () => socket?.close()
  }, [refreshJobs, refreshTree, bump])

  const value = useMemo<AppContextValue>(() => ({
    ...state, patch, notify, refreshProjects, switchProject, refreshTree, refreshJobs,
    openTab, closeTab, activateTab, updateTab, openDialog, runCommand, bump, reloadTheme,
  }), [state, patch, notify, refreshProjects, switchProject, refreshTree, refreshJobs,
    openTab, closeTab, activateTab, updateTab, openDialog, runCommand, bump, reloadTheme])

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export function useApp(): AppContextValue {
  const context = useContext(AppContext)
  if (!context) throw new Error('useApp 必须在 AppProvider 内使用')
  return context
}
