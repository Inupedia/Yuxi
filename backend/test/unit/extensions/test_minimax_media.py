from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from langchain_core.tools import ToolException

from yuxi.modules.extensions.tools.builtin import minimax_media


@pytest.mark.parametrize(
    "url",
    [
        "http://cdn.example.com/image.png",
        "https://localhost/image.png",
        "https://10.0.0.4/image.png",
        "https://127.0.0.1/image.png",
    ],
)
def test_minimax_media_rejects_non_public_https_urls(url):
    """拒绝非 HTTPS、回环和私网媒体地址。"""
    with pytest.raises(ToolException):
        minimax_media._validate_public_https_url(url)


@pytest.mark.asyncio
async def test_minimax_media_download_rejects_oversized_response(tmp_path, monkeypatch):
    """下载过程按实际流量限制文件大小。"""

    def respond(request):
        return httpx.Response(200, headers={"Content-Type": "image/png"}, content=b"12345")

    monkeypatch.setattr(minimax_media, "SSRFGuardTransport", lambda: httpx.MockTransport(respond))
    target = tmp_path / "image.png"

    with pytest.raises(ToolException, match="下载上限"):
        await minimax_media._download_public_media(
            "https://cdn.example.com/image.png",
            target,
            kind="image",
            max_bytes=4,
        )

    assert not target.exists()


@pytest.mark.asyncio
async def test_minimax_media_download_revalidates_redirect_before_following(tmp_path, monkeypatch):
    """每次重定向都重新检查目标，阻断公网到私网跳转。"""
    requested_urls = []

    def respond(request):
        """记录原始公网请求并模拟恶意重定向。"""
        requested_urls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://127.0.0.1/internal"})

    monkeypatch.setattr(minimax_media, "SSRFGuardTransport", lambda: httpx.MockTransport(respond))
    target = tmp_path / "image.png"

    with pytest.raises(ToolException, match="公网 HTTPS URL"):
        await minimax_media._download_public_media(
            "https://cdn.example.com/image.png",
            target,
            kind="image",
            max_bytes=1024,
        )

    assert requested_urls == ["https://cdn.example.com/image.png"]
    assert not target.exists()


@pytest.mark.asyncio
async def test_minimax_media_download_saves_valid_media(tmp_path, monkeypatch):
    """通过受控下载路径保存并返回真实媒体类型。"""
    monkeypatch.setattr(
        minimax_media,
        "SSRFGuardTransport",
        lambda: httpx.MockTransport(lambda _request: httpx.Response(200, headers={"Content-Type": "image/png"}, content=b"png-bytes")),
    )
    target = tmp_path / "image.png"

    media_type = await minimax_media._download_public_media(
        "https://cdn.example.com/image.png",
        target,
        kind="image",
        max_bytes=1024,
    )

    assert media_type == "image/png"
    assert target.read_bytes() == b"png-bytes"


@pytest.mark.asyncio
async def test_minimax_media_reads_only_the_runtime_users_key(monkeypatch):
    """用户身份来自运行上下文，API Key 参数不由模型输入控制。"""
    loaded_uids = []
    keys_by_uid = {"user-a": "key-a", "user-b": "key-b"}

    def load_for_sync_runtime(uid):
        """模拟按当前执行身份读取各用户的独立环境。"""
        loaded_uids.append(uid)
        return {"MINIMAX_API_KEY": keys_by_uid[uid]}

    monkeypatch.setattr(
        minimax_media.AgentEnvRepository,
        "load_for_sync_runtime",
        staticmethod(load_for_sync_runtime),
    )
    token = minimax_media.sandbox_run_env.set(None)
    runtime = SimpleNamespace(context={"uid": "user-b", "workdir_relative_path": "/workspace/project"})
    try:
        key = await minimax_media._get_api_key(runtime)
    finally:
        minimax_media.sandbox_run_env.reset(token)

    assert key == "key-b"
    assert loaded_uids == ["user-b"]
    assert "api_key" not in minimax_media.MinimaxGenerateImageInput.model_fields
    assert "uid" not in minimax_media.MinimaxGenerateImageInput.model_fields
