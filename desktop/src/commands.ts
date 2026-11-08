import { api } from './api'
import type { Command, DialogCommand, FieldSpec } from './types'

const f = (spec: FieldSpec): FieldSpec => spec
const required = (key: string, label: string, extra: Partial<FieldSpec> = {}): FieldSpec =>
  f({ key, label, type: 'text', required: true, ...extra })

const jsonField = (key: string, label: string, value: unknown, help?: string): FieldSpec =>
  f({ key, label, type: 'json', default: value, help })

const selectFrom = (key: string, label: string, endpoint: string): FieldSpec =>
  f({ key, label, type: 'select', required: true, optionsFrom: { endpoint, label: 'name', value: 'id' } })

export function buildCommands(pid: string): Command[] {
  const versionOptions: FieldSpec = f({
    key: 'version', label: '数据集版本', type: 'select', required: true,
    optionsFrom: { endpoint: `/projects/${pid}/dataset-versions`, label: 'name', value: 'id' },
  })

  const dialog = (command: Omit<Command, 'action'> & { dialog: DialogCommand }): Command => ({ ...command, action: 'dialog' })

  return [
    dialog({
      id: 'project.create', title: '新建项目', group: '项目', shortcut: 'Ctrl+N', needsProject: false,
      dialog: {
        id: 'project.create', title: '新建项目', description: '每个项目拥有独立 workspace 与元数据库',
        fields: [required('name', '项目名称', { placeholder: '例如：客服意图模型 v1' }),
          f({ key: 'description', label: '描述', type: 'textarea' })],
        endpoint: '/projects',
        payload: (v) => ({ name: v.name, description: v.description }),
        onDone: async (result, ctx) => {
          await (ctx.refreshProjects as () => Promise<void>)?.()
          const id = (result as { id: string }).id
          await (ctx.switchProject as (id: string) => Promise<void>)?.(id)
        },
        submitLabel: '创建并打开',
      },
    }),
    dialog({
      id: 'project.switch', title: '切换项目', group: '项目', needsProject: false,
      dialog: {
        id: 'project.switch', title: '切换项目',
        fields: [f({ key: 'project_id', label: '目标项目', type: 'select', required: true,
          optionsFrom: { endpoint: '/projects', label: 'name', value: 'id' } })],
        endpoint: (v) => `/projects/${v.project_id}/open`,
        onDone: async (_result, ctx) => {
          await (ctx.refreshProjects as () => Promise<void>)?.()
          const chosen = (ctx.values as Record<string, unknown>)?.project_id
          if (chosen) await (ctx.switchProject as (id: string) => Promise<void>)(String(chosen))
        },
        submitLabel: '打开',
      },
    }),
    dialog({
      id: 'datasource.create', title: '连接现有数据库', group: '数据',
      dialog: {
        id: 'datasource.create', title: '新建数据源', description: '凭据在 Windows 上使用 DPAPI 加密存储',
        fields: [
          required('name', '名称', { placeholder: '生产库只读账号' }),
          f({ key: 'type', label: '类型', type: 'select', required: true,
            options: [{ label: 'SQLite', value: 'sqlite' }, { label: 'PostgreSQL', value: 'pg' },
              { label: 'MySQL', value: 'mysql' }, { label: '插件数据源', value: 'plugin' }] }),
          jsonField('config', '连接配置（JSON）', { path: 'C:/data/app.db' },
            'sqlite: {path}; pg/mysql: {host, port, user, password, database}'),
          f({ key: 'plugin_id', label: '插件 ID（类型为插件时填写）', type: 'text' }),
        ],
        endpoint: `/projects/${pid}/datasources`,
        payload: (v) => ({ name: v.name, type: v.type, config: v.config, plugin_id: v.plugin_id || undefined }),
      },
    }),
    dialog({
      id: 'dataset.create', title: '新建数据集', group: '数据',
      dialog: {
        id: 'dataset.create', title: '新建数据集',
        fields: [required('name', '名称'), f({ key: 'description', label: '描述', type: 'textarea' })],
        endpoint: `/projects/${pid}/datasets`,
        payload: (v) => ({ name: v.name, description: v.description }),
      },
    }),
    dialog({
      id: 'dataset.import', title: '导入数据集版本', group: '数据',
      dialog: {
        id: 'dataset.import', title: '导入为不可变数据集版本',
        description: '支持 JSONL / JSON / CSV / Parquet / TXT / 目录',
        fields: [
          selectFrom('dataset_id', '目标数据集', `/projects/${pid}/datasets`),
          f({ key: 'path', label: '文件路径', type: 'path', required: true, help: '也可直接粘贴路径' }),
          f({ key: 'fmt', label: '格式', type: 'select', default: 'jsonl',
            options: ['jsonl', 'json', 'csv', 'parquet', 'txt', 'dir'].map((v) => ({ label: v, value: v })) }),
          jsonField('field_mapping', '字段映射（可选）', {}),
          f({ key: 'changelog', label: '变更说明', type: 'text' }),
        ],
        endpoint: (v) => `/datasets/${v.dataset_id}/versions`,
        payload: (v) => ({ path: v.path, fmt: v.fmt, workspace_relative: false,
          field_mapping: v.field_mapping, changelog: v.changelog }),
      },
    }),
    dialog({
      id: 'dataset.export', title: '导出训练格式', group: '数据',
      dialog: {
        id: 'dataset.export', title: '导出数据集版本',
        fields: [versionOptions,
          f({ key: 'format', label: '格式', type: 'select', default: 'alpaca',
            options: ['alpaca', 'sharegpt', 'custom', 'jsonl', 'csv'].map((v) => ({ label: v, value: v })) }),
          jsonField('mapping', '字段映射', { instruction: 'text', output: 'label' }),
          f({ key: 'template', label: '自定义模板', type: 'text', placeholder: '指令：{instruction}\n输出：{output}' }),
        ],
        endpoint: (v) => `/dataset-versions/${v.version}/export`,
        payload: (v) => ({ format: v.format, mapping: v.mapping, template: v.template }),
      },
    }),
    dialog({
      id: 'pipeline.create', title: '新建清洗 Pipeline', group: '数据',
      dialog: {
        id: 'pipeline.create', title: '新建清洗 Pipeline',
        fields: [required('name', '名称'), jsonField('nodes_json', '节点配置', [
          { op: 'strip_whitespace', params: { fields: ['text'] } },
          { op: 'dedup', params: { field: 'text' } },
          { op: 'length_range', params: { field: 'text', min: 1, max: 8192 } },
        ], '可在标签页中运行/编辑；算子目录见右侧面板')],
        endpoint: `/projects/${pid}/pipelines`,
        payload: (v) => ({ name: v.name, nodes_json: v.nodes_json }),
      },
    }),
    dialog({
      id: 'annotationschema.create', title: '新建标注模板', group: '标注',
      dialog: {
        id: 'annotationschema.create', title: '新建标注模板',
        fields: [required('name', '名称'),
          f({ key: 'template_type', label: '模板类型', type: 'select', default: 'classification',
            options: ['classification', 'ner', 'qa', 'summary', 'quality_score', 'preference', 'ab_human'].map((v) => ({ label: v, value: v })) }),
          jsonField('schema_json', '标签体系', { fields: [{ key: 'label', type: 'select', label: '类别', options: ['正向', '负向'], shortcuts: ['1', '2'] }] })],
        endpoint: `/projects/${pid}/annotation-schemas`,
        payload: (v) => ({ name: v.name, template_type: v.template_type, schema_json: v.schema_json }),
      },
    }),
    dialog({
      id: 'annotationtask.create', title: '新建标注任务', group: '标注',
      dialog: {
        id: 'annotationtask.create', title: '新建标注任务',
        fields: [required('name', '名称'), versionOptions,
          selectFrom('schema_id', '标注模板', `/projects/${pid}/annotation-schemas`),
          f({ key: 'assignee', label: '指派给', type: 'text', default: 'local' })],
        endpoint: `/projects/${pid}/annotation-tasks`,
        payload: (v) => ({ name: v.name, dataset_version_id: v.version, schema_id: v.schema_id, assignee: v.assignee }),
      },
    }),
    dialog({
      id: 'script.create', title: '新建脚本', group: '训练',
      dialog: {
        id: 'script.create', title: '新建收集/训练脚本',
        fields: [required('name', '名称'),
          f({ key: 'type', label: '类型', type: 'select', default: 'py',
            options: [{ label: 'Python', value: 'py' }, { label: 'SQL', value: 'sql' }] }),
          f({ key: 'content', label: '初始内容（留空使用模板）', type: 'textarea' })],
        endpoint: `/projects/${pid}/scripts`,
        payload: (v) => ({ name: v.name, type: v.type, content: v.content || undefined }),
      },
    }),
    dialog({
      id: 'config.create', title: '新建训练配置', group: '训练',
      dialog: {
        id: 'config.create', title: '新建训练配置',
        fields: [required('name', '名称'), selectFrom('script_id', '训练脚本', `/projects/${pid}/scripts`),
          f({ key: 'params_yaml', label: '参数 YAML', type: 'textarea', default: 'epochs: 3\nlr: 0.0001\nbatch_size: 8\n' }),
          f({ key: 'runner_type', label: 'Runner', type: 'select', default: 'local',
            options: ['local', 'ssh', 'docker'].map((v) => ({ label: v, value: v })) })],
        endpoint: `/projects/${pid}/configs`,
        payload: (v) => ({ name: v.name, script_id: v.script_id, params_yaml: v.params_yaml, runner_type: v.runner_type }),
      },
    }),
    dialog({
      id: 'run.create', title: '提交训练任务', group: '训练',
      dialog: {
        id: 'run.create', title: '提交训练', description: 'Run 强制关联至少一个 DatasetVersion 与一个 TrainingConfig',
        fields: [required('name', '实验名称', { default: '实验' }),
          selectFrom('config_id', '训练配置', `/projects/${pid}/configs`), versionOptions],
        endpoint: `/projects/${pid}/runs`,
        payload: (v) => ({ name: v.name, config_id: v.config_id, dataset_version_ids: [v.version] }),
      },
    }),
    dialog({
      id: 'suite.create', title: '新建评测套件', group: '评测',
      dialog: {
        id: 'suite.create', title: '新建评测套件',
        fields: [required('name', '名称'),
          f({ key: 'type', label: '类型', type: 'select', default: 'accuracy',
            options: [{ label: '准确性 accuracy', value: 'accuracy' }, { label: '能力边界 boundary', value: 'boundary' }, { label: 'A/B ab', value: 'ab' }] }),
          jsonField('cases_json', '测试用例', [
            { id: 'c1', input: '你好', expected: '你好', output: '你好', category: 'general' },
          ])],
        endpoint: `/projects/${pid}/eval-suites`,
        payload: (v) => ({ name: v.name, type: v.type, cases_json: v.cases_json }),
      },
    }),
    dialog({
      id: 'eval.run', title: '运行评测', group: '评测',
      dialog: {
        id: 'eval.run', title: '运行评测套件',
        fields: [selectFrom('suite_id', '评测套件', `/projects/${pid}/eval-suites`),
          f({ key: 'model_id', label: '或选择已注册模型（优先）', type: 'select',
            optionsFrom: { endpoint: `/projects/${pid}/models`, label: 'name', value: 'id' },
            help: '在「模型注册表」里登记一次路径/端点后，这里下拉即可' }),
          jsonField('model_ref_json', '模型适配器（会自动调用模型生成输出）', {
            type: 'openai', base_url: 'http://127.0.0.1:8000/v1', model: 'default',
            temperature: 0.2, max_tokens: 512, concurrency: 4,
          }, '离线复现可用 {"type":"inline","field":"output"}；类型见「模型适配器」标签页'),
          jsonField('scorer_json', '评分器', { type: 'exact_match' },
            '可选 exact_match / contains / regex / llm_judge / plugin'),
          f({ key: 'dataset_version_id', label: '评测集版本 ID（可选）', type: 'text' })],
        endpoint: (v) => `/eval-suites/${v.suite_id}/runs`,
        payload: (v) => ({ model_id: v.model_id || undefined,
          model_ref_json: v.model_ref_json, scorer_json: v.scorer_json,
          dataset_version_ids: v.dataset_version_id ? [v.dataset_version_id] : [] }),
      },
    }),
    dialog({
      id: 'ab.create', title: '新建 A/B 测试', group: '评测',
      dialog: {
        id: 'ab.create', title: '新建 A/B 测试',
        fields: [required('name', '名称'), required('model_a_ref', '模型 A 引用'), required('model_b_ref', '模型 B 引用'),
          jsonField('prompt_set_json', '提示集与评分', [
            { id: 'p1', output_a: '回答 A', output_b: '回答 B', score_a: 1, score_b: 0, winner: 'a' },
          ])],
        endpoint: `/projects/${pid}/ab-tests`,
        payload: (v) => ({ name: v.name, model_a_ref: v.model_a_ref, model_b_ref: v.model_b_ref, prompt_set_json: v.prompt_set_json }),
      },
    }),
    dialog({
      id: 'ab.generate', title: '自动生成 A/B 对比（调用两个模型）', group: '评测',
      dialog: {
        id: 'ab.generate', title: '自动生成 A/B 对比',
        description: '两个模型分别推理提示集，自动评分后计算胜率与显著性',
        fields: [required('name', '名称', { default: '模型 A/B 自动生成' }),
          f({ key: 'model_a_id', label: '模型 A（注册表，优先）', type: 'select',
            optionsFrom: { endpoint: `/projects/${pid}/models`, label: 'name', value: 'id' } }),
          f({ key: 'model_b_id', label: '模型 B（注册表，优先）', type: 'select',
            optionsFrom: { endpoint: `/projects/${pid}/models`, label: 'name', value: 'id' } }),
          jsonField('model_a_ref', '模型 A 适配器', { type: 'openai', base_url: 'http://127.0.0.1:8000/v1', model: 'model-a' }),
          jsonField('model_b_ref', '模型 B 适配器', { type: 'openai', base_url: 'http://127.0.0.1:8000/v1', model: 'model-b' }),
          jsonField('prompt_set_json', '提示集（只需 input / expected）', [
            { id: 'p1', input: '你好', expected: '你好' },
          ]),
          jsonField('scorer_json', '评分器', { type: 'exact_match' })],
        endpoint: `/projects/${pid}/ab-tests`,
        payload: (v) => ({ name: v.name, generate: true,
          model_a_id: v.model_a_id || undefined, model_b_id: v.model_b_id || undefined,
          model_a_ref: v.model_a_ref, model_b_ref: v.model_b_ref,
          prompt_set_json: v.prompt_set_json, scorer_json: v.scorer_json }),
        submitLabel: '提交对比任务',
      },
    }),
    dialog({
      id: 'report.create', title: '生成报告', group: '报告',
      dialog: {
        id: 'report.create', title: '生成报告', description: '报告必须强关联实体，禁止孤立报告',
        fields: [required('name', '名称'),
          f({ key: 'type', label: '类型', type: 'select', default: 'evaluation',
            options: ['experiment', 'evaluation', 'ab', 'boundary', 'accuracy', 'custom'].map((v) => ({ label: v, value: v })) }),
          jsonField('linked_entities_json', '关联实体', [{ type: 'run', id: '' }], '例：[{"type":"run","id":"..."}]'),
          jsonField('summary_json', '摘要与指标', { metrics: { accuracy: 0 } })],
        endpoint: `/projects/${pid}/reports`,
        payload: (v) => ({ name: v.name, type: v.type, linked_entities_json: v.linked_entities_json, summary_json: v.summary_json }),
      },
    }),
    { id: 'theme.open', title: '主题编辑器（IDE 配色自定义）', group: '外观', action: 'tab', tab: { title: '主题', kind: 'theme' } },
    dialog({
      id: 'schedule.create', title: '新建定时任务', group: '自动化',
      dialog: {
        id: 'schedule.create', title: '新建定时任务', description: '五段 cron：分 时 日 月 周，例如 */5 * * * *',
        fields: [required('name', '名称'),
          f({ key: 'type', label: '类型', type: 'select', default: 'command',
            options: [{ label: '执行本地命令', value: 'command' },
              { label: '运行数据收集脚本', value: 'script.run' },
              { label: '复跑清洗 Pipeline', value: 'pipeline.run' },
              { label: '运行评测套件', value: 'eval.run' }] }),
          required('cron_expr', 'cron 表达式', { default: '*/5 * * * *' }),
          f({ key: 'target_id', label: '目标资源 ID（命令类型可留空）', type: 'text' }),
          jsonField('payload_json', '运行参数', { command: 'echo hello' })],
        endpoint: `/projects/${pid}/schedules`,
        payload: (v) => ({ name: v.name, type: v.type, cron_expr: v.cron_expr,
          target_id: v.target_id, payload_json: v.payload_json }),
      },
    }),
    { id: 'registry.open', title: '模型注册表（添加自己的模型路径）', group: '模型', action: 'tab',
      tab: { title: '模型注册表', kind: 'registry' } },
    { id: 'finetune.open', title: '微调工作台（模板 → 一键提交）', group: '模型', action: 'tab',
      tab: { title: '微调', kind: 'finetune' } },
    { id: 'agent.open', title: 'Agent 编排（目标 → 计划 → 执行）', group: 'Agent', action: 'tab',
      tab: { title: 'Agent 编排', kind: 'agent' } },
    dialog({
      id: 'model.create', title: '注册模型（路径 / 端点）', group: '模型',
      dialog: {
        id: 'model.create', title: '快速注册模型',
        description: '权重留在原处，平台只保存引用。复杂配置可在「模型注册表」标签页里编辑。',
        fields: [required('name', '名称'),
          f({ key: 'kind', label: '类型', type: 'select', default: 'base',
            options: [{ label: '基座模型', value: 'base' }, { label: '微调产物', value: 'finetuned' },
              { label: '推理端点', value: 'endpoint' }, { label: '外部模型', value: 'external' }] }),
          jsonField('ref_json', '引用配置', { type: 'transformers', model: 'D:/models/my-model' },
            '本地权重用 {"type":"transformers","model":"路径"}；OpenAI 兼容服务用 {"type":"openai","base_url":"http://.../v1","model":"名称"}'),
          f({ key: 'description', label: '描述', type: 'text' })],
        endpoint: `/projects/${pid}/models`,
        payload: (v) => ({ name: v.name, kind: v.kind, ref_json: v.ref_json, description: v.description }),
        submitLabel: '注册',
      },
    }),
    dialog({
      id: 'finetune.run', title: '一键提交微调', group: '模型',
      dialog: {
        id: 'finetune.run', title: '一键提交微调', description: '模板 + 基座模型 + 自己的脚本 + 数据集版本，产物自动登记回注册表',
        fields: [required('name', '实验名称', { default: '微调实验' }),
          { key: 'template_id', label: '微调模板', type: 'select', required: true, default: 'builtin:lora',
            optionsFrom: { endpoint: `/projects/${pid}/finetune-templates`, label: 'name', value: 'id' } },
          { key: 'base_model_id', label: '基座模型（可选）', type: 'select',
            optionsFrom: { endpoint: `/projects/${pid}/models`, label: 'name', value: 'id' } },
          selectFrom('script_id', '训练脚本', `/projects/${pid}/scripts`),
          { key: 'version', label: '数据集版本', type: 'select', required: true,
            optionsFrom: { endpoint: `/projects/${pid}/dataset-versions`, label: 'name', value: 'id' } },
          jsonField('params', '微调参数覆盖（可选）', {})],
        endpoint: `/projects/${pid}/finetune-runs`,
        payload: (v) => ({ name: v.name, template_id: v.template_id,
          base_model_id: v.base_model_id || undefined, script_id: v.script_id,
          dataset_version_ids: [v.version], params: v.params }),
        submitLabel: '提交',
      },
    }),
    { id: 'models.open', title: '模型推理适配器', group: '系统', action: 'tab', tab: { title: '模型适配器', kind: 'models' } },
    { id: 'schedules.open', title: '定时任务', group: '自动化', action: 'tab', tab: { title: '定时任务', kind: 'schedules' } },
    { id: 'members.open', title: '成员与权限', group: '协作', action: 'tab', tab: { title: '成员与权限', kind: 'members' } },
    { id: 'plugins.manage', title: '插件管理', group: '系统', action: 'tab', tab: { title: '插件', kind: 'plugins' } },
    { id: 'plugins.scan', title: '扫描插件', group: '系统', action: 'run', run: async (ctx) => {
      const result = await api.post<{ scanned: number }>(`/plugins/scan?pid=${ctx.pid}`)
      ;(ctx.notify as (s: string, t?: string) => void)(`发现 ${result.scanned} 个插件`, 'success')
      ;(ctx.bump as () => void)()
    } },
    { id: 'settings.open', title: '打开设置', group: '系统', action: 'tab', tab: { title: '设置', kind: 'settings' } },
    { id: 'lineage.open', title: '资产版本与引用关系图', group: '系统', action: 'tab', tab: { title: '血缘图', kind: 'lineage' } },
    { id: 'dashboard.open', title: '指标看板', group: '系统', action: 'tab', tab: { title: '指标看板', kind: 'dashboard' } },
    { id: 'audit.open', title: '审计事件', group: '系统', action: 'tab', tab: { title: '审计', kind: 'audit' } },
    { id: 'search.focus', title: '全局搜索', group: '系统', action: 'run', run: () => {
      document.getElementById('global-search')?.focus()
    } },
    { id: 'tree.refresh', title: '刷新资源树', group: '系统', action: 'run', run: async (ctx) => {
      await (ctx.refreshTree as () => Promise<void>)()
      ;(ctx.notify as (s: string) => void)('资源树已刷新')
    } },
  ]
}
