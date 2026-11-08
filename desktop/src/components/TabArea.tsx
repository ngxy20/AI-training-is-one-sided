import { useApp } from '../store'
import type { Tab } from '../types'
import { DatasetView, JsonResourceView, PipelineView, RecordsView, SqlEditor, WelcomeView } from './views/DataViews'
import { AuditView, DashboardView, LineageView, PluginsView, SearchView, SettingsView } from './views/SystemViews'
import { AnnotationView, ConfigView, EvalRunView, EvalSuiteView, ReportView, RunView, ScriptEditor } from './views/WorkViews'
import { ThemeView } from './views/ThemeView'
import { ModelDetailView, ModelRegistryView } from './views/ModelRegistryView'
import { AgentView, FineTuneView } from './views/OrchestrationViews'
import { MembersView, ModelsView, SchedulesView } from './views/WorkspaceViews'

function View({ tab }: { tab: Tab }) {
  switch (tab.kind) {
    case 'welcome': return <WelcomeView />
    case 'sql': return <SqlEditor tab={tab} />
    case 'dataset': return <DatasetView tab={tab} />
    case 'records': return <RecordsView tab={tab} />
    case 'pipeline': return <PipelineView tab={tab} />
    case 'code': return <ScriptEditor tab={tab} />
    case 'config': return <ConfigView tab={tab} />
    case 'annotation': return <AnnotationView tab={tab} />
    case 'run': return <RunView tab={tab} />
    case 'eval': return <EvalSuiteView tab={tab} />
    case 'evalrun': return <EvalRunView tab={tab} />
    case 'report': return <ReportView tab={tab} />
    case 'settings': return <SettingsView />
    case 'plugins': return <PluginsView />
    case 'lineage': return <LineageView />
    case 'dashboard': return <DashboardView />
    case 'audit': return <AuditView />
    case 'search': return <SearchView tab={tab} />
    case 'json': return <JsonResourceView tab={tab} />
    case 'theme': return <ThemeView />
    case 'models': return <ModelsView />
    case 'schedules': return <SchedulesView />
    case 'members': return <MembersView />
    case 'registry': return <ModelRegistryView />
    case 'model': return <ModelDetailView tab={tab} />
    case 'finetune': return <FineTuneView />
    case 'agent': return <AgentView />
    default: return <div className="editor-pad">未知视图类型：{tab.kind}</div>
  }
}

export function TabArea() {
  const app = useApp()
  const active = app.tabs.find((tab) => tab.id === app.activeTabId)
  return <main className="center">
    <div className="tabbar">
      {app.tabs.map((tab) => <div key={tab.id} className={`tab ${tab.id === app.activeTabId ? 'active' : ''}`}
        onClick={() => app.activateTab(tab.id)} title={tab.title}>
        {tab.dirty && <span className="dirty">●</span>}
        <span className="name">{tab.title}</span>
        <button className="close" onClick={(e) => { e.stopPropagation(); app.closeTab(tab.id) }}>×</button>
      </div>)}
      <div style={{ flex: 1 }} />
      <button className="icon-btn" title="命令面板" onClick={() => app.patch({ paletteOpen: true })}>＋</button>
    </div>
    <div className="editor">{active ? <View key={active.id} tab={active} /> :
      <div className="editor-pad muted">没有打开的标签页，按 Ctrl+Shift+P 打开命令面板。</div>}</div>
  </main>
}
