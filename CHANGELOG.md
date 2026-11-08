# 更新日志

> **仓库状态说明（2026-11-08）**：以下为开发过程记录。
> ① 历史条目中的「闭源 / 受邀体验」描述仅反映当时状态，**项目现已转为 MIT 开源**（见 `LICENSE`）。
> ② 历史条目中提到的 `原型/` 归档目录**已不在当前仓库**（旧 TrainFlow 原型不属于本次交付，也不随本仓库分发）；
> 如需迁移旧数据，用 `aixian.migration --legacy-root <含 data/ 的目录>` 自行指定。

## 2026-11-08 — 转为 MIT 开源

- 新增 `LICENSE`（MIT 全文）；`NOTICE.md` 由「闭源受邀体验」重写为开源发布说明（许可、第三方组件、未签名包、安全边界、商标、贡献）。
- `README.md` 全站改为公开仓库与 MIT 许可措辞，新增「许可与贡献」章节；`THIRD-PARTY-NOTICES.md` 标注主体许可。
- `docs/plugin-sdk.md`、`sidecar/aixian/plugin_sdk.py` 及界面两处「主体闭源」文案改为「MIT 开源 · 插件开放」。
- 保留 CORS 白名单与本地终端默认关闭等安全设置；重新构建前端、冻结 Sidecar 与发布包，并重新生成 `SHA256SUMS.txt`。
- 说明：`prompt/提示词`（PRD v0.1 原文）随仓库公开。

## 2026-11-08 — 受邀体验版发布准备

- 安全加固：CORS 从通配符改为应用自身来源白名单；本地终端（`POST /terminal/exec`）默认关闭，需显式设置 `enable_local_terminal=true`；新增 `tests/test_security.py`。
- 授权与合规：新增 `NOTICE.md`（闭源、仅限受邀体验、不得再分发）与 `THIRD-PARTY-NOTICES.md`（第三方许可归类）。
- 仓库卫生：`.gitignore` 增加 `release/`、`*.exe`、`*.zip`、`*.7z`，避免 128 MB 安装包与 180 MB Electron 二进制进入版本库；执行 `git init` 并用 `git add -n` 核对无大文件。
- 文档：重写 `README.md` 面向体验者说明「是什么 / 怎么用」；清理 `start.bat`、`config.py`、`migration.py` 中指向已不存在归档目录的引用。
- 发布：重新生成未签名安装包并附 `release/SHA256SUMS.txt` 供完整性校验；README 写明 SmartScreen 放行步骤。

## 2026-11-07 — 第 2、3 步：微调编排与 Agent 编排

**第 2 步：微调模板与产物回写**

- 新增 `FineTuneTemplate` 表、`services/finetune.py`、`api/finetune.py`；`TrainingConfig` 增加 `finetune_json`。4 套内置模板（LoRA / QLoRA / 全参 / 冻结层）+ 自定义模板，含默认参数、JSON Schema 与训练格式。
- `POST /projects/{pid}/finetune-runs` 一键创建 `TrainingConfig` + `Run` + `Job`；`build_spec` 向脚本注入 `AIXIAN_BASE_MODEL` / `AIXIAN_FINETUNE_METHOD` / `AIXIAN_FINETUNE_PARAMS` / `AIXIAN_ADAPTER_OUTPUT` / `AIXIAN_DATASET_FORMAT`。
- 数据集格式校验（`alpaca` / `sharegpt` / `jsonl` / `custom`）：`check_dataset` 检查字段并以警告返回，不硬拦。
- **产物自动回写**：训练成功后扫描 `adapters/` 与 `checkpoints/`，登记为 `kind=adapter|finetuned` 的模型，带 `base_model_id` / `source_run_id`；修复 SQLAlchemy 对 JSON 列原地修改不持久化的问题（重新绑定新 dict）。
- 前端新增「微调工作台」标签页（模板卡片、基座/脚本/数据版本选择、参数编辑、实验列表与产物计数）与一键微调命令。

**第 3 步：Agent 编排层**

- 新增 `AgentSession` 表、`services/agent.py`、`api/agent.py`：19 个工具映射到现有端点，通过应用内 `httpx.ASGITransport` 调用，不重复实现业务逻辑、不经过网络。
- 双模式规划：注册模型（LLM）输出 JSON 计划，解析失败自动回退关键词规则流程（完全离线可用）。
- 人在回路：计划可编辑；`finetune.run` / `ab.generate` / `schedule.create` 为高风险，未确认时拦截为 `needs_confirmation`；执行复用 `Job` 表 + WS 日志 + 审计。
- 前端新增「Agent 编排」标签页（目标、大脑模型选择、计划编辑、确认执行、结果表格、历史会话、工具目录）。

**验证**

- API 端点 101 → **111**；`pytest -q` **5 passed**（新增 `tests/test_finetune_agent.py`，覆盖模板、格式校验、一键微调、产物回写与血缘、Agent 工具/规则规划/LLM 规划/高风险拦截/执行结果）。
- `npm run typecheck && npm run build` 通过；无头浏览器实测微调工作台（4 模板）与 Agent 编排（19 工具、生成计划成功），**0 JS 异常**。

## 2026-11-07 — 第 1 步：模型注册表（登记路径，全站复用）

按「平台是控制平面、模型是训练师资产」的定位实施，不携带任何权重。

- 新增 `Model` 表与 `services/registry.py`：`kind` / `ref_json` / `base_model_id` / `source_run_id` / `source_checkpoint_id` / `version` / `parent_version_id` / `status`；校验适配器类型与必填字段；本地路径暂不存在时允许注册但标 `missing` 并给出警告。
- 新增 `api/models.py`：`GET /projects/{pid}/models|model-kinds`、`POST /projects/{pid}/models`、`GET|PUT|DELETE /models/{id}`、`GET /models/{id}/usage`、`POST /models/{id}/test`。API 端点 96 → **101**。
- `EvalRun` 新增 `model_id`、`ABTest` 新增 `model_a_id` / `model_b_id`；`create_eval_run` / `create_ab_test` / `llm_judge` 全部支持 `model_id` 优先解析，内联 `model_ref_json` 向后兼容（含 legacy 纯字符串 A/B 引用）。
- `POST /runs/{id}/register-model` 登记 checkpoint 时**自动写入注册表**，带来源 Run、step 与指标。
- 资源树新增「模型」分组；血缘图新增模型节点与「微调自 / 训练产出 / checkpoint / 评测模型 / A/B 模型」边；全局搜索与统计自动覆盖。
- 前端新增 `ModelRegistryView`（注册/编辑/归档/测试、表单按适配器动态生成字段、路径选择器、高级 JSON 模式、引用统计）与 `ModelDetailView`（引用配置、血缘、调用测试）；适配器页新增「从注册表载入」；命令面板新增「模型注册表」「注册模型」「快速注册」；评测与 A/B 命令新增 `model_id` 下拉。
- 新增 `tests/test_model_registry.py`：路径注册、端点注册、校验（重名 409 / 非法类型 422 / 缺 URL 422）、版本递增、`model_id` 驱动评测与 A/B、引用统计、资源树/搜索/血缘、连通性测试、checkpoint 自动登记、归档后拒绝引用。
- 验证：`pytest -q` **4 passed**；`npm run typecheck && npm run build` 通过；无头浏览器实测注册流程（路径缺失仍可注册并提示、表格出现新行、资源树 `model` 分组 count=1），**0 JS 异常**。

## 2026-11-07 — 模型推理闭环、定时调度、协作权限与 IDE 主题编辑器

**新增：模型推理适配层（补齐端到端评测）**

- 新增 `sidecar/aixian/services/model_adapters.py`：`openai`（OpenAI 兼容 /chat/completions）、`vllm`（/generate）、`http`（自定义模板与 headers）、`transformers`（本地 HF pipeline，单例复用）、`subprocess`（本地推理程序 stdin/stdout）、`plugin`，并保留 4 种离线适配器用于结果复现。
- 批量并发生成（`concurrency`，transformers 强制串行）、单用例失败隔离、字段路径提取（`choices.0.message.content`）、`fail_fast` 开关。
- `EvalRun` 现在先调模型生成输出再评分；`llm_judge` 评分器会真实调用裁判模型打分并解析 0–1 分数；`ABTest` 支持 `generate: true`，分别调用两个模型后自动评分算胜率与显著性（异步 Job + 报告）。
- 插件 SDK v0.1 新增 `model_adapter` 扩展点、`ModelCase` / `ModelAdapterPlugin` 与 `model:invoke` 高风险权限；新增示例插件 `plugins/examples/echo_adapter`。
- 新端点：`GET /projects/{pid}/model-adapters`、`POST /projects/{pid}/model-adapters/test`。

**新增：cron 定时调度**

- 新增 `Schedule` 表、`services/scheduler.py`（五段表达式解析、下次运行计算、20 秒扫描循环）与 `api/schedules.py`。
- 支持 `script.run` / `pipeline.run` / `eval.run` / `command`，复用既有端点创建 Job，含日志、进度、审计与 `run-now` 立即触发。
- `app.py` lifespan 启动时执行 `migrate_all_projects()`，为已存在项目的 SQLite 自动补齐新表。

**新增：用户 / 角色 / 项目共享（P2-b）**

- 全局 `users` / `project_members` 表（registry DB），五级角色 `owner/admin/reviewer/annotator/viewer`。
- `AuditedRoute` 在所有变更请求前执行角色校验，审计事件写入真实操作者；项目未配置成员时保持原本地免登录语义（向后兼容）。
- 新增 `/users`、`/me`、`/roles`、`/projects/{pid}/members` 端点与成员权限标签页。

**新增：IDE 式主题编辑器**

- 新增 `api/themes.py`（5 套预设、自定义主题、实时 token 覆盖、导入/导出）与 `desktop/src/theme.ts`、`ThemeView.tsx`。
- 30 个颜色 Token 分组（基础 / 文本状态 / 编辑器 / 语法高亮），基础/高级模式切换、色值选择器 + hex 输入 + 原始 JSON 编辑、迷你 IDE 实时预览。
- CSS 变量全面主题化（含滚动条、表格、日志、状态栏、遮罩），Monaco 主题随 Token 同步；启动时自动恢复持久化主题。

**UI**

- 新增 4 个标签页：主题、模型适配器、定时任务、成员与权限；命令面板新增对应命令与「自动生成 A/B」「新建定时任务」；顶栏增加主题快捷入口与身份标识。
- `styles.css` 增加主题编辑器布局样式并替换硬编码颜色。

**数据迁移修复**

- 发现并修复：`Base.metadata.create_all()` 只建新表、不补新列，导致已有项目 SQLite 的 `ab_tests` 缺少 `scorer_json` / `job_id` / `generated`，资源树查询报错。`database.py` 新增 `_add_missing_columns()`，在 lifespan 里对 registry 与每个项目库执行 `ALTER TABLE ... ADD COLUMN`（带常量默认值），保证旧项目平滑升级；新增 `test_legacy_column_migration` 回归用例。

**交付物重建**

- 重新冻结 Sidecar（160 MB）、同步前端与新插件到 `release/AI训练工作台/`，并重新生成单文件安装包（128 MB）。在真实旧项目库上验证：`/tree`、`/schedules`、`/model-adapters`、`/members`、`/themes`、`/users` 全部 200，无 SQL 错误；单文件包自解压后同样通过（首次解压约 30–90 秒，取决于磁盘负载）。

**测试与验证**

- `pytest -q` — **3 passed**（`test_flow.py` 原 10 项 MVP 验收 + `test_new_features.py` 新功能：真实 HTTP 推理、LLM-judge、插件适配器、自动生成 A/B、cron 解析/立即运行、RBAC 403、主题导入导出 + 遗留库列迁移）。
- `npm run typecheck && npm run build` — 通过。
- 无头浏览器验证：主题编辑器 15 个基础 Token / 5 套预设 / 实时预览，切换浅色后 `--bg` 变为 `#f5f7fa`，编辑强调色实时生效，高级模式 30 项 + JSON 编辑；模型适配器、定时任务、成员权限三个标签页均可打开；**0 个 JS 异常**。

## 2026-11-05 — 应用瘦身 + 单文件安装包

**瘦身（功能无损）**

- 用干净 venv + PyPI wheel 重新冻结 Sidecar，去掉 conda numpy 带来的约 400 MB MKL DLL 以及 PyQt5 / matplotlib 等被 hook 带入的包：`809.2 MB → 159.9 MB`。
- 免安装便携版 `1,089.8 MB → 440.2 MB`；新增单文件分发包 `release/AI-Training-Studio-0.1.0-Setup.exe`，压缩后 **127.9 MB**。
- 瘦身版依赖集通过 **完整端到端回归 `pytest -q tests/test_flow.py`（1 passed）**；另对冻结 exe 做了 HTTP 冒烟：Parquet 导入 2 条、PDF 导出 3026 字节（`%PDF`）、插件 4 个、清洗算子 10 个，全部通过。
- `pyarrow 26` 不再强依赖 numpy，Parquet 读写在无 numpy 的冻结环境中验证可用。

**单文件安装包**

- `desktop/package.json` 增加 `win.signAndEditExecutable: false` 跳过 `rcedit`，从而绕开 `winCodeSign` 的 macOS 符号链接权限问题 —— **无需管理员权限或开发者模式**即可 `npm run dist`。
- `extraResources` 改为精确指向 `dist-slim/aixian-sidecar`、`sidecar/aixian`、`web`、`plugins`，不再把整个 `sidecar/`（含 venv 与构建中间产物）打进包。
- 验证：运行单文件 exe → 自解压后 `/api/v1/health` 200、前端 200、`resources/sidecar/aixian-sidecar.exe` 与 `resources/web`、`resources/plugins` 齐全。
- `README.md` 补充两种运行方式对比、瘦身原理与可复现的三步构建流程；已知限制更新为「跳过 rcedit 导致 exe 资源信息未写入」与「自解压首次启动 20–35 秒」。

## 2026-11-05 — 补齐可直接运行的 exe

- 新增 `release/AI训练工作台/AI训练工作台.exe`：免安装便携版，双击即用，目标机器**无需安装 Python / Node.js**，断网可用。
- Python Sidecar 通过 PyInstaller 冻结为 `resources/sidecar/aixian-sidecar.exe`；`desktop/electron/main.cjs` 自动识别开发/打包布局，优先启动冻结 Sidecar，否则回退 `python -m aixian`。
- `config.BUNDLED_PLUGINS_DIR` 支持 `AIXIAN_BUNDLED_PLUGINS` 环境变量，冻结后仍能定位解包的插件目录；打包资源改为 `resources/web`、`resources/sidecar`、`resources/plugins`（Python 进程无法读取 asar 内文件）。
- `start.bat` 优先启动 exe；`AIXIAN_SOURCE_MODE=1` 可强制回源码运行。README 补充 exe 使用说明与三步重新打包流程。
- 验证：无 Python 子进程条件下启动 exe → `/api/v1/health` 200、前端 200、插件 4 个、WebSocket 已连接。
- 当时限制：`electron-builder` 单文件 `portable` 目标一度受 `winCodeSign` 的 macOS 符号链接权限阻塞，**已在同日后续「应用瘦身 + 单文件安装包」条目中通过 `signAndEditExecutable: false` 解决**。

## 2026-11-05 — 旧原型归档

- 原 TrainFlow 原型 `index.html`、`backend/`、`data/`、`models/`、`reports/` 整体移入 `原型/`，保持原有相对结构，旧服务仍可独立运行（`python 原型\backend\server.py`，端口 8300）。
- 新增 `原型/TrainFlow原型.zip`（9 个文件，已排除 `__pycache__`），便于整体分发与留档。
- `config.LEGACY_ROOT` 默认指向 `原型/`，并支持环境变量 `AIXIAN_LEGACY_ROOT` 覆盖；未归档的旧布局自动回退到仓库根目录。数据迁移脚本、README、`start.bat` 中的路径同步更新。
- `prompt/提示词`（PRD v0.1 规格文档）不属于原型产物，保留在根目录。

## v0.1.0 — P0 共享底座 + 数据模块 + P1/P2 核心闭环（首次交付）

**新增**

- 从零重建架构：Electron + React 19 + TypeScript + Monaco 桌面端，Python FastAPI + Uvicorn Sidecar，`/api/v1` 共 78 个端点 + WebSocket `/ws`。
- 项目级隔离：全局 `registry.db` + 每项目独立 `meta.db` 与 workspace（21 张表，SQLAlchemy 2.x）。
- 统一错误 `{code, message, detail}`、分页、自动审计路由、Windows DPAPI 凭据加密。
- 数据闭环：外部 SQLite/PG/MySQL 连接、只读 SQL、Schema 浏览、结果导入；不可变数据集版本 + manifest + 内容指纹；JSONL/CSV/Parquet 导入；Alpaca/ShareGPT/自定义导出；版本化收集脚本；节点化清洗 Pipeline（可复跑）；文本标注模板/任务/审核/Cohen's Kappa/导出。
- 训练闭环：JSON Schema ↔ YAML 双向同步、本地/SSH/Docker/插件 Runner、Job 队列 + 实时日志流 + 中断、checkpoint 发现、实验全关联、模型登记。
- 训后闭环：评测套件与 A/B 测试、规则/正则/LLM-as-judge 接口/插件评分器、指标看板、HTML/PDF/JSON/Markdown 四格式报告且禁止孤立报告。
- 插件 SDK v0.1：7 个扩展点、权限声明、高风险权限启用二次确认、项目级启用集，附 4 个示例插件。
- IDE 交互：资源树双击/右键、多标签编辑器、命令面板、全局搜索、底部任务/日志/终端/问题/审计面板、右侧属性/参数/指标/标签面板。
- 工程化：`requirements.txt` / `package.json` + electron-builder、端到端测试、旧原型数据迁移脚本、`start.bat`。

**测试**

- `cd sidecar; python -m pytest -q tests/test_flow.py` — 1 passed，覆盖 PRD 第 11 节全部 10 项 MVP 验收清单。
- `cd desktop; npm run typecheck && npm run build` — 类型检查通过，产物 `desktop/dist` 生成。

**数据迁移**

- `python -m aixian.migration --name 迁移项目`：把 `原型/data/DS-001.json`（1371 条）与 `原型/data/test_v1.1.json` 迁为独立项目的不可变 v1 版本，原文件保持不变。
- 旧原型未做数据库迁移（无数据库），仅资产导入；`原型/data/state.json` 摘要写入迁移审计事件。

**插件兼容性说明**

- SDK `sdk_version = "0.1"`，应用 `app_version = ">=0.1.0 <0.2.0"`。
- 稳定契约文件：`sidecar/aixian/plugin_sdk.py`。manifest 字段、扩展点接口、权限清单见 `docs/plugin-sdk.md`。
- 本版本不兼容任何 `sdk_version != 0.1` 的插件；插件在 UI 中标记为「不兼容」且无法启用。
- 前端插件协议（事件总线 / 组件注册）仅定义消息格式，未开放实现，计划在 V2 提供。

**已知问题**

- 首次 `npm install` 可能因网络波动导致 Electron 二进制下载失败（不影响 `npm run build`）；使用 `ELECTRON_MIRROR` 镜像重试即可。
- 旧原型（`原型/backend/`、`原型/index.html`、`原型/data/`、`原型/models/`、`原型/reports/`）已归档，未接入新架构。
