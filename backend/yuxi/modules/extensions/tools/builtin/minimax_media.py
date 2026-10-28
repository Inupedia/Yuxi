"""通过 MiniMax 官方 API 生成图片和视频。"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import tempfile
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

import httpx
from langchain_core.tools import ToolException
from langgraph.prebuilt.tool_node import ToolRuntime
from pydantic import BaseModel, Field

from yuxi.modules.agents.repositories.environment import AgentEnvRepository
from yuxi.modules.agents.runtime.sandbox.context import sandbox_run_env
from yuxi.modules.extensions.tools.builtin.file_context import resolve_file_context
from yuxi.modules.extensions.tools.registry import tool
from yuxi.modules.knowledge.utils.url_fetcher import SSRFGuardTransport
from yuxi.modules.workspace.filesystem import Workspace
from yuxi.modules.workspace.runtime_paths import runtime_workdir_path
from yuxi.modules.workspace.workdir import Workdir

_API_BASE = "https://api.minimax.cn"
_MAX_IMAGE_BYTES = 25 * 1024 * 1024
_MAX_VIDEO_BYTES = 150 * 1024 * 1024
_MAX_REDIRECTS = 3
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_IMAGE_EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


class MinimaxGenerateImageInput(BaseModel):
    """MiniMax 图片生成参数。"""

    prompt: str = Field(min_length=1, max_length=1500, description="图片内容描述，最多 1500 个字符")
    aspect_ratio: Literal["1:1", "16:9", "4:3", "3:2", "2:3", "3:4", "9:16", "21:9"] = Field(
        default="1:1", description="生成图片宽高比；image-01-live 不支持 21:9"
    )
    model: Literal["image-01", "image-01-live"] = Field(default="image-01", description="MiniMax 官方图片模型")
    n: int = Field(default=1, ge=1, le=9, description="生成数量，1 到 9 张")
    prompt_optimizer: bool = Field(default=True, description="是否让 MiniMax 自动优化提示词")
    aigc_watermark: bool = Field(default=False, description="是否添加 AIGC 标识水印")


class MinimaxGenerateVideoInput(BaseModel):
    """MiniMax H3 文生视频参数。"""

    prompt: str = Field(min_length=1, max_length=2000, description="视频内容描述")
    duration: int = Field(default=5, ge=4, le=15, description="视频时长，4 到 15 秒")
    ratio: Literal["21:9", "16:9", "4:3", "1:1", "3:4", "9:16"] = Field(default="16:9", description="视频宽高比")
    resolution: Literal["768P", "2K"] = Field(default="768P", description="视频分辨率")


class MinimaxCheckVideoInput(BaseModel):
    """MiniMax H3 视频任务查询参数。"""

    task_id: str = Field(min_length=1, max_length=128, description="创建视频任务时 MiniMax 返回的 task_id")


MINIMAX_MEDIA_CONFIG_GUIDE = "先在设置 → Agent 环境中添加 MINIMAX_API_KEY；密钥按用户隔离，仅由 Yuxi 后端调用 MiniMax。"


@tool(
    category="builtin",
    tags=["MiniMax", "图片生成"],
    display_name="MiniMax 图片生成",
    description="调用 MiniMax 官方 image-01 图片生成 API，自动下载并保存图片到当前 Project Workdir。",
    config_guide=MINIMAX_MEDIA_CONFIG_GUIDE,
    args_schema=MinimaxGenerateImageInput,
)
async def minimax_generate_image(
    prompt: str,
    runtime: ToolRuntime,
    aspect_ratio: str = "1:1",
    model: str = "image-01",
    n: int = 1,
    prompt_optimizer: bool = True,
    aigc_watermark: bool = False,
) -> dict:
    """调用 MiniMax 文生图接口并把临时图片 URL 固化到当前 Workdir。"""
    key = await _get_api_key(runtime)
    uid, workdir_relative_path = resolve_file_context(runtime)
    if model == "image-01-live" and aspect_ratio == "21:9":
        raise ToolException("image-01-live 不支持 21:9，请改用其他宽高比。")

    payload = {
        "model": model,
        "prompt": prompt.strip(),
        "aspect_ratio": aspect_ratio,
        "response_format": "url",
        "n": n,
        "prompt_optimizer": prompt_optimizer,
        "aigc_watermark": aigc_watermark,
    }
    data = await _post_json("/v1/image_generation", payload, key)
    base_resp = data.get("base_resp") or {}
    if base_resp.get("status_code") not in (None, 0, "0"):
        raise ToolException("MiniMax 图片生成失败，请检查提示词、账户额度或模型权限。")
    image_urls = (data.get("data") or {}).get("image_urls")
    if not isinstance(image_urls, list) or not image_urls:
        raise ToolException("MiniMax 没有返回可用图片，请检查提示词或内容审核结果。")

    workdir = Workdir(workdir_relative_path, Workspace(uid))
    result_paths: list[str] = []
    with tempfile.TemporaryDirectory(prefix="yuxi-minimax-image-") as directory:
        downloaded: list[tuple[Path, str]] = []
        for index, image_url in enumerate(image_urls[:n], start=1):
            temp_path = Path(directory) / f"image-{index}"
            media_type = await _download_public_media(image_url, temp_path, kind="image", max_bytes=_MAX_IMAGE_BYTES)
            extension = _IMAGE_EXTENSIONS.get(media_type)
            if extension is None:
                raise ToolException("MiniMax 返回了不支持的图片格式；目前支持 PNG、JPEG 和 WebP。")
            downloaded.append((temp_path, extension))

        for temp_path, extension in downloaded:
            relative_path = f"/outputs/minimax/images/{uuid4().hex}{extension}"
            await asyncio.to_thread(workdir.copy_file_from_path, relative_path, str(temp_path))
            result_paths.append(f"{runtime_workdir_path(workdir_relative_path)}{relative_path}")

    return {"model": model, "count": len(result_paths), "files": result_paths}


@tool(
    category="builtin",
    tags=["MiniMax", "视频生成"],
    display_name="MiniMax H3 视频生成",
    description="通过 MiniMax 官方 H3 视频生成 V2 API 提交文生视频任务。任务创建后使用 minimax_check_video 查询并下载结果。",
    config_guide=MINIMAX_MEDIA_CONFIG_GUIDE,
    args_schema=MinimaxGenerateVideoInput,
)
async def minimax_generate_video(
    prompt: str,
    runtime: ToolRuntime,
    duration: int = 5,
    ratio: str = "16:9",
    resolution: str = "768P",
) -> dict:
    """提交 MiniMax H3 异步视频任务，返回 task_id 供后续查询。"""
    key = await _get_api_key(runtime)
    resolve_file_context(runtime)
    if duration < 4 or duration > 15:
        raise ToolException("MiniMax H3 视频时长必须在 4 到 15 秒之间。")
    if not prompt.strip():
        raise ToolException("视频提示词不能为空。")

    data = await _post_json(
        "/v2/video_generation",
        {
            "model": "MiniMax-H3",
            "content": [{"type": "text", "text": prompt.strip()}],
            "resolution": resolution,
            "duration": duration,
            "ratio": ratio,
        },
        key,
        timeout=60.0,
    )
    task_id = data.get("task_id")
    if not isinstance(task_id, str) or not _TASK_ID_RE.fullmatch(task_id):
        raise ToolException("MiniMax 未返回有效的视频任务 ID。")
    return {
        "task_id": task_id,
        "status": "queued",
        "model": "MiniMax-H3",
        "message": "视频任务已提交。稍后调用 minimax_check_video 查询；任务完成后该工具会下载并保存 MP4 文件。",
    }


@tool(
    category="builtin",
    tags=["MiniMax", "视频生成"],
    display_name="查询 MiniMax 视频任务",
    description="查询 MiniMax H3 视频任务状态；任务完成后自动下载 MP4 到当前 Project Workdir。",
    config_guide=MINIMAX_MEDIA_CONFIG_GUIDE,
    args_schema=MinimaxCheckVideoInput,
)
async def minimax_check_video(task_id: str, runtime: ToolRuntime) -> dict:
    """查询 MiniMax H3 任务并在成功时下载 MP4 到当前 Workdir。"""
    if not _TASK_ID_RE.fullmatch(task_id.strip()):
        raise ToolException("视频 task_id 格式无效。")
    key = await _get_api_key(runtime)
    uid, workdir_relative_path = resolve_file_context(runtime)
    data = await _get_json(f"/v2/query/video_generation/{task_id.strip()}", key)
    task = data.get("task") or {}
    status = str(task.get("status") or "unknown").lower()
    if status != "succeeded":
        message = (
            "视频仍在生成中，请稍后再次调用 minimax_check_video。"
            if status in {"queued", "running"}
            else "MiniMax 视频任务未成功，请检查任务状态或稍后重试。"
        )
        return {
            "task_id": task_id,
            "status": status,
            "message": message,
        }

    media_url = (task.get("content") or {}).get("url")
    if not isinstance(media_url, str):
        raise ToolException("MiniMax 任务已完成，但没有返回视频下载地址。")
    workdir = Workdir(workdir_relative_path, Workspace(uid))
    with tempfile.TemporaryDirectory(prefix="yuxi-minimax-video-") as directory:
        temp_path = Path(directory) / "generated.mp4"
        await _download_public_media(media_url, temp_path, kind="video", max_bytes=_MAX_VIDEO_BYTES)
        relative_path = f"/outputs/minimax/videos/minimax_{task_id.strip()}.mp4"
        await asyncio.to_thread(workdir.copy_file_from_path, relative_path, str(temp_path))

    return {
        "task_id": task_id,
        "status": status,
        "duration": task.get("duration"),
        "resolution": task.get("resolution"),
        "file": f"{runtime_workdir_path(workdir_relative_path)}{relative_path}",
    }


async def _get_api_key(runtime: ToolRuntime) -> str:
    """只读取当前运行用户的 Agent 环境变量，不将密钥暴露给模型参数。"""
    uid, _workdir = resolve_file_context(runtime)
    env = sandbox_run_env.get()
    if env is None:
        env = await asyncio.to_thread(AgentEnvRepository.load_for_sync_runtime, uid)
    key = str((env or {}).get("MINIMAX_API_KEY") or "").strip()
    if not key:
        raise ToolException("未配置 MiniMax API Key。请在设置 → Agent 环境中添加 MINIMAX_API_KEY。")
    return key


async def _post_json(path: str, payload: dict, key: str, *, timeout: float = 180.0) -> dict:
    return await _request_json("POST", path, key, json=payload, timeout=timeout)


async def _get_json(path: str, key: str) -> dict:
    return await _request_json("GET", path, key, timeout=30.0)


async def _request_json(method: str, path: str, key: str, *, json: dict | None = None, timeout: float) -> dict:
    """调用固定 MiniMax API 地址；错误信息只返回脱敏后的状态，不拼接响应正文。"""
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.request(
                method,
                f"{_API_BASE}{path}",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=json,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ToolException("MiniMax 返回了无效响应。")
            return data
    except httpx.HTTPStatusError as exc:
        messages = {
            401: "MiniMax API Key 无效或已失效。",
            402: "MiniMax 账户余额不足。",
            403: "MiniMax 拒绝访问，请检查账户或模型权限。",
            422: "MiniMax 内容审核未通过或请求参数不受支持。",
            429: "MiniMax 请求过于频繁，请稍后重试。",
        }
        raise ToolException(messages.get(exc.response.status_code, f"MiniMax 请求失败（HTTP {exc.response.status_code}）。")) from None
    except httpx.TimeoutException:
        raise ToolException("MiniMax 请求超时，请稍后重试。") from None
    except httpx.RequestError:
        raise ToolException("连接 MiniMax 失败，请检查 Yuxi 服务器的 DNS 和外网访问。") from None
    except ValueError:
        raise ToolException("MiniMax 返回的内容不是有效 JSON。") from None


def _validate_public_https_url(url: str) -> None:
    """拒绝非 HTTPS、携带凭据、本地地址和私有 IP 字面量。"""
    parsed = urlsplit(str(url or "").strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ToolException("MiniMax 媒体地址必须是无凭据的公网 HTTPS URL。")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith((".local", ".internal")):
        raise ToolException("MiniMax 媒体地址必须是公网 HTTPS URL。")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return
    if not address.is_global:
        raise ToolException("MiniMax 媒体地址必须是公网 HTTPS URL。")


async def _download_public_media(url: str, target_path: Path, *, kind: Literal["image", "video"], max_bytes: int) -> str:
    """使用防 SSRF 传输下载 MiniMax 返回的媒体，并限制重定向及文件体积。"""
    if not isinstance(url, str) or not url.strip():
        raise ToolException("MiniMax 返回的媒体下载地址无效。")
    _validate_public_https_url(url)
    current_url = url.strip()
    transport = SSRFGuardTransport()
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=10.0),
            transport=transport,
            trust_env=False,
        ) as client:
            for redirect_count in range(_MAX_REDIRECTS + 1):
                async with client.stream("GET", current_url) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("Location")
                        if not location or redirect_count >= _MAX_REDIRECTS:
                            raise ToolException("MiniMax 媒体下载地址重定向异常。")
                        current_url = urljoin(current_url, location)
                        _validate_public_https_url(current_url)
                        continue

                    response.raise_for_status()
                    media_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                    if (kind == "image" and not media_type.startswith("image/")) or (
                        kind == "video" and media_type not in {"video/mp4", "application/octet-stream", "binary/octet-stream"}
                    ):
                        raise ToolException("MiniMax 返回的媒体类型与请求不匹配。")

                    content_length = response.headers.get("Content-Length")
                    if content_length and int(content_length) > max_bytes:
                        raise ToolException("生成文件超过 Yuxi 的安全下载上限。")
                    written = 0
                    with target_path.open("wb") as output:
                        async for chunk in response.aiter_bytes():
                            written += len(chunk)
                            if written > max_bytes:
                                raise ToolException("生成文件超过 Yuxi 的安全下载上限。")
                            output.write(chunk)
                    if not written:
                        raise ToolException("MiniMax 返回了空文件。")
                    return media_type
    except ToolException:
        raise
    except httpx.HTTPStatusError as exc:
        raise ToolException(f"下载 MiniMax 生成文件失败（HTTP {exc.response.status_code}）。") from None
    except httpx.TimeoutException:
        raise ToolException("下载 MiniMax 生成文件超时，请稍后重试。") from None
    except httpx.RequestError:
        raise ToolException("下载 MiniMax 生成文件失败，请检查 Yuxi 服务器的 DNS 和外网访问。") from None
    except (OSError, ValueError):
        raise ToolException("读取 MiniMax 生成文件失败。") from None
    raise ToolException("MiniMax 媒体下载重定向过多。")


__all__ = ["minimax_check_video", "minimax_generate_image", "minimax_generate_video"]
