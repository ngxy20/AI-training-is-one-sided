import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../api'
import { applyTheme, normalizeHex, PREVIEW_SNIPPET, TOKEN_GROUPS, tokensForSave } from '../../theme'
import type { ThemePreset, ThemeState, ThemeTokens } from '../../theme'
import { useApp } from '../../store'

const GROUP_ORDER = ['基础', '文本与状态', '编辑器', '语法高亮']

export function ThemeView() {
  const app = useApp()
  const [data, setData] = useState<ThemeState | null>(null)
  const [draft, setDraft] = useState<ThemeTokens>({})
  const [selectedId, setSelectedId] = useState('dark')
  const [name, setName] = useState('我的主题')
  const [advanced, setAdvanced] = useState(false)
  const [rawJson, setRawJson] = useState('')
  const [dirty, setDirty] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const reload = useCallback(async (apply = false) => {
    const result = await api.get<ThemeState>('/themes')
    setData(result)
    setSelectedId(result.active_id)
    const active = [...result.presets, ...result.custom].find((t) => t.id === result.active_id)
    setName(active && !active.builtin ? active.name : '我的主题')
    setDraft({ ...result.tokens })
    setRawJson(JSON.stringify(result.tokens, null, 2))
    setDirty(false)
    if (apply) applyTheme(result.tokens)
  }, [])

  useEffect(() => { void reload(true).catch((e: Error) => app.notify(e.message, 'error')) }, [reload])

  const allThemes = useMemo<ThemePreset[]>(
    () => data ? [...data.presets, ...data.custom] : [], [data])

  const changeToken = (key: string, value: string) => {
    const color = normalizeHex(value)
    if (!color) return
    const next = { ...draft, [key]: color }
    setDraft(next)
    setRawJson(JSON.stringify(next, null, 2))
    setDirty(true)
    applyTheme(next)
  }

  const editRaw = (text: string) => {
    setRawJson(text)
    try {
      const parsed = JSON.parse(text) as ThemeTokens
      if (parsed && typeof parsed === 'object') {
        const next = { ...draft }
        Object.entries(parsed).forEach(([key, value]) => {
          const color = normalizeHex(String(value))
          if (color) next[key] = color
        })
        setDraft(next)
        setDirty(true)
        applyTheme(next)
      }
    } catch { /* invalid JSON while typing: keep last valid draft */ }
  }

  const activate = async (theme: ThemePreset) => {
    try {
      await api.put('/themes/active', { id: theme.id, tokens: {} })
      setSelectedId(theme.id)
      setName(theme.builtin ? '我的主题' : theme.name)
      setDraft({ ...theme.tokens })
      setRawJson(JSON.stringify(theme.tokens, null, 2))
      setDirty(false)
      applyTheme(theme.tokens)
      app.notify(`已切换到「${theme.name}」`, 'success')
      await reload()
    } catch (e) { app.notify((e as Error).message, 'error') }
  }

  const save = async (overwrite: boolean) => {
    try {
      const payload: Record<string, unknown> = { name: name || '我的主题', tokens: tokensForSave(draft) }
      if (overwrite && selectedId.startsWith('custom-')) payload.id = selectedId
      await api.post('/themes', payload)
      app.notify(overwrite ? '主题已覆盖保存' : '已保存为新主题', 'success')
      await reload()
    } catch (e) { app.notify((e as Error).message, 'error') }
  }

  const persistOnly = async () => {
    try {
      await api.put('/themes/tokens', { tokens: tokensForSave(draft) })
      setDirty(false)
      app.notify('配色已应用并持久化（未命名）', 'success')
      await reload()
    } catch (e) { app.notify((e as Error).message, 'error') }
  }

  const reset = () => {
    const theme = allThemes.find((t) => t.id === selectedId)
    if (!theme) return
    setDraft({ ...theme.tokens })
    setRawJson(JSON.stringify(theme.tokens, null, 2))
    setDirty(false)
    applyTheme(theme.tokens)
  }

  const exportJson = () => {
    const blob = new Blob([JSON.stringify({ format: 'aixian-theme/1', name, tokens: tokensForSave(draft) }, null, 2)],
      { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${name || 'theme'}.json`
    link.click()
    URL.revokeObjectURL(url)
  }

  const importJson = async (file: File) => {
    try {
      const parsed = JSON.parse(await file.text())
      await api.post('/themes/import', { theme: parsed })
      app.notify('主题已导入并激活', 'success')
      await reload(true)
    } catch (e) { app.notify((e as Error).message, 'error') }
  }

  const remove = async () => {
    if (!selectedId.startsWith('custom-')) return
    try {
      await api.del(`/themes/${selectedId}`)
      app.notify('自定义主题已删除', 'success')
      await reload(true)
    } catch (e) { app.notify((e as Error).message, 'error') }
  }

  const visibleGroups = GROUP_ORDER.map((group) => ({
    group,
    items: TOKEN_GROUPS.filter((d) => d.group === group && (advanced || !d.advanced)),
  })).filter((g) => g.items.length)

  return <div className="theme-editor">
    <div className="editor-toolbar">
      <strong>主题编辑器</strong>
      <span className="pill info">{dirty ? '未保存' : '已同步'}</span>
      <input value={name} onChange={(e) => setName(e.target.value)} style={{ width: 150 }} placeholder="主题名称" />
      <button className={`btn sm ${advanced ? 'primary' : ''}`} onClick={() => setAdvanced((v) => !v)}>
        {advanced ? '高级：开' : '高级：关'}
      </button>
      <div style={{ flex: 1 }} />
      <button className="btn sm" onClick={reset}>重置</button>
      <button className="btn sm" onClick={() => fileRef.current?.click()}>导入 JSON</button>
      <button className="btn sm" onClick={exportJson}>导出 JSON</button>
      <input ref={fileRef} type="file" accept="application/json,.json" className="hidden"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) void importJson(f); e.target.value = '' }} />
      {selectedId.startsWith('custom-') && <button className="btn sm danger" onClick={() => void remove()}>删除</button>}
      <button className="btn sm" onClick={() => void persistOnly()}>仅应用</button>
      {selectedId.startsWith('custom-') && <button className="btn sm" onClick={() => void save(true)}>覆盖保存</button>}
      <button className="btn sm primary" onClick={() => void save(false)}>另存为新主题</button>
    </div>

    <div className="theme-body">
      <aside className="theme-presets">
        <div className="panel-head"><span>预设与自定义</span><span>{allThemes.length}</span></div>
        <div className="theme-preset-list">
          {allThemes.map((theme) => <button key={theme.id}
            className={`theme-preset ${theme.id === selectedId ? 'active' : ''}`}
            onClick={() => void activate(theme)}>
            <span className="theme-swatches">
              <i style={{ background: theme.tokens.bg }} />
              <i style={{ background: theme.tokens.panel }} />
              <i style={{ background: theme.tokens.accent }} />
              <i style={{ background: theme.tokens.green }} />
            </span>
            <span className="theme-preset-name">{theme.name}</span>
            {theme.builtin ? <span className="pill">内置</span> : <span className="pill info">自定义</span>}
          </button>)}
        </div>
        <p className="small dim" style={{ padding: '8px 12px' }}>
          点击预设立即切换；修改右侧色值会实时应用到整个工作台与 Monaco 编辑器。
        </p>
      </aside>

      <section className="theme-tokens">
        <div className="panel-head"><span>颜色 Token{advanced ? '（含高级）' : '（基础）'}</span>
          <span>{TOKEN_GROUPS.filter((d) => advanced || !d.advanced).length} 项</span></div>
        <div className="theme-token-scroll">
          {visibleGroups.map(({ group, items }) => <div className="section" key={group}>
            <h3>{group}</h3>
            {items.map((def) => <div className="theme-token-row" key={def.key}>
              <div className="theme-token-label"><span>{def.label}</span>
                <span className="mono small dim">{def.key}</span></div>
              <input type="color" value={normalizeHex(draft[def.key] || '#000000') || '#000000'}
                onChange={(e) => changeToken(def.key, e.target.value)} />
              <input className="mono theme-hex" value={draft[def.key] || ''}
                onChange={(e) => changeToken(def.key, e.target.value)} />
              {def.hint && <span className="small dim theme-hint">{def.hint}</span>}
            </div>)}
          </div>)}
          {advanced && <div className="section">
            <h3>原始 JSON（可直接编辑）</h3>
            <textarea className="mono" spellCheck={false} style={{ width: '100%', minHeight: 180 }}
              value={rawJson} onChange={(e) => editRaw(e.target.value)} />
            <p className="small dim">仅接受 <code>#rgb</code> / <code>#rrggbb</code> / <code>#rrggbbaa</code> 颜色值。</p>
          </div>}
        </div>
      </section>

      <aside className="theme-preview">
        <div className="panel-head"><span>实时预览</span><span>{draft.bg}</span></div>
        <div className="theme-mini">
          <div className="theme-mini-bar">
            <span className="theme-mini-dot" /><b>AI 训练工作台</b>
            <span className="small dim" style={{ marginLeft: 'auto' }}>命令面板 · 设置</span>
          </div>
          <div className="theme-mini-main">
            <div className="theme-mini-tree">
              <div>▾ 数据源</div><div>▾ 数据集</div><div>▸ 清洗 Pipeline</div>
              <div>▸ 标注任务</div><div>▸ 训练配置</div><div>▸ 实验</div>
              <div>▸ 报告</div>
            </div>
            <div className="theme-mini-code">
              <div className="theme-mini-tab">train.py ×</div>
              <pre>{PREVIEW_SNIPPET.map((part, i) => <span key={i}
                style={{ color: part.token ? draft[part.token] : undefined }}>{part.text}</span>)}</pre>
            </div>
          </div>
          <div className="theme-mini-bottom"><span className="pill ok">任务成功</span>
            <span className="small dim">日志 · 终端 · 问题 · 审计</span></div>
        </div>
        <div className="theme-preview-note small dim">
          基础色、面板色、文本色、状态色与语法高亮均来自当前 Token 集合。切换到「高级」可编辑语法高亮与编辑器细节。
        </div>
      </aside>
    </div>
  </div>
}
