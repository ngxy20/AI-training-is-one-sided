import { useEffect, useMemo, useRef, useState } from 'react'
import { buildCommands } from '../commands'
import { useApp } from '../store'

export function CommandPalette() {
  const app = useApp()
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const commands = useMemo(() => buildCommands(app.activeProject?.id || ''), [app.activeProject?.id])

  useEffect(() => {
    if (app.paletteOpen) { setQuery(''); setActive(0); window.setTimeout(() => inputRef.current?.focus(), 20) }
  }, [app.paletteOpen])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return q ? commands.filter((c) => `${c.title} ${c.group} ${c.id}`.toLowerCase().includes(q)) : commands
  }, [commands, query])

  if (!app.paletteOpen) return null

  const choose = (index: number) => {
    const command = filtered[index]
    if (command) void app.runCommand(command)
  }

  return <div className="overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) app.patch({ paletteOpen: false }) }}>
    <div className="palette">
      <input ref={inputRef} value={query} placeholder="输入命令，例如：新建数据集 / 运行训练 / 生成报告"
        onChange={(e) => { setQuery(e.target.value); setActive(0) }}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, filtered.length - 1)) }
          else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
          else if (e.key === 'Enter') { e.preventDefault(); choose(active) }
          else if (e.key === 'Escape') app.patch({ paletteOpen: false })
        }} />
      <div className="palette-list">
        {filtered.map((command, index) => <div key={command.id}
          className={`palette-item ${index === active ? 'active' : ''}`}
          onMouseEnter={() => setActive(index)} onClick={() => choose(index)}>
          <span className="pill info">{command.group}</span>
          <span>{command.title}</span>
          {command.shortcut && <span className="kbd" style={{ marginLeft: 'auto' }}>{command.shortcut}</span>}
          {!command.shortcut && <span className="group">{command.id}</span>}
        </div>)}
        {!filtered.length && <div className="tree-empty">没有匹配的命令</div>}
      </div>
      <div className="palette-foot">↑↓ 选择 · Enter 执行 · Esc 关闭 · Ctrl+Shift+P 打开</div>
    </div>
  </div>
}
