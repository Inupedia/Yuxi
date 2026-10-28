"""按沙盒后端解析 Compose profile。"""

from __future__ import annotations

import os
from pathlib import Path


def resolve_compose_profile() -> str:
    """读取并规范化沙盒后端，返回需要启用的 Compose profile。"""
    backend = os.environ.get("SANDBOX_BACKEND")
    if backend is None:
        backend = ""
        env_file = Path(".env")
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                key, separator, value = line.partition("=")
                if separator and key.strip() == "SANDBOX_BACKEND":
                    backend = value.strip()
        if backend.startswith(("'", '"')):
            quote = backend[0]
            quote_end = backend.find(quote, 1)
            backend = backend[1:quote_end] if quote_end > 0 else "invalid"
        else:
            backend = backend.split("#", 1)[0].strip()

    normalized = backend.strip().lower()
    if not normalized:
        normalized = "container"
    if normalized == "cube":
        return ""
    if normalized == "container":
        return "--profile container"
    return "invalid"


if __name__ == "__main__":
    print(resolve_compose_profile())
