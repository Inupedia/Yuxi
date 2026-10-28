---
name: minimax-media
description: "使用 MiniMax 官方接口生成图片或 H3 视频；当用户要求生成图片或视频时默认使用此内置能力，或用户指定 MiniMax、Hailuo、image-01、H3 时使用。"
version: "2026.10.28.2"
tool_dependencies: ["minimax_generate_image", "minimax_generate_video", "minimax_check_video", "present_artifacts"]
skill_dependencies: ["chat-widgets"]
---

# MiniMax 图片与视频生成

通过 Yuxi 内置后端工具调用 MiniMax 官方 API。API Key 必须由用户在“设置 → Agent 环境”中配置为 `MINIMAX_API_KEY`；Key 按用户隔离，不要要求用户把 Key 写进提示词、脚本或文件。

## 图片生成

1. 把用户的要求整理成清晰的中文或英文画面提示词，保留主体、构图、场景、光线、风格和文字要求。
2. 调用 `minimax_generate_image`。默认模型为 `image-01`，默认比例为 `1:1`；需要实时画风时可选 `image-01-live`。最多一次生成 9 张。
3. 工具返回的 `files` 是已经下载到当前 Workdir 的虚拟绝对路径。调用 `present_artifacts` 登记这些图片，并读取 `chat-widgets` Skill。
4. 最终答复中用 `Image` 或 `ImageGroup` widget 的 `path` 展示工具实际返回的文件路径；不要使用 MiniMax 24 小时临时 URL。

## H3 视频生成

1. 如果当前用户上传了首帧图片，使用本轮 `<attachment_context>` 中该图片的完整 Workdir 路径，传给 `minimax_generate_video` 的 `first_frame_path`；不要把图片改成纯文本描述，也不要自己构造外部 URL。没有图片时才使用文生视频。I2V 的画幅由首帧自适应；默认 5 秒、768P。
2. 如果当前用户还安装了 MiniMax 官方 `h3-prompt-writing` Skill，可以借用其镜头运动提示词结构；视频内容须明确描述动作和镜头变化，例如“无人机从河面上空平稳升高并缓慢前推，逐步展现建筑群、运动场和背后的森林山体；保持建筑布局、河道和道路形态与首帧一致，真实自然的日间光线，无字幕、无配乐”。
3. 工具返回 `task_id` 后，按间隔约 10 秒调用 `minimax_check_video` 查询状态；状态为 `queued` 或 `running` 时继续等待并查询，避免连续高频轮询。
4. 状态为 `succeeded` 时，查询工具会自动把 MP4 下载到当前 Workdir，并返回 `file` 路径。调用 `present_artifacts` 登记该 MP4；文件在 Yuxi 预览大小限制内时可直接播放，超过限制时提示用户从交付物卡片下载。
5. `failed`、`cancelled` 等非成功状态应如实告知用户，不要伪造生成结果或直接展示外部临时 URL。

## 约束

- 只使用这组内置工具访问 MiniMax；不要在 Agent 沙盒里运行 `curl`、Python 或 Node 脚本访问生成 API。
- `image-01` 的图片生成是同步接口，H3 视频是异步 `task_id` 流程。
- 图片临时链接有效期为 24 小时，工具已自动下载并保存到 Workdir。
- 当前内置 H3 工具实现文生视频和单首帧图生视频；首尾帧及多模态参考视频/音频暂未接入。
