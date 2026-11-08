import type { Tab, TabKind, TreeItem } from './types'

const MAP: Record<string, { kind: TabKind; prefix: string }> = {
  datasource: { kind: 'sql', prefix: 'SQL' },
  dataset: { kind: 'dataset', prefix: '数据集' },
  pipeline: { kind: 'pipeline', prefix: '清洗' },
  annotation: { kind: 'annotation', prefix: '标注' },
  annotation_schema: { kind: 'json', prefix: '模板' },
  script: { kind: 'code', prefix: '脚本' },
  config: { kind: 'config', prefix: '配置' },
  model: { kind: 'model', prefix: '模型' },
  run: { kind: 'run', prefix: '实验' },
  eval_suite: { kind: 'eval', prefix: '套件' },
  eval_run: { kind: 'evalrun', prefix: '评测' },
  ab_test: { kind: 'json', prefix: 'A/B' },
  report: { kind: 'report', prefix: '报告' },
}

export function tabForItem(item: TreeItem, pid: string): Omit<Tab, 'id'> {
  const target = MAP[item.kind] || { kind: 'json' as TabKind, prefix: '资源' }
  const meta: Record<string, unknown> = { item }
  if (item.kind === 'ab_test') meta.endpoint = `/ab-tests/${item.id}`
  return {
    title: `${target.prefix} · ${item.name}`,
    kind: target.kind,
    projectId: pid,
    resourceId: item.id,
    meta,
  }
}

export const GROUP_ORDER = [
  'datasource', 'dataset', 'pipeline', 'annotation', 'annotation_schema', 'script',
  'config', 'model', 'run', 'eval_suite', 'eval_run', 'ab_test', 'report',
]
