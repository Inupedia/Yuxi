from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.tools import ToolException
from PIL import Image

from yuxi.modules.extensions.tools.builtin import minimax_media
from yuxi.modules.workspace.runtime_paths import workdir_scope_from_runtime_path


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


def test_minimax_video_payload_uses_first_frame_and_adaptive_ratio():
    """I2V 按 MiniMax V2 content[] 协议标记首帧，并让比例跟随图片。"""
    payload = minimax_media._build_video_payload(
        prompt="无人机缓慢升高，展示河边建筑群。",
        duration=5,
        ratio="16:9",
        resolution="768P",
        first_frame_file_id="file-123",
    )

    assert payload["model"] == "MiniMax-H3"
    assert payload["content"] == [
        {"type": "text", "text": "无人机缓慢升高，展示河边建筑群。"},
        {
            "type": "image_url",
            "image_url": {"url": "mm_file://file-123"},
            "role": "first_frame",
        },
    ]
    assert payload["ratio"] == "adaptive"
    assert payload["duration"] == 5


@pytest.mark.asyncio
async def test_minimax_video_uploads_first_frame_with_official_video_purpose(monkeypatch):
    """首帧通过官方文件上传接口传输，不放入 JSON 或公开 URL。"""
    captured = []
    real_async_client = httpx.AsyncClient

    def respond(request):
        """检查发出的 multipart 请求并模拟 MiniMax 的文件 ID 响应。"""
        captured.append(request)
        return httpx.Response(200, json={"file": {"file_id": "file-123"}, "base_resp": {"status_code": 0}})

    monkeypatch.setattr(
        minimax_media.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(transport=httpx.MockTransport(respond), **kwargs),
    )

    file_id = await minimax_media._upload_video_input_file(
        file_name="first-frame.jpg",
        content=b"jpeg-bytes",
        mime_type="image/jpeg",
        key="secret-key",
    )

    request = captured[0]
    assert file_id == "file-123"
    assert str(request.url) == "https://api.minimax.cn/v1/files/upload"
    assert request.headers["Authorization"] == "Bearer secret-key"
    assert request.headers["Content-Type"].startswith("multipart/form-data;")
    assert b"video_generation_input" in request.content
    assert b"first-frame.jpg" in request.content
    assert b"jpeg-bytes" in request.content


@pytest.mark.asyncio
async def test_minimax_video_upload_rejects_invalid_file_id(monkeypatch):
    """拒绝无法安全组成官方 `mm_file://` 引用的响应 ID。"""
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        minimax_media.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"file": {"file_id": "https://attacker.invalid"}})),
            **kwargs,
        ),
    )

    with pytest.raises(ToolException, match="响应缺少有效首帧素材 ID"):
        await minimax_media._upload_video_input_file(
            file_name="first-frame.jpg",
            content=b"jpeg-bytes",
            mime_type="image/jpeg",
            key="secret-key",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response_data", "expected"),
    [
        ({"file": {"file_id": 123456}}, "123456"),
        ({"file": {"id": "file-123"}}, "file-123"),
        ({"file_id": "file-123"}, "file-123"),
    ],
)
async def test_minimax_video_upload_accepts_documented_id_variants(monkeypatch, response_data, expected):
    """接受 upload API 的不变 ID 字段以及常见 JSON 标量包装。"""
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        minimax_media.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=response_data)),
            **kwargs,
        ),
    )

    result = await minimax_media._upload_video_input_file(
        file_name="first-frame.jpg",
        content=b"jpeg-bytes",
        mime_type="image/jpeg",
        key="secret-key",
    )

    assert result == expected


@pytest.mark.parametrize(
    ("image_format", "expected"),
    [
        ("JPEG", "image/jpeg"),
        ("PNG", "image/png"),
        ("WEBP", "image/webp"),
    ],
)
def test_minimax_video_first_frame_detects_image_type_from_signature(image_format, expected):
    assert minimax_media._image_mime_type(_make_test_image(image_format), f"frame.{image_format.lower()}") == expected


def test_minimax_video_first_frame_rejects_unknown_format():
    with pytest.raises(ToolException, match="格式无效"):
        minimax_media._image_mime_type(b"not an image", "frame.jpg")


@pytest.mark.parametrize("size", [(255, 256), (6000, 2400), (256, 1024)])
def test_minimax_video_first_frame_rejects_unsupported_dimensions(size):
    with pytest.raises(ToolException, match="首帧尺寸"):
        minimax_media._image_mime_type(_make_test_image("JPEG", size=size), "frame.jpg")


@pytest.mark.asyncio
async def test_minimax_video_rejects_first_frame_over_byte_limit_before_read_or_upload(monkeypatch):
    """首帧超过字节上限时不读取文件内容或上传供应商。"""
    monkeypatch.setattr(minimax_media, "_MAX_VIDEO_INPUT_IMAGE_BYTES", 4)

    async def get_api_key(_runtime):
        return "secret-key"

    monkeypatch.setattr(minimax_media, "_get_api_key", get_api_key)
    monkeypatch.setattr(minimax_media, "resolve_file_context", lambda _runtime: ("user-a", "projects/project-a"))
    monkeypatch.setattr(minimax_media, "workdir_scope_from_runtime_path", lambda _workdir, _path: "uploads/frame.jpg")
    monkeypatch.setattr(minimax_media, "Workspace", lambda _uid: object())

    class FakeWorkdir:
        def __init__(self, _path, _workspace):
            pass

        def stat(self, _path):
            return {"is_dir": False, "size": 5}

        def read_file(self, *_args):
            pytest.fail("oversized first frame must be rejected before reading")

    uploads = []

    async def record_upload(**kwargs):
        uploads.append(kwargs)
        return "file-123"

    monkeypatch.setattr(minimax_media, "Workdir", FakeWorkdir)
    monkeypatch.setattr(minimax_media, "_upload_video_input_file", record_upload)

    with pytest.raises(ToolException, match="不能超过 30 MB"):
        await minimax_media.minimax_generate_video.coroutine(
            prompt="无人机缓慢升高。",
            runtime=SimpleNamespace(context={}),
            first_frame_path="/home/user/workspace/projects/project-a/uploads/frame.jpg",
        )

    assert uploads == []


@pytest.mark.parametrize(
    ("extension", "brand", "expected"),
    [("heic", b"heic", "image/heic"), ("heif", b"mif1", "image/heif")],
)
def test_minimax_video_first_frame_accepts_official_heif_formats(extension, brand, expected):
    content = b"\x00\x00\x00\x18ftyp" + brand + b"\x00\x00\x00\x00"
    assert minimax_media._image_mime_type(content, f"frame.{extension}") == expected


def test_minimax_video_first_frame_rejects_path_outside_current_workdir():
    """跨 Project 的附件路径会在读取文件或请求 MiniMax 前被拒绝。"""
    with pytest.raises(ValueError, match="outside the Workdir"):
        workdir_scope_from_runtime_path(
            "projects/20261028/abcdef",
            "/home/user/workspace/projects/20261028/123456/uploads/other-user.jpg",
        )


def _make_test_image(image_format, *, size=(256, 256)):
    """生成通过真实图片解析器读取的最小测试帧。"""
    output = BytesIO()
    Image.new("RGB", size).save(output, format=image_format)
    return output.getvalue()
