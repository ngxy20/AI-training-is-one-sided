# AI Training Studio 插件 SDK v0.1（开放）

主体以 MIT 许可证开源（见 `LICENSE`），插件机制开放。插件只依赖 `sidecar/aixian/plugin_sdk.py` 这一个稳定契约文件。
MVP 仅开放 **Python 后端扩展点**；前端 UI 插件、子进程隔离、签名校验留到 V2。

## 1. 包结构

```
my_plugin/
  manifest.json
  plugin.py          # 入口，导出扩展点实现
  requirements.txt
```

安装位置（任选）：

1. 用户插件目录 `%USERPROFILE%\.aixian\plugins\<my_plugin>\`；
2. 仓库 `plugins/examples\`（随应用附带的示例）；
3. 通过 Python entry points，group = `aixian.plugins`（`ep.load()` 返回 manifest 字典或带 `.manifest` 的对象）。

在 UI 中执行「扫描插件」→「启用」即可生效；启用状态按项目隔离存储。

## 2. manifest.json

```json
{
  "id": "com.example.mysql-connector",
  "name": "MySQL Connector",
  "version": "0.1.0",
  "sdk_version": "0.1",
  "app_version": ">=0.1.0 <0.2.0",
  "permissions": ["datasource:connect", "network:outbound"],
  "extension_points": [
    { "point": "data_source", "impl": "plugin:MySQLDataSource" }
  ],
  "config_schema": { "type": "object", "properties": { "host": { "type": "string" } } }
}
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `id` | 是 | 全局唯一，建议反向域名 |
| `name` / `version` | 是 | 展示用 |
| `sdk_version` | 是 | 必须等于 `0.1`，否则标记不兼容 |
| `app_version` | 否 | 版本约束，支持 `>= <= == != > <` 组合 |
| `permissions` | 否 | 见第 4 节 |
| `extension_points` | 是 | `{point, impl, label?}` 列表，`impl` 格式为 `模块名:类名` |
| `config_schema` | 否 | JSON Schema，用于 UI 配置面板 |

## 3. 扩展点接口（Python ABC）

```python
from aixian.plugin_sdk import (
    DataSourcePlugin, CleaningOperatorPlugin, TrainingBackendPlugin,
    EvalMetricPlugin, ModelAdapterPlugin, ReportRendererPlugin,
    AnnotationTemplatePlugin, CommandPlugin,
    TableSchema, QueryResult, JobContext, JobStatus, EvalCase, ModelCase,
    MetricResult, ReportContext,
)

class DataSourcePlugin(ABC):
    def test_connection(self, config: dict) -> bool: ...
    def list_schema(self, config: dict) -> list[TableSchema]: ...
    def query(self, config: dict, sql: str) -> QueryResult: ...

class CleaningOperatorPlugin(ABC):
    def apply(self, record: dict, params: dict) -> dict | None: ...   # 返回 None 表示丢弃

class TrainingBackendPlugin(ABC):
    def submit(self, job: JobContext) -> str: ...
    def status(self, job_id: str) -> JobStatus: ...
    def logs(self, job_id: str) -> Iterable[str]: ...

class EvalMetricPlugin(ABC):
    def score(self, case: EvalCase, output: str) -> MetricResult: ...

class ModelAdapterPlugin(ABC):
    def generate(self, case: ModelCase, config: dict) -> str: ...  # 返回模型输出文本

class ReportRendererPlugin(ABC):
    def render(self, report: ReportContext) -> str: ...               # 返回 HTML

class AnnotationTemplatePlugin(ABC):
    def schema(self) -> dict: ...
    def validate(self, label: dict, schema: dict) -> bool: ...

class CommandPlugin(ABC):
    def run(self, payload: dict, context: JobContext) -> dict: ...
```

| point | 用途 | 调用位置 |
| --- | --- | --- |
| `data_source` | 自定义数据库驱动 | 数据源 `type=plugin` 且指定 `plugin_id` 时 |
| `cleaning_operator` | 自定义清洗算子 | Pipeline 节点 `op = plugin:<id>:<impl>` |
| `annotation_template` | 自定义标注模板 | `/projects/{pid}/annotation-templates` |
| `training_backend` | 自定义训练后端 | Run `runner_type = plugin:<id>` |
| `eval_metric` | 自定义评测指标 | `scorer_json = {"type":"plugin"}` |
| `model_adapter` | 自定义模型推理网关 | `model_ref_json = {"type":"plugin","plugin_id":"..."}`，供 EvalRun / A/B / LLM-judge 调用 |
| `report_renderer` | 自定义 HTML 报告 | 创建报告时传 `renderer_plugin_id` |
| `command` | 自定义命令 | `POST /commands/{name}` |

所有 `JobContext` 都带 `log` 回调，插件可通过它把日志推送到桌面端底部日志面板。

## 4. 权限模型

| 权限 | 含义 | 高风险 |
| --- | --- | --- |
| `datasource:connect` | 连接外部数据库 | 否 |
| `network:outbound` | 对外网络访问 | **是** |
| `fs:read` | 读取本地文件 | 否 |
| `fs:write` | 写入本地文件 | **是** |
| `job:submit` | 提交 Job | **是** |
| `training:submit` | 提交训练 | **是** |
| `model:invoke` | 调用模型推理（含本地模型） | **是** |

声明了高风险权限的插件，在启用时后端返回 `428 PERMISSION_CONFIRMATION_REQUIRED`，
前端弹出二次确认后带 `confirm: true` 重试。运行时调用插件算子前还会核对 `require_permission`。

## 5. 示例插件

| 目录 | 扩展点 | 说明 |
| --- | --- | --- |
| `plugins/examples/mysql_connector` | `data_source` | MySQL 连接器，演示高风险权限二次确认 |
| `plugins/examples/dedup_operator` | `cleaning_operator` | 按字段去重的清洗算子 |
| `plugins/examples/bleu_metric` | `eval_metric` | 无第三方依赖的 BLEU 近似指标 |
| `plugins/examples/html_report_template` | `report_renderer` | 极简 HTML 报告模板 |
| `plugins/examples/echo_adapter` | `model_adapter` | 离线规则应答模型，演示 `model:invoke` 权限 |

最小可用算子：

```python
from aixian.plugin_sdk import CleaningOperatorPlugin

class UpperCase(CleaningOperatorPlugin):
    def apply(self, record, params):
        field = params.get("field", "text")
        if isinstance(record.get(field), str):
            record[field] = record[field].upper()
        return record
```

## 6. V2 前端协议（仅定义消息格式，未实现）

```json
{ "type": "plugin.event", "version": "0.1", "event": "string", "payload": "object" }
{ "type": "plugin.component", "version": "0.1", "slot": "string", "schema": "object" }
```

常量导出为 `FRONTEND_EVENT` / `FRONTEND_COMPONENT`。V1 不提供事件总线与组件注册实现。

## 7. 兼容性

- 当前 `sdk_version = 0.1`，`app_version = 0.1.0`。
- 隔离方式：进程内 `importlib` 加载（MVP）；V2 计划子进程隔离 + 签名校验。
- 破坏性变更时 SDK 版本号递增，旧插件在 UI 中显示「不兼容」而非崩溃宿主。
