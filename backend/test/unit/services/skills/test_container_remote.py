"""Container 技能下载包的文件边界与后端选择回归。"""

import base64
import io
import zipfile

import pytest

from yuxi.modules.extensions.skills import remote
from yuxi.sandbox_runner.skill_installer import SkillInstaller


def packed(entries):
    """创建不可信下载结果。"""
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return base64.b64encode(stream.getvalue()).decode()


@pytest.mark.asyncio
async def test_container_download_works_without_active_agent_run(monkeypatch, tmp_path):
    """设置页请求不依赖 Run 上下文，回读草稿文件并确认暂存目录清理。"""
    from yuxi.modules.agents.runtime.sandbox.container import SandboxRunnerClient

    monkeypatch.setenv("SANDBOX_BACKEND", "container")

    async def policy():
        return {"allowed_hosts": ["modelscope.cn"]}

    from types import SimpleNamespace

    monkeypatch.setattr(remote, "remote_skill_source_policy", SimpleNamespace(get=policy))
    monkeypatch.setattr(
        SandboxRunnerClient,
        "skill_cli",
        lambda self, args, allowed_hosts: {
            "exit_code": 0,
            "output": "installed",
            "archive_b64": packed([("minimax-pdf/SKILL.md", "name: minimax-pdf")]),
        },
    )
    request = remote._RemoteSkillRequest.create("test-user")
    root = request.root
    try:
        await request.run(
            [
                "npx",
                "-y",
                "skills",
                "add",
                "https://modelscope.cn/collections/MiniMax/MiniMax-Office-skills",
                "--skill",
                "minimax-pdf",
                "-g",
                "-y",
                "--copy",
            ]
        )
        await request.download_skill("minimax-pdf", tmp_path / "download")
        assert (tmp_path / "download/SKILL.md").read_text() == "name: minimax-pdf"
    finally:
        await request.cleanup()
    assert not root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["../escape", "/tmp/escape", "good/../../escape", "good/../escape", "good\\escape"])
async def test_download_rejects_escaped_paths(name):
    """不可信归档不能逃出私有下载根。"""
    request = remote._ContainerSkillRequest()
    try:
        with pytest.raises(ValueError, match="非法文件路径"):
            request._unpack(packed([(name, "bad")]))
        assert list(request.root.iterdir()) == []
    finally:
        await request.cleanup()


@pytest.mark.parametrize(
    "args",
    [
        ["add", "http://github.com/test/repo", "--list"],
        ["add", "https://127.0.0.1/repo", "--list"],
        ["add", "https://user:password@github.com/test/repo", "--list"],
        ["add", "https://github.com/test/repo", "--skill", "../../escape", "-g", "-y", "--copy"],
        ["add", "https://github.com/test/repo", "--skill", "good", "--execute", "-y", "--copy"],
        ["find", "--help"],
        ["exec", "touch /tmp/escape"],
    ],
)
def test_installer_rejects_arbitrary_commands_and_sources(args):
    """runner 的固定操作入口拒绝任意命令、来源和参数注入。"""
    with pytest.raises(ValueError):
        SkillInstaller._validate_args(args, ["github.com"])


def test_installer_honors_custom_source_and_large_batch():
    """管理员允许的来源与超过二十项的批次保持现有业务契约。"""
    args = ["add", "https://gitlab.example.org/team/skills"]
    for index in range(21):
        args.extend(["--skill", f"skill-{index}"])
    args.extend(["-g", "-y", "--copy"])
    SkillInstaller._validate_args(args, [" GitLab.Example.Org. "])


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["symlink", "duplicate", "entries", "bytes"])
async def test_download_rejects_invalid_archive_metadata(kind):
    """全部条目预检后才落盘，拒绝链接、重名及资源超限。"""
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if kind == "symlink":
            item = zipfile.ZipInfo("good/SKILL.md")
            item.external_attr = 0o120777 << 16
            archive.writestr(item, "/etc/passwd")
        elif kind == "duplicate":
            archive.writestr("good/SKILL.md", "first")
            with pytest.warns(UserWarning):
                archive.writestr("good/SKILL.md", "second")
        elif kind == "entries":
            for i in range(2001):
                archive.writestr(f"good/f{i}", "")
        else:
            archive.writestr("good/big", b"x" * (50 * 1024 * 1024 + 1))
    request = remote._ContainerSkillRequest()
    try:
        with pytest.raises(ValueError):
            request._unpack(base64.b64encode(stream.getvalue()).decode())
        assert list(request.root.iterdir()) == []
    finally:
        await request.cleanup()


@pytest.mark.parametrize("failure", [None, "cli", "start", "exec", "timeout", "capacity"])
def test_installer_finally_removes_request_container(failure):
    """执行失败和超时也必须删除容器；满额请求不能创建资源。"""
    import json
    from types import SimpleNamespace

    from yuxi.sandbox_runner.engine import EngineError, ExecDeadlineExceeded

    class Engine:
        def __init__(self):
            self.containers = {}
            self.config = None

        def list_containers(self, **kwargs):
            return [{}] * 4 if failure == "capacity" else list(self.containers.values())

        def create_container(self, *, name, config):
            self.config = config
            self.containers["test"] = {"Id": "test"}
            return self.containers["test"]

        def start_container(self, cid):
            if failure == "start":
                raise EngineError("start failed")

        def create_exec(self, cid, **kwargs):
            if failure == "exec":
                raise EngineError("exec failed")
            return "exec"

        def start_exec(self, eid, **kwargs):
            if failure == "timeout":
                raise ExecDeadlineExceeded(b"", False)
            return json.dumps({"exit_code": 1 if failure == "cli" else 0, "output": "", "archive_b64": packed([])}).encode(), False

        def inspect_exec(self, eid, **kwargs):
            return 0

        def remove_container(self, cid):
            del self.containers[cid]

    settings = SimpleNamespace(
        run_uid=1000,
        run_gid=1000,
        network="bridge",
        pids_limit=256,
        memory_bytes=1024**3,
        cpus=1,
        home_bytes=256 * 1024**2,
        tmp_bytes=256 * 1024**2,
    )
    engine = Engine()
    installer = SkillInstaller(settings, engine, "fixed-image", "test-scope")
    if failure in ("start", "exec", "timeout", "capacity"):
        with pytest.raises((EngineError, ValueError)):
            installer.run(["add", "https://github.com/test/repo", "--list"], ["github.com"])
    else:
        result = installer.run(["add", "https://github.com/test/repo", "--list"], ["github.com"])
        assert result["exit_code"] == (1 if failure == "cli" else 0)
    assert engine.containers == {}
    if engine.config:
        config = engine.config["HostConfig"]
        assert not config.get("Mounts") and not config.get("Binds")
        assert config["ReadonlyRootfs"] and config["CapDrop"] == ["ALL"]
        assert "no-new-privileges" in config["SecurityOpt"]
        assert engine.config["User"] == "1000:1000"
