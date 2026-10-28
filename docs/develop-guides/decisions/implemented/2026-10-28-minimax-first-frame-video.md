# MiniMax 首帧图生视频

状态：implemented
类型：feature
Owner：backend/yuxi/modules/extensions/tools/builtin/minimax_media.py

## 问题

用户上传图片后，Yuxi 内置 MiniMax 视频工具仍只提交文本，无法把该图片固定为视频首帧。用户希望从现有航拍建筑效果图生成连续航拍视频，并能在新聊天中查看实际结果。

## 决策

### 实现方案

保持现有 MiniMax H3 V2 异步任务与查询、下载链路。在视频工具增加可选的 `first_frame_path`，由可信 runtime 身份和当前 Workdir 将路径限制到本会话用户文件；只读并验证该路径的 JPEG、PNG、WebP、HEIC 或 HEIF 图片后，通过 MiniMax 文件上传接口以 `purpose=video_generation_input` 上传，再将返回的文件 ID 作为 `content[].image_url.url` 的 `mm_file://` 引用并标注 `role=first_frame`。HEIC/HEIF 的宽高和比例由 MiniMax 上传接口校验；I2V 的 `ratio` 使用 `adaptive`，文生视频继续使用用户选择的固定比例。MiniMax 返回的 MP4 仍由现有查询工具下载并经 `present_artifacts` 展示。

## 替代方案

- 把首帧改成公网 URL：Yuxi 附件默认私有，不应为一次视频任务公开文件。
- 只把图片内容交给模型描述：不能保证 MiniMax 使用原图作为第一帧。
- 新建独立的视频 MCP：重复现有内置工具和 Agent 环境 Key 管理，不解决附件的 Workdir 边界。

## 后果

首帧通过 MiniMax 官方文件上传接口发送，供应商素材保留 7 天；Yuxi 不持久化供应商文件 ID。`first_frame_path` 仅在可信运行身份解析出的当前 Workdir 内读取。H3 任务仍异步完成，`minimax_check_video` 下载 MP4 到 Workdir，`present_artifacts` 将文件登记为当前聊天交付物。

## 验证

- `cd backend && uv run pytest test/unit/extensions/test_minimax_media.py -q`：25 项通过，覆盖上传 multipart、响应 ID 校验、V2 首帧 payload、T2V 兼容、Workdir 越界、首帧大小及图片格式/尺寸边界；超字节上限的首帧在读取内容和调用上传前被拒绝。
- `cd backend && uv run ruff check yuxi/modules/extensions/tools/builtin/minimax_media.py test/unit/extensions/test_minimax_media.py` 与 `uv run ruff format --check ...`：通过。
- 真实生产 Yuxi chat 使用 5120×3200、约 3.5 MB 的 JPEG 首帧。MiniMax H3 任务生成 5 秒、768P MP4，文件约 5.3 MB；Yuxi 状态为 `succeeded`，`present_artifacts` 确认交付物已展示。公网 `/api/system/ready` 返回 `ready`。
- 生产 MP4 的 `ffprobe` 独立探测未运行：沙盒镜像未安装 `ffprobe`。视频任务成功、MP4 落盘和 chat 交付物均已通过 Yuxi API 回读。
- 本机完整后端 unit 在 macOS Python 3.13 上有 78 项失败、24 项错误和 1 项跳过。未逐项归因这些失败和错误，因此该结果不用于判定相关范围；本功能 targeted suite 全部通过。

## 风险

生产视频生成消耗用户的 MiniMax 额度；本功能不自动重试内容生成，只查询异步任务并在成功时下载结果。
