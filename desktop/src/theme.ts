import * as monaco from 'monaco-editor'

export interface ThemeTokens { [key: string]: string }

export interface ThemePreset {
  id: string
  name: string
  builtin: boolean
  tokens: ThemeTokens
}

export interface ThemeState {
  presets: ThemePreset[]
  custom: ThemePreset[]
  active_id: string
  tokens: ThemeTokens
  token_keys: string[]
}

export interface TokenDef {
  key: string
  label: string
  group: string
  advanced?: boolean
  hint?: string
}

export const TOKEN_GROUPS: TokenDef[] = [
  { key: 'bg', label: '主背景', group: '基础', hint: '整个工作台底色' },
  { key: 'panel', label: '侧栏 / 顶栏', group: '基础' },
  { key: 'panel2', label: '输入框 / 次级面板', group: '基础' },
  { key: 'panel3', label: '按钮 / 浮层', group: '基础' },
  { key: 'line', label: '分隔线', group: '基础' },
  { key: 'borderSoft', label: '表格细线', group: '基础' },
  { key: 'text', label: '主文本', group: '文本与状态' },
  { key: 'muted', label: '次级文本', group: '文本与状态' },
  { key: 'dim', label: '弱化文本', group: '文本与状态' },
  { key: 'accent', label: '强调色', group: '文本与状态', hint: '选中态、主按钮、链接' },
  { key: 'accentSoft', label: '强调色底色', group: '文本与状态' },
  { key: 'green', label: '成功', group: '文本与状态' },
  { key: 'amber', label: '警告', group: '文本与状态' },
  { key: 'red', label: '错误', group: '文本与状态' },
  { key: 'cyan', label: '信息', group: '文本与状态' },
  { key: 'scrollbar', label: '滚动条', group: '基础', advanced: true },
  { key: 'rowHover', label: '表格悬停', group: '基础', advanced: true },
  { key: 'codeBg', label: 'JSON / 日志背景', group: '编辑器', advanced: true },
  { key: 'editorBg', label: '编辑器背景', group: '编辑器', advanced: true },
  { key: 'editorLine', label: '当前行高亮', group: '编辑器', advanced: true },
  { key: 'selection', label: '选区', group: '编辑器', advanced: true },
  { key: 'cursor', label: '光标', group: '编辑器', advanced: true },
  { key: 'synKeyword', label: '关键字', group: '语法高亮', advanced: true },
  { key: 'synString', label: '字符串', group: '语法高亮', advanced: true },
  { key: 'synNumber', label: '数字', group: '语法高亮', advanced: true },
  { key: 'synComment', label: '注释', group: '语法高亮', advanced: true },
  { key: 'synFunction', label: '函数', group: '语法高亮', advanced: true },
  { key: 'synVariable', label: '变量 / 标识符', group: '语法高亮', advanced: true },
  { key: 'synType', label: '类型', group: '语法高亮', advanced: true },
  { key: 'synOperator', label: '运算符', group: '语法高亮', advanced: true },
]

export const CSS_VARS: Record<string, string> = {
  bg: '--bg', panel: '--panel', panel2: '--panel-2', panel3: '--panel-3',
  line: '--line', borderSoft: '--border-soft', text: '--text', muted: '--muted', dim: '--dim',
  accent: '--accent', accentSoft: '--accent-soft', green: '--green', amber: '--amber',
  red: '--red', cyan: '--cyan', scrollbar: '--scrollbar', rowHover: '--row-hover',
  codeBg: '--code-bg', selection: '--selection', editorBg: '--editor-bg',
  editorLine: '--editor-line', cursor: '--cursor',
}

export const PREVIEW_SNIPPET: { text: string; token: string }[] = [
  { text: 'from ', token: 'synKeyword' },
  { text: 'aixian', token: 'synVariable' },
  { text: ' import ', token: 'synKeyword' },
  { text: 'Dataset', token: 'synType' },
  { text: '\n\n', token: '' },
  { text: '# 建立不可变数据集版本\n', token: 'synComment' },
  { text: 'version', token: 'synFunction' },
  { text: ' = ', token: 'synOperator' },
  { text: 'create', token: 'synFunction' },
  { text: '(', token: 'synOperator' },
  { text: 'records', token: 'synVariable' },
  { text: ', ', token: 'synOperator' },
  { text: '42', token: 'synNumber' },
  { text: ')\n', token: 'synOperator' },
  { text: 'print', token: 'synFunction' },
  { text: '(', token: 'synOperator' },
  { text: '"训练样本已就绪"', token: 'synString' },
  { text: ')', token: 'synOperator' },
]

export function normalizeHex(value: string): string {
  const text = value.trim().toLowerCase()
  if (/^#[0-9a-f]{3}$/.test(text)) {
    return '#' + text.slice(1).split('').map((c) => c + c).join('')
  }
  if (/^#[0-9a-f]{6}$/.test(text)) return text
  if (/^#[0-9a-f]{8}$/.test(text)) return text.slice(0, 7)
  return ''
}

function luminance(hex: string): number {
  const value = normalizeHex(hex) || '#0d1117'
  const r = parseInt(value.slice(1, 3), 16) / 255
  const g = parseInt(value.slice(3, 5), 16) / 255
  const b = parseInt(value.slice(5, 7), 16) / 255
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

export function isLightTheme(tokens: ThemeTokens): boolean {
  return luminance(tokens.bg || '#0d1117') > 0.55
}

export function applyTheme(tokens: ThemeTokens): void {
  const root = document.documentElement
  Object.entries(CSS_VARS).forEach(([key, cssVar]) => {
    const color = normalizeHex(tokens[key] || '')
    if (color) root.style.setProperty(cssVar, color)
  })
  root.style.colorScheme = isLightTheme(tokens) ? 'light' : 'dark'

  const light = isLightTheme(tokens)
  const hex = (key: string, fallback: string) => (normalizeHex(tokens[key] || '') || fallback).slice(1, 7)
  try {
    monaco.editor.defineTheme('aixian-custom', {
      base: light ? 'vs' : 'vs-dark',
      inherit: true,
      rules: [
        { token: 'keyword', foreground: hex('synKeyword', 'c792ea') },
        { token: 'string', foreground: hex('synString', 'c3e88d') },
        { token: 'number', foreground: hex('synNumber', 'f78c6c') },
        { token: 'comment', foreground: hex('synComment', '5f6f85'), fontStyle: 'italic' },
        { token: 'type', foreground: hex('synType', 'ffcb6b') },
        { token: 'identifier', foreground: hex('synVariable', 'dce4f0') },
        { token: 'delimiter', foreground: hex('synOperator', '89ddff') },
      ],
      colors: {
        'editor.background': normalizeHex(tokens.editorBg || '') || '#0d1117',
        'editor.foreground': normalizeHex(tokens.text || '') || '#dce4f0',
        'editorLineNumber.foreground': normalizeHex(tokens.dim || '') || '#5f6f85',
        'editor.lineHighlightBackground': normalizeHex(tokens.editorLine || '') || '#161d29',
        'editor.selectionBackground': normalizeHex(tokens.selection || '') || '#264f78',
        'editorCursor.foreground': normalizeHex(tokens.cursor || '') || '#dce4f0',
      },
    })
    monaco.editor.setTheme('aixian-custom')
  } catch {
    // Monaco may not be initialised yet; CSS theming still applies.
  }
}

export function tokensForSave(tokens: ThemeTokens): ThemeTokens {
  const cleaned: ThemeTokens = {}
  Object.entries(tokens).forEach(([key, value]) => {
    const color = normalizeHex(value)
    if (color) cleaned[key] = color
  })
  return cleaned
}
