# AI 训练工作台 · AI Training Studio

> **一个 Windows 桌面端，把 AI 训练师散落在脚本、Excel、远程终端和报告文档里的工作收进同一条可追溯的流程。**
>
> 模型与算力仍然属于训练师自己：你只需给出**模型路径或推理端点**，平台保存引用、编排流程、管理版本、把结果可视化。平台不携带任何模型权重，也不重写训练框架。

当前版本 **v0.1 · MIT 开源**。可自由使用、修改、再分发与商用，唯一条件是保留版权与许可声明（见 `LICENSE`）。发布与安全说明见 `NOTICE.md`。

**仓库** · https://github.com/ngxy20/AI-training-is-one-sided 　|　 **下载** · https://github.com/ngxy20/AI-training-is-one-sided/releases 　|　 **反馈** · https://github.com/ngxy20/AI-training-is-one-sided/issues

---

## 1. 它是干什么的

### 面向谁

个人 AI 工程师、小团队算法工程师、训练项目负责人 —— 尤其是那些「一个项目要同时管数据版本、训练脚本、远端机器、评测集和报告，最后说不清某个 checkpoint 到底用了哪版数据」的人。

### 解决什么

| 以前 | 现在 |
| --- | --- |
| 拉数据、清洗、标注、训练、评测各用一套脚本/工具 | 一个桌面端，资源树 + 多标签编辑器统一入口 |
| 数据集改了没有记录，复现靠记忆 | 不可变数据集版本 + `manifest` + 内容指纹 + 父版本 |
| 实验参数、代码、数据、环境对不上 | Run 强制关联配置、数据版本、代码版本、环境快照 |
| 评测靠手填 Excel 再算胜率 | 直接调用模型生成输出、自动评分、A/B 胜率与显著性 |
| 报告是孤立文件，不知道基于哪次实验 | 报告强制关联实体，可沿血缘图回溯 |
| 换个环节就换工具/换机器 | 一个 exe，断网可用，本地数据不外传 |

### 一条完整链路

```
数据接入 → 收集脚本 → 数据集版本 → 清洗 → 文本标注 → 训练格式导出
   → 代码/参数编辑 → 微调训练 → 实验追踪 → A/B / 边界 / 准确性测试
   → 指标看板 → 报告（HTML/PDF/JSON/MD）→ 归档与血缘追溯
```

全程也可以交给 **Agent 编排**：用一句中文描述目标 → 生成调用计划 → 人工确认 → 自动执行。

### 不做什么（请先看这里）

- **不内置模型**：权重、推理服务、GPU 都在你那边。平台只存路径/端点引用。
- **不重写训练框架**：训练算法由你自己的脚本实现；平台负责注入环境变量、启动 Runner、采集产物。
- **不内置数据库服务**：连接你现有的 SQLite / PostgreSQL / MySQL。
- **不是多人协作系统**：v0.1 是本地多身份 + 角色校验，没有账号密码与远程认证。
- **不做模型部署/上线**：只登记 checkpoint 与 adapter，不管服务化。

---

## 2. 快速开始（只需 3 步）

### 第 1 步：拿安装包

从 **GitHub Releases** 下载：

| 文件 | 大小 | 用途 |
| --- | --- | --- |
| `AI-Training-Studio-0.1.0-Setup.exe` | 约 128 MB | **推荐**，单文件便于分发；每次启动自解压到临时目录 |
| `AI训练工作台-便携版.zip`（若 Release 提供） | 约 440 MB | 免安装，启动更快；解压后需保留整个目录，不能只复制 exe |
| `SHA256SUMS.txt` | — | 两个交付物的 SHA256，用于完整性校验 |

也可以用根目录 `start.bat` 启动便携版；找不到 exe 时它会走源码模式。

**不需要安装 Python、Node.js、CUDA 或任何依赖**，断网也能跑。

### 第 2 步：校验并放行 SmartScreen

> 发布包 **exe 未做代码签名**（项目暂无签名证书），Windows 首次运行会提示「Windows 已保护你的电脑」。
> 这是未签名的正常表现，但需要你手动确认来源可信。

```powershell
# 先核对完整性（把下面输出与 Release 里的 SHA256SUMS.txt 比对）
Get-FileHash .\AI-Training-Studio-0.1.0-Setup.exe -Algorithm SHA256
```

确认哈希一致后，在 SmartScreen 弹窗点 **更多信息 → 仍要运行**。

### 第 3 步：启动

双击 exe。**首次启动约 30–90 秒**（单文件版要先自解压，取决于磁盘速度），请耐心等，不要反复双击。启动后会自动打开桌面窗口。

- 数据默认落在 `%USERPROFILE%\.aixian\`（项目工作区、SQLite、日志、设置），不会主动外传。
- 本地服务固定在 `127.0.0.1:8756`，浏览器可直接打开 `http://127.0.0.1:8756/` 查看同一界面。
- 交互式 API 文档：`http://127.0.0.1:8756/docs`。

---

## 3. 五分钟走通一次全流程

> **前提**：准备一个模型。可以是本机权重目录（如 `D:\models\qwen-lora`），
> 或一个 OpenAI 兼容推理端点（如 `http://127.0.0.1:8000/v1`）。
> 暂时没有模型？看下一节的「离线演示」。

### Step 1 · 注册模型（只填一次路径）

按 `Ctrl+Shift+P` → 输入「注册模型」，或打开顶栏/命令面板的 **模型注册表** 标签页 → 点「＋ 注册模型」：

- 名称随便起，如 `客服意图 LoRA v1`
- 适配器选 `transformers` → 填本地权重路径；或选 `openai` → 填 Base URL + 模型名
- 点「注册」，再点「测试」验证能否调用

> 路径暂时不存在也能注册，状态会标为「路径缺失」并提示，之后把权重放进去即可。
> 平台**不会复制**你的模型文件。

### Step 2 · 把数据变成版本

- **数据源**：命令面板「连接现有数据库」→ 填连接信息 → 测试 → 写 SQL → 「导入为数据集」
- 或直接「导入数据集版本」→ 选 JSONL / CSV / Parquet 文件路径

每次导入都生成一个**不可变版本**（带 manifest、内容指纹、变更说明），后面所有实验都引用版本 ID。

### Step 3 · 微调（可选）

打开 **微调** 标签页：选模板（LoRA / QLoRA / 全参 / 冻结层）→ 选 Step 1 的基座模型 → 选你自己的训练脚本 → 选数据版本 → 点「提交微调任务」。

平台会向脚本注入这些环境变量，脚本怎么用由你决定：

| 变量 | 含义 |
| --- | --- |
| `AIXIAN_BASE_MODEL` | 基座模型路径/端点 |
| `AIXIAN_FINETUNE_METHOD` | `lora` / `qlora` / `full` / `freeze` |
| `AIXIAN_FINETUNE_PARAMS` | 微调参数 JSON 文件 |
| `AIXIAN_ADAPTER_OUTPUT` | 期望的产物输出目录 |
| `AIXIAN_DATASET_FORMAT` | `alpaca` / `sharegpt` / `jsonl` / `custom` |

训练结束后，`adapters/`、`checkpoints/` 里的产物会**自动登记回模型注册表**，并连上「微调自 / 训练产出」的血缘边。

### Step 4 · 评测与 A/B

- 命令面板「新建评测套件」→ 填用例（input / expected）
- 「运行评测」→ **下拉选择 Step 1 注册的模型** → 平台批量调用模型生成输出再评分
- 「自动生成 A/B 对比」→ 选两个模型 → 分别推理、自动评分、算胜率与 z 检验
- 评分器支持 `exact_match` / `contains` / `regex` / `llm_judge`（真调裁判模型）/ 插件指标

### Step 5 · 报告与追溯

- **报告** 标签页内嵌 HTML 预览，右上角可导出 HTML / PDF / JSON / Markdown
- **血缘图** 标签页可看到「数据集版本 → 实验 → checkpoint → 模型 → 评测 → 报告」的完整引用链
- **审计事件** 标签页记录谁在什么时候改了什么

**想省事？** 打开 **Agent 编排** 标签页，输入「帮我做一次评测并生成报告」→ 生成计划 → 检查/编辑步骤 → 执行。微调、A/B、定时任务这类高风险动作会被拦下来等你确认。

---

## 4. 没有模型 / 没有显卡也能体验

用**离线适配器**注册一个模型，即可在不调用任何真实模型的情况下跑通全部流程与界面：

```json
{ "type": "static", "outputs": { "c1": "你好" } }
```

在「模型注册表」里把上面的 JSON 贴进「高级：JSON 编辑」（或命令面板快速注册时填 `ref_json`），
再建一个用例 `{"id":"c1","input":"问","expected":"你好"}` 的评测套件，用该模型运行评测即可看到
准确率 1.0、逐用例输出和自动生成的报告。

其他离线适配器：`inline`（读用例里的 output 列，用于复现历史结果）、`dataset`（从数据集版本读输出列）、
`echo`（回显输入）。它们只用于**流程演示与回归**，不是真实推理。

---

## 5. 核心概念速查

| 概念 | 说明 |
| --- | --- |
| 项目 | 每个项目独立 workspace + 独立 SQLite 元数据库 + 独立插件启用集 |
| 模型注册表 | 你给路径/端点，平台存引用、版本、血缘；全站下拉复用 |
| 数据集版本 | 不可变；带 manifest、`content_hash`、`parent_version_id` |
| TrainingConfig | 训练脚本 + 参数 YAML（JSON Schema 表单双向同步）+ 微调规格 |
| Run | 一次训练实验，强制关联配置、数据版本，记录代码版本与环境快照 |
| Job | 所有耗时操作（脚本、清洗、训练、评测、Agent）统一走队列表 + 实时日志 |
| 血缘图 | 资产之间的引用关系，报告必须挂在实体上，不允许孤立报告 |
| 插件 | Python 后端扩展点（数据源、清洗算子、模型适配器、评测指标…） |

### 界面速览

```
[项目 ▼] [命令面板] [全局搜索]        [服务状态] [运行中] [◐主题] [设置] [身份]
├── 资源树 ──┬── 多标签编辑器 ──────────────┬── 右侧面板 ──┤
│ 数据源      │ 代码 / SQL / 数据表格 / 标注  │ 属性 / 参数  │
│ 数据集      │ 实验详情 / 报告预览 / 注册表  │ 指标 / 标签  │
│ 模型 微调   │ Monaco 编辑器                │              │
│ 训练 评测   │                              │              │
│ 报告 插件   │                              │              │
├────────── 任务队列 | 日志 | 终端 | 问题 | 审计 ──────────┤
```

常用快捷键：`Ctrl+Shift+P` 命令面板、`Ctrl+N` 新建项目、`Ctrl+W` 关闭标签、标注视图 `↑↓` 切换记录 + 数字键选标签。

---

## 6. 常见问题

| 现象 | 处理 |
| --- | --- |
| SmartScreen 拦截 | 校验 SHA256 → 更多信息 → 仍要运行（见第 2 步） |
| 双击后很久没窗口 | 单文件版首次自解压 30–90 秒，属正常；日常建议用便携版目录 |
| 提示端口被占用 | `8756` 被其它实例占用，先关掉已开的工作台；或设环境变量 `AIXIAN_PORT` 改端口（前端与 Sidecar 需一致） |
| 模型状态「路径缺失」 | 权重还没放到注册的路径；放好后在注册表点「测试」，会自动转为可用 |
| 终端面板报 `TERMINAL_DISABLED` | 本地终端可执行任意命令，**默认关闭**。需要时到「设置 → 全局设置」把 `enable_local_terminal` 设为 `true`，用完改回 |
| 评测报「模型调用失败」 | 检查 Base URL / 模型名 / 服务是否启动；离线演示改用 `static` 适配器 |
| 日志在哪 | 底部「日志」面板按 Job 过滤；文件在 `%USERPROFILE%\.aixian\projects\<项目id>\logs\` |
| 想换主题 | 顶栏 `◐` 或命令面板「主题编辑器」：5 套预设、30 个颜色 Token、实时预览、导入导出 |

---

## 7. 安全与隐私（使用者必读）

- 本地服务绑定 `127.0.0.1`，**MVP 免登录、无 token 鉴权**：同一台机器上的本地进程可以调用本地 API。请**仅在可信单机**运行，不要在多人共用或不受信机器上使用。
- 跨域访问已限制为应用自身来源（Vite 开发服务器与 Sidecar 同源地址），不允许任意网页调用本地 API。
- 数据库凭据在 Windows 上用 DPAPI 加密存储。
- 数据默认只落本地，不主动外传；但**模型推理端点由你自己填**，请求会发往你指定的地址，请自行确认合规。
- `prompt/提示词` 是 PRD v0.1 原文，随仓库公开，便于理解设计意图。
- 发布与安全说明见 `NOTICE.md`；第三方许可见 `THIRD-PARTY-NOTICES.md`；许可全文见 `LICENSE`。

---

## 8. 从源码运行 / 开发

```powershell
# Python 依赖
python -m pip install -r sidecar/requirements.txt

# 前端依赖与构建
cd desktop; npm install; npm run build; cd ..

# 终端 A：本地服务
cd sidecar; python -m aixian --port 8756

# 终端 B：桌面壳（Vite 热更新）
cd desktop; npm run dev            # http://127.0.0.1:5173
# 或 npm run app                   # Electron 加载 Sidecar 托管的 dist
```

| 命令 | 说明 |
| --- | --- |
| `cd sidecar; python -m pytest -q` | 端到端回归（6 个测试） |
| `cd desktop; npm run typecheck && npm run build` | TS 类型检查 + 前端构建 |
| `cd desktop; npm run dist` | 生成单文件安装包（需设 `ELECTRON_BUILDER_BINARIES_MIRROR`） |
| `python -m aixian.migration --legacy-root <含 data/ 的目录> --name 迁移项目` | 可选：导入旧版 JSON 数据 |

### 目录结构

| 路径 | 说明 |
| --- | --- |
| `sidecar/aixian/` | FastAPI 本地服务：API、ORM、服务层、插件 SDK、调度器 |
| `sidecar/tests/` | 端到端回归测试 |
| `desktop/src/` | React + TypeScript 应用（视图、命令面板、主题、状态） |
| `desktop/electron/` | Electron 主进程与受限 preload |
| `plugins/examples/` | 5 个示例插件（数据源、清洗算子、指标、报告模板、模型适配器） |
| `docs/plugin-sdk.md` | 开放插件 SDK 文档 |
| `LICENSE` / `NOTICE.md` / `THIRD-PARTY-NOTICES.md` | MIT 许可全文、发布说明、第三方许可 |
| `release/`（本地才有） | 构建产物，已 gitignore、不在仓库中；发布包从 Releases 下载 |

> 旧 TrainFlow 原型**不属于本仓库**，也不随本仓库分发；历史 CHANGELOG 条目中提到的 `原型/` 目录已不存在。

架构：Electron 壳通过 `HTTP /api/v1` + `WebSocket /ws` 连接 Python FastAPI Sidecar；
Sidecar 下挂项目级 SQLite、workspace 资产目录、Job Runner（local/SSH/Docker）与插件加载器。

插件开发见 `docs/plugin-sdk.md`：8 个扩展点，manifest + 权限声明 + 高风险二次确认。

---

## 9. 许可与贡献

本项目以 **MIT 许可证** 开源（见 `LICENSE`）：可自由使用、修改、再分发及商用，
只需在副本中保留版权与许可声明。第三方组件许可见 `THIRD-PARTY-NOTICES.md`。
发布 fork 请更换名称与图标，避免让人误以为是官方版本。

欢迎在 [Issues](https://github.com/ngxy20/AI-training-is-one-sided/issues) 与 [Pull Requests](https://github.com/ngxy20/AI-training-is-one-sided/pulls) 中参与：

- 反馈优先回答三个问题：**跑通了吗 / 卡在哪一步 / 会不会用自己的真实模型再跑一次**；
- 提交 PR 前请跑 `cd sidecar && python -m pytest -q` 与 `cd desktop && npm run typecheck && npm run build`；
- 请勿在 Issue、截图或日志里附带真实业务数据、凭据或个人信息；
- 提交 PR 即表示同意该贡献以 MIT 许可证发布。

---

## 10. 已知限制（v0.1）

- 训练算法、peft/transformers、GPU 环境由训练师自备；平台只登记产物路径，不校验权重是否可加载。
- 真实 LLM 推理需自备端点或本地程序；`transformers` 适配器需自行安装 `transformers + torch`（冻结版未内置）。
- 本地 SSH / Docker Runner 已实现但未在真实远端环境实测；协作是本地多身份，不是远程账号体系。
- Agent 的规则规划为关键词匹配；LLM 规划依赖所选模型稳定输出 JSON，失败会自动回退内置流程。
- 可视化目前是结果型（指标卡、报告、血缘、日志），**没有训练过程实时 loss/acc 曲线**。
- 单文件安装包首次启动需自解压；exe 未签名。
- PRD 性能指标（10 万条预览 <3s、标注切换 <200ms）尚未做压测。
