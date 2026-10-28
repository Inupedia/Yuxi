from __future__ import annotations

import asyncio
import base64
import io
import os
import re
import shlex
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from yuxi.modules.agents.runtime.sandbox import UserSandboxBackend
from yuxi.modules.agents.runtime.sandbox.download import download_sandbox_directory
from yuxi.modules.extensions.options import remote_skill_source_policy
from yuxi.modules.extensions.skills.package import is_valid_skill_slug
from yuxi.modules.workspace.runtime_paths import WORKSPACE_PATH

ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
CONTROL_SEQUENCE_RE = re.compile(r"\x1B\][^\x07]*(?:\x07|\x1B\\)|\x1B[\(\)][A-Za-z0-9]")
CLI_TIMEOUT_SECONDS = 300
GITHUB_REPO_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?/(?!\.{1,2}$)[A-Za-z0-9_.-]+$")
GITHUB_HOST = "github.com"
INVALID_SOURCE_MESSAGE = "source 仅支持远程 Skill 来源白名单中的 HTTPS 地址"


@dataclass(frozen=True, slots=True)
class DownloadedSkill:
    """已下载的目录；包格式由草稿或安装边界校验。"""

    slug: str
    source_dir: Path


@dataclass(frozen=True, slots=True)
class SkillDownloadFailure:
    """一个请求条目的获取失败原因。"""

    slug: str
    error: str


@dataclass(slots=True)
class RemoteSkillDownloads:
    """一次远程批量获取的临时目录与逐项结果。"""

    temp_home: str | None
    results: list[DownloadedSkill | SkillDownloadFailure]

    async def cleanup(self) -> None:
        """释放本批获取持有的宿主临时目录。"""
        if self.temp_home:
            await asyncio.to_thread(shutil.rmtree, self.temp_home, ignore_errors=True)


async def list_remote_skills(source: str, *, uid: str) -> list[dict[str, str]]:
    """列出允许来源中的可安装 Skill。"""
    policy = await remote_skill_source_policy.get()
    normalized_source = _normalize_source(source, policy["allowed_hosts"])

    sandbox = _RemoteSkillRequest.create(uid)
    try:
        output = await sandbox.run(["npx", "-y", "skills", "add", normalized_source, "--list"])
    finally:
        await sandbox.cleanup()

    skills = _parse_available_skills(output)
    if not skills:
        raise ValueError("未发现可安装的 skills")
    return skills


async def download_remote_skills(
    *,
    source: str,
    skills: list[str],
    uid: str,
) -> RemoteSkillDownloads:
    """批量从远程仓库拉取 skill 目录，但不写数据库。"""
    policy = await remote_skill_source_policy.get()
    normalized_source = _normalize_source(source, policy["allowed_hosts"])
    if not skills:
        raise ValueError("skills 列表不能为空")

    results: dict[int, DownloadedSkill | SkillDownloadFailure] = {}
    requests: list[tuple[int, str]] = []
    for index, skill in enumerate(skills):
        try:
            requests.append((index, _normalize_skill_name(skill)))
        except ValueError as exc:
            results[index] = SkillDownloadFailure(slug=skill, error=str(exc))

    if not requests:
        return RemoteSkillDownloads(temp_home=None, results=list(results.values()))

    sandbox = _RemoteSkillRequest.create(uid)
    temp_home: str | None = None
    try:
        try:
            temp_home = tempfile.mkdtemp(prefix=".remote-skills-")
            skill_args: list[str] = []
            for _index, name in requests:
                skill_args.extend(["--skill", name])

            cli_failed = False
            try:
                await sandbox.run(
                    [
                        "npx",
                        "-y",
                        "skills",
                        "add",
                        normalized_source,
                        *skill_args,
                        "-g",
                        "-y",
                        "--copy",
                    ]
                )
            except ValueError:
                # CLI 对不匹配的 skill 会退出码非零，但已安装的目录仍在
                cli_failed = True

            downloaded_dirs: dict[str, Path | None] = {}
            for original_index, name in requests:
                installed_dir = Path(temp_home) / name
                if name not in downloaded_dirs:
                    try:
                        await sandbox.download_skill(name, installed_dir)
                        downloaded_dirs[name] = installed_dir
                    except ValueError:
                        downloaded_dirs[name] = None
                installed_dir = downloaded_dirs[name]
                if installed_dir is None:
                    error_msg = "CLI 安装失败" if cli_failed else "skills CLI 未生成预期的技能目录"
                    results[original_index] = SkillDownloadFailure(slug=name, error=error_msg)
                    continue
                results[original_index] = DownloadedSkill(slug=name, source_dir=installed_dir)

        finally:
            await sandbox.cleanup()
    except BaseException:
        if temp_home:
            await asyncio.to_thread(shutil.rmtree, temp_home, ignore_errors=True)
        raise

    return RemoteSkillDownloads(temp_home=temp_home, results=[results[index] for index in range(len(skills))])


async def search_remote_skills(query: str, *, uid: str) -> list[dict[str, str]]:
    """使用 npx skills find <query> 搜索远程 skills。"""
    query_val = str(query or "").strip()
    if not query_val:
        return []
    if any(ch in query_val for ch in ("\n", "\r", "\x00")):
        raise ValueError("搜索关键字包含非法字符")

    sandbox = _RemoteSkillRequest.create(uid)
    try:
        output = await sandbox.run(["npx", "-y", "skills", "find", query_val])
    finally:
        await sandbox.cleanup()

    return _parse_search_skills(output)


@dataclass(slots=True)
class _RemoteSkillRequest:
    """在操作者环境执行远程 Skill CLI，临时文件按请求隔离。"""

    home: str
    backend: UserSandboxBackend

    @classmethod
    def create(cls, uid: str) -> _RemoteSkillRequest:
        """每个请求只创建自己的共享临时目录，VM 始终属于操作者。"""
        if os.environ.get("SANDBOX_BACKEND", "cube").strip().lower() == "container":
            return _ContainerSkillRequest()

        from yuxi.modules.workspace.filesystem import Workspace
        from yuxi.modules.workspace.paths import ensure_user_workspace

        request_id = f"remote-skill-{uuid.uuid4().hex}"
        home = f"{WORKSPACE_PATH}/.remote-skills/{request_id}"
        ensure_user_workspace(uid)
        workspace = Workspace(uid)
        try:
            workspace.create_authorized_directory("/", ".remote-skills", root="/")
        except FileExistsError:
            pass
        workspace.create_authorized_directory("/.remote-skills", request_id, root="/")
        return cls(home=home, backend=UserSandboxBackend(uid=uid))

    async def run(self, args: list[str]) -> str:
        """执行 Skills CLI，并返回原始命令输出。"""
        workspace = f"{self.home}/workspace"
        command = " && ".join(
            [
                f"mkdir -p {shlex.quote(workspace)}",
                f"cd {shlex.quote(workspace)}",
                f"HOME={shlex.quote(self.home)} {shlex.join(args)}",
            ]
        )
        result = await self.backend.aexecute(command, timeout=CLI_TIMEOUT_SECONDS)
        output = str(result.output or "")
        if result.exit_code != 0:
            raise ValueError("skills CLI 执行失败，请检查来源或稍后重试")
        return output

    async def download_skill(self, name: str, target_dir: Path) -> None:
        """将 Sandbox 内的一个 Skill 下载到宿主临时目录。"""
        remote_dir = f"{self.home}/.agents/skills/{name}"
        await asyncio.to_thread(
            download_sandbox_directory,
            self.backend,
            remote_dir,
            target_dir,
            empty_message="skills CLI 未生成预期的技能目录",
        )

    async def cleanup(self) -> None:
        """只移除本请求的临时文件，不暂停或销毁用户环境。"""
        await asyncio.to_thread(self.backend.delete_authorized_path, self.home, root=WORKSPACE_PATH)


class _ContainerSkillRequest:
    """通过 runner 获取技能，响应只落入请求私有目录并复用草稿校验。"""

    def __init__(self):
        """创建本请求的暂存根，CLI 容器不接触用户文件。"""
        self.root = Path(tempfile.mkdtemp(prefix=".container-skills-"))

    async def run(self, args: list[str]) -> str:
        """固定操作端点与 CLI 前缀，不允许请求选择 shell 命令。"""
        from yuxi.modules.agents.runtime.sandbox.container import SandboxRunnerClient

        if args[:3] != ["npx", "-y", "skills"]:
            raise ValueError("不支持的技能 CLI 操作")
        policy = await remote_skill_source_policy.get()
        result = await asyncio.to_thread(SandboxRunnerClient().skill_cli, args[3:], policy["allowed_hosts"])
        self._unpack(result["archive_b64"])
        if result["exit_code"] != 0:
            raise ValueError("skills CLI 执行失败，请检查来源或稍后重试")
        return str(result["output"])

    def _unpack(self, value: str) -> None:
        """仅导出普通文件，限制字节和条目，拒绝目录逃逸和重复路径。"""
        raw = base64.b64decode(value, validate=True)
        if len(raw) > 52 * 1024 * 1024:
            raise ValueError("技能下载包超过大小限制")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > 2000 or sum(item.file_size for item in entries) > 50 * 1024 * 1024:
                raise ValueError("技能下载包超过文件数或大小限制")
            seen: set[str] = set()
            for item in entries:
                path = PurePosixPath(item.filename)
                mode = (item.external_attr >> 16) & 0o170000
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or "\\" in item.filename
                    or len(path.parts) < 2
                    or len(path.parts) > 64
                    or not is_valid_skill_slug(path.parts[0])
                    or mode not in (0, 0o100000)
                    or item.is_dir()
                    or path.as_posix() in seen
                ):
                    raise ValueError("技能下载包包含非法文件路径或类型")
                seen.add(path.as_posix())
            for item in entries:
                target = self.root.joinpath(*PurePosixPath(item.filename).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(item))

    async def download_skill(self, name: str, target_dir: Path) -> None:
        """把已校验的所选技能复制到现有草稿下载边界。"""
        source = self.root / name
        if not source.is_dir():
            raise ValueError("skills CLI 未生成预期的技能目录")
        await asyncio.to_thread(shutil.copytree, source, target_dir)

    async def cleanup(self) -> None:
        """释放请求暂存目录，容器已由 runner 在返回前删除。"""
        await asyncio.to_thread(shutil.rmtree, self.root, ignore_errors=True)


def _normalize_source(source: str, allowed_hosts: list[str]) -> str:
    value = str(source or "").strip()
    if not value:
        raise ValueError("source 不能为空")
    if any(ch in value for ch in ("\n", "\r", "\x00")):
        raise ValueError("source 包含非法字符")

    allowed_hosts = {host.strip().lower().rstrip(".") for host in allowed_hosts}
    if GITHUB_REPO_PATTERN.fullmatch(value):
        if GITHUB_HOST not in allowed_hosts:
            raise ValueError(INVALID_SOURCE_MESSAGE)
        return f"https://{GITHUB_HOST}/{value}"

    parsed = urlparse(value)
    try:
        hostname = (parsed.hostname or "").rstrip(".").lower()
        port = parsed.port
    except ValueError:
        raise ValueError(INVALID_SOURCE_MESSAGE) from None

    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or hostname not in allowed_hosts
    ):
        raise ValueError(INVALID_SOURCE_MESSAGE)

    path = parsed.path.rstrip("/") or "/"
    if hostname == GITHUB_HOST:
        repo_path = path.strip("/")
        if repo_path.endswith(".git"):
            repo_path = repo_path[:-4]
        if not GITHUB_REPO_PATTERN.fullmatch(repo_path):
            raise ValueError(INVALID_SOURCE_MESSAGE)
        return f"https://{GITHUB_HOST}/{repo_path}"

    return parsed._replace(scheme="https", netloc=hostname, path=path).geturl().rstrip("/")


def _normalize_skill_name(skill: str) -> str:
    value = str(skill or "").strip()
    if not is_valid_skill_slug(value):
        raise ValueError("skill 名称不合法")
    return value


def _clean_cli_output(output: str) -> list[str]:
    cleaned = ANSI_ESCAPE_RE.sub("", output or "")
    cleaned = CONTROL_SEQUENCE_RE.sub("", cleaned)
    cleaned = cleaned.replace("\r", "\n")
    normalized_lines: list[str] = []
    for line in cleaned.splitlines():
        stripped = line.strip()
        stripped = re.sub(r"^[│┌└◇◒◐◓◑■●]+\s*", "", stripped)
        normalized_lines.append(stripped.strip())
    return normalized_lines


def _parse_available_skills(output: str) -> list[dict[str, str]]:
    lines = _clean_cli_output(output)
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    collecting = False

    for idx, line in enumerate(lines):
        if not collecting:
            if "Available Skills" in line:
                collecting = True
            continue

        if not line:
            continue
        if "Use --skill " in line:
            break
        if not is_valid_skill_slug(line):
            continue
        if line in seen:
            continue

        description = ""
        next_index = idx + 1
        while next_index < len(lines):
            next_line = lines[next_index]
            next_index += 1
            if not next_line:
                continue
            if "Use --skill " in next_line:
                break
            if is_valid_skill_slug(next_line):
                break
            if next_line and next_line[0].isalpha():
                description = next_line
            else:
                continue
            break

        seen.add(line)
        items.append({"name": line, "description": description})

    return items


def _parse_search_skills(output: str) -> list[dict[str, str]]:
    """解析 npx skills find 命令的输出。"""
    lines = _clean_cli_output(output)
    results: list[dict[str, str]] = []
    # 匹配形如 "owner/repo@skill-name [installs]"
    # 例如：vercel-labs/agent-skills@web-design-guidelines 339.3K installs
    pattern = re.compile(r"^([a-zA-Z0-9_\-\.]+/[a-zA-Z0-9_\-\.]+)\@([a-zA-Z0-9_\-\.]+)(?:\s+(.*))?$")
    for line in lines:
        line = line.strip()
        if not line:
            continue
        match = pattern.match(line)
        if match:
            source, name, extra = match.groups()
            installs = extra.strip() if extra else ""
            results.append(
                {
                    "source": source,
                    "name": name,
                    "installs": installs,
                }
            )
    return results
