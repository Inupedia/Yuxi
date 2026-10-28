"""设置页技能获取使用无用户挂载的一次性容器，不伪造 Agent Run。"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from urllib.parse import urlparse

from yuxi.sandbox_runner.engine import DockerEngine
from yuxi.sandbox_runner.settings import RunnerSettings

# CLI 的输出留在容器中；只导出所选技能的普通文件，不执行仓库中的安装脚本。
_EXPORT_SCRIPT = r"""
import base64, io, json, os, pathlib, stat, subprocess, sys, zipfile
args=json.loads(sys.argv[1])
with open('/home/user/cli.log','wb') as log:
    try:
        code=subprocess.run(['skills',*args],stdout=log,stderr=log,timeout=300).returncode
    except subprocess.TimeoutExpired:
        code=124
output=pathlib.Path('/home/user/cli.log').read_bytes()[:65536].decode('utf-8',errors='replace')
files=io.BytesIO()
count=total=0
with zipfile.ZipFile(files,'w',zipfile.ZIP_STORED) as archive:
    for index,arg in enumerate(args):
        if arg!='--skill': continue
        name=args[index+1]
        root=pathlib.Path('/home/user/.agents/skills')/name
        if not root.exists(): continue
        if root.is_symlink(): raise ValueError('skill root is a symlink')
        for parent,dirs,names in os.walk(root,followlinks=False):
            for child in dirs+names:
                path=pathlib.Path(parent)/child
                mode=path.lstat().st_mode
                if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                    raise ValueError('skill contains a link or special file')
                count+=1
                if count>2000: raise ValueError('too many skill entries')
                if stat.S_ISREG(mode):
                    data=path.read_bytes()
                    total+=len(data)
                    if total>50*1024*1024: raise ValueError('skills exceed 50 MiB')
                    archive.writestr(name+'/'+path.relative_to(root).as_posix(),data)
print(json.dumps({'exit_code':code,'output':output,'archive_b64':base64.b64encode(files.getvalue()).decode()}))
"""


class SkillInstaller:
    """独立管理 CLI 请求容器，不进入 Run 的 lease 与 orphan 回收集合。"""

    def __init__(self, settings: RunnerSettings, engine: DockerEngine, image_id: str, scope: str):
        """复用部署固定的镜像与资源限制。"""
        self.settings = settings
        self.engine = engine
        self.image_id = image_id
        self.scope = scope
        self.lock = threading.Lock()

    def run(self, args: list[str], allowed_hosts: list[str]) -> dict:
        """校验窄 CLI 参数，导出结果后无条件删除容器。"""
        self._validate_args(args, allowed_hosts)
        config = {
            "Image": self.image_id,
            "Cmd": ["sleep", "infinity"],
            "User": f"{self.settings.run_uid}:{self.settings.run_gid}",
            "Env": ["HOME=/home/user", "TMPDIR=/home/user", "LANG=C.UTF-8", "CI=1", "GIT_TERMINAL_PROMPT=0"],
            "WorkingDir": "/home/user",
            "Labels": {"yuxi.skill-install": "true", "yuxi.scope": self.scope, "yuxi.created_at": str(time.time())},
            "HostConfig": {
                "NetworkMode": self.settings.network,
                "ReadonlyRootfs": True,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges"],
                "PidsLimit": self.settings.pids_limit,
                "Memory": self.settings.memory_bytes,
                "MemorySwap": self.settings.memory_bytes,
                "NanoCpus": int(self.settings.cpus * 1_000_000_000),
                "Init": True,
                "Tmpfs": {
                    "/home/user": (
                        f"rw,nosuid,nodev,size={self.settings.home_bytes},uid={self.settings.run_uid},gid={self.settings.run_gid}"
                    ),
                    "/tmp": f"rw,noexec,nosuid,nodev,size={self.settings.tmp_bytes}",
                },
            },
        }
        with self.lock:
            if len(self.engine.list_containers(scope=self.scope, label="yuxi.skill-install")) >= 4:
                raise ValueError("技能下载并发已达到上限，请稍后重试")
            container = self.engine.create_container(name=f"yuxi-skill-{self.scope}-{uuid.uuid4().hex[:16]}", config=config)
        container_id = container["Id"]
        try:
            self.engine.start_container(container_id)
            exec_id = self.engine.create_exec(
                container_id,
                cmd=["python", "-c", _EXPORT_SCRIPT, json.dumps(args)],
                env=[],
                workdir="/home/user",
                user=config["User"],
            )
            output, truncated = self.engine.start_exec(
                exec_id,
                read_timeout=320,
                output_budget=72 * 1024 * 1024,
                deadline=time.monotonic() + 320,
            )
            if truncated or self.engine.inspect_exec(exec_id, timeout=5) != 0:
                raise ValueError("技能下载容器未能生成完整结果，请检查来源或包大小")
            return json.loads(output)
        finally:
            self.engine.remove_container(container_id)

    def cleanup(self, *, expired_only: bool) -> None:
        """清理崩溃遗留请求；正常请求期限小于兜底回收期限。"""
        for item in self.engine.list_containers(scope=self.scope, label="yuxi.skill-install"):
            created = float((item.get("Labels") or {}).get("yuxi.created_at") or 0)
            if not expired_only or time.time() - created > 600:
                self.engine.remove_container(item["Id"])

    @staticmethod
    def _validate_args(args: list[str], allowed_hosts: list[str]) -> None:
        """只允许 list、find 与按技能名 copy，禁止任意命令或 CLI 选项。"""
        if len(args) == 2 and args[0] == "find" and bool(args[1]) and not args[1].startswith("-"):
            return
        if len(args) < 3 or args[0] != "add":
            raise ValueError("不支持的技能 CLI 操作")
        source = urlparse(args[1])
        if source.scheme != "https" or source.hostname not in {host.strip().lower().rstrip(".") for host in allowed_hosts}:
            raise ValueError("技能来源不在下载容器允许的 HTTPS 主机中")
        if source.username or source.password or source.port not in (None, 443) or source.query or source.fragment:
            raise ValueError("技能来源包含不允许的 URL 字段")
        if args[2:] == ["--list"]:
            return
        tail = args[2:-3]
        if args[-3:] != ["-g", "-y", "--copy"] or not tail or len(tail) % 2:
            raise ValueError("技能安装参数非法")
        for index in range(0, len(tail), 2):
            if tail[index] != "--skill" or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", tail[index + 1]):
                raise ValueError("技能名或安装参数非法")
