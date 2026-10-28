# beta4 双环境升级与二开兼容

状态：implemented
类型：bug-fix
Owner：docker-compose.prod.yml

## 问题

开发分支与上游 beta4 存在版本差距，生产运行 beta3 修复版，local 运行不兼容的 0.7.2。升级需要保留二开、账号、知识库与独立环境数据。

## 决策

### 实现方案

在现有工作分支合并上游，不创建额外 worktree。保留二开品牌、供应商配置、知识库 MCP 与容器技能安装。生产沿用 business 1 / knowledge 2 的现有数据库，备份后切换 beta4 镜像；源代码中的部署叠加配置同时保留正式域名与预览域名路由，避免覆盖部署文件后正式入口丢失。镜像必须包含上游 PP-OCRv6 资源和二开 Node/Skills 工具链。local 使用独立的新 Schema 与状态目录，先备份旧数据库、对象和工作区，保留原登录账号、密码哈希和该环境的模型配置，再切换入口；用户明确选择清理 local 旧数据，旧聊天和知识库不迁移，冷备份作为恢复点。

包含空格的源码目录使部分前端测试把 URL pathname 的 %20 当作文件路径。测试使用 fileURLToPath 解码，保留原断言与验收要求。

## 替代方案

- 覆盖二开后直接跟踪上游：丢失已交付能力，不采用。
- 将 local 旧数据库指向 beta4：初始化器拒绝版本且可能损坏保留要求，不采用。
- 两套环境共享生产凭据和数据：破坏独立性，不采用。

## 验证

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 上游与二开共同保留 | Git 合并与源码 | Git tree / package manifests | ancestry、完整 diff、review | 未合并索引与旧版本检查 | Inspected |
| beta4 运行兼容 | 依赖、前后端、沙盒 | Docker images / Compose | Linux unit、frontend lint/unit/build、真实 HTTP/Run | 无效 Skill 与隔离边界 | Passed |
| 生产数据连续 | 持久化与配置 | PostgreSQL / bind state | 备份、升级前后数量与自定义配置、MCP16 | 新空库或配置丢失检测 | Passed |
| local 保留原账号和模型配置，旧历史保留冷备份 | 不兼容 Schema | 旧备份与迁移回执 | 原凭据登录、模型配置与独立空库回读 | 明确旧 Schema 不复用 | Passed |

## 后果

原生旧聊天与新版 Run/Input/Turn 模型不兼容，local 按用户授权不迁移聊天或知识库。切换前备份整套状态，保留可验证回滚点。升级 API 后需检查公网代理，不能只用进程 liveness 认定部署成功。

Linux beta4 镜像内非 slow unit 为 3340 passed、124 skipped；上游追加的沙盒回归文件为 35 passed。前端 lint、879 项测试与构建通过，含空格的真实源码目录中路径回归通过。prod 升级前后用户、知识库、文件、消息与会话数量，以及 Agent 配置 SHA-256 完全一致，数据库 MCP 测试返回 16 个工具。两套环境均通过 MiniMax 四技能真实 HTTP 安装和文件回读，并清理测试安装；真实 Agent Run 的 JSON 产物证实 DNS、TLS、HTTP 401 连通，Node 24.22.1 和 Skills 1.7.4 可执行。local 原凭据登录返回 200，迁移后重建 Redis 模型目录缓存，保留原模型选择。两套公开网页显示 beta4 和单位品牌，local Spotlight 使用独立 knowledge Key 与新网络。
