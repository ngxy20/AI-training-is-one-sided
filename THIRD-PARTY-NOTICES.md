# 第三方组件清单 / THIRD-PARTY NOTICES

本项目主体以 **MIT 许可证**开源（见 `LICENSE`）。下表列出随项目使用/打包的第三方组件，
各组件权利归其各自所有者，按其**随附的官方 LICENSE 文件**为准；
本清单仅作归类参考，正式分发自己的构建产物前请逐项核对。

## 桌面端（Node / Electron）

| 组件 | 用途 | 许可（参考） |
| --- | --- | --- |
| Electron | 桌面壳 | MIT |
| React / React DOM | UI | MIT |
| Monaco Editor / @monaco-editor/react | 代码与 SQL 编辑器 | MIT |
| Vite | 前端构建 | MIT |
| TypeScript | 类型检查 | Apache-2.0 |
| @vitejs/plugin-react | 构建插件 | MIT |
| electron-builder / app-builder-lib | Windows 安装包 | MIT |
| 7-Zip (7za.exe，打包期工具) | 解包 NSIS 资源 | LGPL-2.1+ / unRAR 限制 |

## 本地服务（Python / FastAPI Sidecar）

| 组件 | 用途 | 许可（参考） |
| --- | --- | --- |
| FastAPI / Starlette | HTTP API | MIT / BSD-3-Clause |
| Uvicorn | ASGI 服务器 | BSD-3-Clause |
| SQLAlchemy | ORM | MIT |
| Pydantic / pydantic-core | 数据校验 | MIT |
| PyYAML | YAML 参数 | MIT |
| python-multipart / Jinja2 | 表单 / 模板 | Apache-2.0 / BSD-3-Clause |
| cryptography | DPAPI 回退加密、凭据 | Apache-2.0 OR BSD-3-Clause |
| httpx / httpcore | 模型端点调用 | BSD-3-Clause |
| paramiko | SSH Runner | LGPL-2.1 |
| docker (SDK) | Docker Runner | Apache-2.0 |
| psycopg2-binary | PostgreSQL 驱动 | LGPL-3.0 |
| PyMySQL | MySQL 驱动 | MIT |
| pyarrow | Parquet 导入 | Apache-2.0 |
| reportlab | PDF 报告（含 `STSong-Light` CID 中文字体） | BSD-3-Clause |
| numpy（pyarrow 依赖） | 数值库 | BSD-3-Clause |
| PyInstaller | 冻结 Sidecar 为 exe | GPLv2 + bootloader 例外（允许分发生成的二进制） |
| pytest | 开发/测试 | MIT |

## 说明

- **LGPL 组件**（`paramiko`、`psycopg2-binary`、7-Zip）以动态链接/独立可执行文件形式使用；
  若修改这些库本身或改为静态链接，需遵守对应 LGPL 义务。
- **PyInstaller**：其 bootloader 采用 GPLv2 并附带明确的例外条款，允许在不开源自有代码的前提下分发生成的可执行文件；本项目依赖该例外。
- **中文字体**：PDF 导出使用 reportlab 内置的 CID 字体 `STSong-Light`（Adobe 中文字体名映射），
  不随包分发字体文件；若替换为自带字体，请单独确认字体授权。
- 冻结版 exe 的 `_internal/` 目录内包含各依赖自带的 LICENSE / NOTICE 文件，**以那些文件为最终依据**。

如发现本清单与官方许可不一致，请以官方文件为准并告知作者修正。
