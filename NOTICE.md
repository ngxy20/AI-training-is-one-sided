# 发布说明 / NOTICE

**AI 训练工作台（AI Training Studio）v0.1 · MIT 开源**

## 1. 许可

本项目以 **MIT 许可证** 开源，完整条款见 `LICENSE`。

你可以自由使用、复制、修改、合并、发布、再分发乃至商用（含出售副本），
唯一条件是**在副本或实质性部分中保留版权声明与本许可声明**。
软件按「原样」提供，不附带任何明示或暗示担保。

提交 Pull Request 即表示你同意该贡献以 MIT 许可证发布。

本文件不是额外限制，只是把发布、安全与第三方组件相关的信息集中说明；
如与 `LICENSE` 冲突，以 `LICENSE` 为准。

## 2. 第三方组件

本项目打包并使用了若干第三方组件，权利归各自所有者，许可条款见
`THIRD-PARTY-NOTICES.md`。该清单仅作归类参考，请以各组件随附的官方
LICENSE 文件为最终依据。冻结版 exe 的 `_internal/` 目录内也包含依赖自带的
LICENSE / NOTICE 文件。

> 其中 `paramiko`、`psycopg2-binary`、7-Zip 为 LGPL，`pyarrow` 为 Apache-2.0，
> PyInstaller bootloader 为 GPLv2 并附带允许分发生成二进制的例外条款。
> 若你修改这些依赖本身或改变链接方式，请遵守其各自的许可义务。

## 3. 发布包未签名

GitHub Releases 中的 exe **没有代码签名证书**（项目暂无签名证书）。
Windows 首次运行会触发 SmartScreen「Windows 已保护你的电脑」，需要手动选择
**更多信息 → 仍要运行**。

请用 Release 里的 `SHA256SUMS.txt` 校验文件完整性：

```powershell
Get-FileHash .\AI-Training-Studio-0.1.0-Setup.exe -Algorithm SHA256
```

> 未签名不等于有恶意，但意味着**没有发布者身份担保**。
> 请只从本项目 GitHub Releases 下载，或自行从源码构建。
> 如果你要对外分发自己的构建产物，建议自行做代码签名。

## 4. 安全边界（使用者必读）

- 本地服务绑定 `127.0.0.1:8756`，**v0.1 免登录、无 token 鉴权**：
  同一台机器上的任何本地进程都能调用本地 API。请**仅在可信单机**运行，
  不要在多人共用或不受信的机器上使用。
- 跨域访问已限制为应用自身来源（Vite 开发服务器与 Sidecar 同源地址），
  不允许任意网页调用本地 API。
- 「本地终端」可执行任意 shell 命令，**默认关闭**；需要时在
  「设置 → 全局设置」把 `enable_local_terminal` 设为 `true`，用完改回 `false`。
- 所有项目数据默认落在 `%USERPROFILE%\.aixian\`（工作区、SQLite、日志、设置），
  **不会主动外传**。数据库凭据在 Windows 上用 DPAPI 加密存储。
- 本仓库**不包含任何模型权重**；模型路径/推理端点由使用者自己提供，
  请自行确认所填路径与所调用端点的内容合规。
- `prompt/提示词` 是 PRD v0.1 原文，随仓库公开，便于理解设计意图。

## 5. 商标与名称

「AI 训练工作台 / AI Training Studio」为项目标识。MIT 许可证授予的是代码与文档的
使用权，**不包含商标授权**；若你发布 fork，请使用不同名称与图标，避免让人误以为是本项目的官方版本。

## 6. 反馈与贡献

欢迎在 GitHub Issues / Pull Requests 中参与：

- 反馈优先回答三个问题：**跑通了吗 / 卡在哪一步 / 会不会用自己的真实模型再跑一次**；
- 提交 PR 前请跑 `cd sidecar && python -m pytest -q` 与 `cd desktop && npm run typecheck && npm run build`；
- 请勿在 Issue、截图或日志里附带真实业务数据、凭据或个人信息。

---

© 2026 AI Training Studio authors · MIT License
