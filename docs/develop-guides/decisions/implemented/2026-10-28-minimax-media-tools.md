# MiniMax 图片与 H3 视频生成能力

状态：implemented
类型：feature
Owner：backend/yuxi/modules/extensions/tools/builtin/minimax_media.py

图片和视频文件预览由 `backend/yuxi/infrastructure/file_preview.py`、`frontend/src/shared/lib/file_preview.js` 与 `frontend/src/modules/session/ui/workspace/AgentFilePreview.vue` 共同拥有。生成流程由内置 Skill `backend/yuxi/modules/extensions/skills/builtin/minimax-media/SKILL.md` 编排。

## 问题

在 Agent 沙盒里运行生成脚本依赖沙盒的 DNS 和外网策略，可能无法访问 MiniMax；临时生成 URL 也需要及时下载，才能作为 Yuxi 项目文件持续查看和交付。只安装说明型 Skill 无法解决这两个问题。

## 决策

MiniMax 图片和视频生成使用 Yuxi 后端内置工具访问官方 API，Agent 沙盒只负责发起工具调用，不直接持有生成 API 的网络请求逻辑。工具从当前用户的 Agent 环境读取 `MINIMAX_API_KEY`，密钥作为 HTTP Bearer token 发送给固定的 `api.minimax.cn` 地址，不作为模型可填写的工具参数。

### 实现方案

内置工具注册 `minimax_generate_image`、`minimax_generate_video` 和 `minimax_check_video`。图片工具调用 `/v1/image_generation`，把 MiniMax 返回的限时图片下载到当前 Project Workdir；视频工具调用 `/v2/video_generation` 提交 MiniMax-H3 文生视频任务，再由查询工具调用 `/v2/query/video_generation/{task_id}`，成功后把 MP4 保存到 Workdir。下载流程逐跳校验 HTTPS 公网地址，并限制重定向和文件大小。后端与前端文件预览器识别并播放现有预览大小限制内的 MP4，超限文件仍作为可下载产物交付。`minimax-media` Skill 负责提示词整理、异步查询间隔和产物展示；现有 Qwen/SiliconFlow Skill 保留给用户明确指定的图像模型。当前 H3 工具只接入文生视频，不接入图生视频、首尾帧或多模态参考输入。

## 替代方案

- 只安装 MiniMax 生成 Skill：请求仍从 Agent 沙盒出网，无法解决沙盒 DNS 或出口限制，也没有后端下载、持久化和文件预览能力。
- 配置 MiniMax 远程 MCP：需要额外部署并配置 MCP 服务；本功能由 Yuxi 内置工具和 Skill 直接提供。

## 后果

- 每位用户在“设置 → Agent 环境”配置自己的 `MINIMAX_API_KEY` 后才能调用；生成费用计入该用户对应的 MiniMax 账户。
- ModelScope 集合中的官方 `h3-prompt-writing` Skill 负责 H3 提示词结构，不调用生成 API；其 slug 与本内置 `minimax-media` 不同，可继续用于提示词组织，无需停用。
- Yuxi 后端生产服务必须能解析并访问 MiniMax API 和生成结果 CDN。后端网络不通时，工具返回连接失败；沙盒网络配置不影响后端请求。
- MP4 超过 Yuxi 当前 30 MiB 文件预览上限时仍可下载，但不能通过文件预览器内嵌播放。
- 图片生成同步返回；H3 视频生成异步返回 `task_id`，Skill 需要间隔查询。下载后的文件保存在当前 Project Workdir，不依赖 MiniMax 临时 URL 的有效期。
- MiniMax 响应异常、内容审核拒绝、任务失败或下载保护拒绝都会返回失败状态，不报告为成功产物。

## 验证

- 后端 MiniMax、内置发现与文件预览单元测试 27 项通过；覆盖非 HTTPS/本机/私网 URL、私网重定向、用户级 Key 读取、有效媒体落盘和超大小下载。后端 Ruff、格式和 import 排序检查通过。
- MiniMax 工具显式注册，内置 Skill catalog 可解析其工具依赖和 `chat-widgets` 依赖。
- 前端单元测试 880 项通过，lint、typecheck 和生产构建通过；文件预览单测覆盖 MP4 二进制结果。构建有既有 `:deep` 与 chunk 大小告警，没有构建错误。
- 生产 API 容器成功解析 `api.minimax.cn` 并完成 TLS 连接；未认证根路径返回 HTTP 404。该探针没有验证 API 认证、生成结果 CDN、有效账户权限或实际计费生成。
- 本地 macOS 全量后端 unit 曾报告 79 failures、24 errors、3391 passed、1 skipped；失败目前未逐项在目标 Linux 环境归因，不能记为通过或仅归因于操作系统。MiniMax 相关单测与完整 `test_builtin_discovery.py` 单独通过。
