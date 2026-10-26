"""PP-Structure-V3 文档解析器。"""

import base64
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests

from yuxi.infrastructure.document_parsing import DocumentParserException
from yuxi.infrastructure.document_parsing.artifacts import replace_image_links, save_resource
from yuxi.infrastructure.document_parsing.engines import DocumentEngine
from yuxi.infrastructure.observability.logging import logger

# PP-Structure-V3 协议中的 fileType 取值。
_PDF_FILE_TYPE = 0
_IMAGE_FILE_TYPE = 1
_DEFAULT_TIMEOUT_SECONDS = 300


class PPStructureV3Parser(DocumentEngine):
    """通过 PP-Structure-V3 版面解析服务生成 Markdown。"""

    engine_id = "pp_structure_v3_ocr"

    def __init__(self, server_url: str | None = None):
        self.server_url = server_url or os.getenv("PADDLEX_URI") or "http://localhost:8080"
        self.base_url = self.server_url.rstrip("/")
        self.endpoint = f"{self.base_url}/layout-parsing"

    def check_health(self) -> dict[str, Any]:
        """检查 PP-Structure-V3 服务健康状态。"""
        try:
            response = requests.get(f"{self.base_url}/health", timeout=5)

            if response.status_code == 200:
                return {
                    "status": "healthy",
                    "message": "PP-Structure-V3 服务运行正常",
                    "details": {"server_url": self.server_url},
                }
            return {
                "status": "unhealthy",
                "message": f"PP-Structure-V3 服务响应异常: {response.status_code}",
                "details": {"server_url": self.server_url},
            }

        except requests.exceptions.ConnectionError:
            return {
                "status": "unavailable",
                "message": "PP-Structure-V3 服务无法连接,请检查服务是否启动",
                "details": {"server_url": self.server_url},
            }
        except requests.exceptions.Timeout:
            return {
                "status": "timeout",
                "message": "PP-Structure-V3 服务连接超时",
                "details": {"server_url": self.server_url},
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"PP-Structure-V3 健康检查失败: {str(e)}",
                "details": {"server_url": self.server_url, "error": str(e)},
            }

    def process_file(self, file_path: str, output_dir: Path, params: dict[str, Any] | None = None) -> str:
        """调用版面解析 API，保存图片并返回完整 Markdown。"""
        if not os.path.exists(file_path):
            raise DocumentParserException(f"文件不存在: {file_path}", self.get_service_name(), "file_not_found")

        file_ext = Path(file_path).suffix.lower()
        if not self.supports_file_type(file_ext):
            raise DocumentParserException(f"不支持的文件类型: {file_ext}", self.get_service_name(), "unsupported_file_type")

        health = self.check_health()
        if health["status"] != "healthy":
            raise DocumentParserException(f"PP-Structure-V3 服务不可用: {health['message']}", self.get_service_name(), health["status"])

        try:
            start_time = time.time()
            params = params or {}
            file_type = _PDF_FILE_TYPE if file_ext == ".pdf" else _IMAGE_FILE_TYPE

            logger.info(f"PP-Structure-V3 开始处理: {os.path.basename(file_path)}")
            api_result = self._call_layout_api(
                file_input=file_path,
                file_type=file_type,
                use_table_recognition=params.get("use_table_recognition", True),
                use_formula_recognition=params.get("use_formula_recognition", True),
                use_seal_recognition=params.get("use_seal_recognition", False),
                timeout_seconds=params.get("timeout_seconds", _DEFAULT_TIMEOUT_SECONDS),
            )
            if api_result.get("errorCode") != 0:
                raise DocumentParserException(
                    f"PP-Structure-V3 API错误: {api_result.get('errorMsg', '未知错误')}",
                    self.get_service_name(),
                    "api_error",
                )

            result = self._parse_api_result(api_result, output_dir)
            text = result["full_text"]
            processing_time = time.time() - start_time
            logger.info(f"PP-Structure-V3 处理成功: {os.path.basename(file_path)} - {len(text)} 字符 ({processing_time:.2f}s)")

            summary = result["summary"]
            logger.info(f"  统计: {summary.get('total_tables', 0)} 表格, {summary.get('total_formulas', 0)} 公式")

            return text

        except DocumentParserException:
            raise
        except Exception as e:
            processing_time = time.time() - start_time
            error_msg = f"PP-Structure-V3 处理失败: {str(e)}"
            logger.error(f"{error_msg} ({processing_time:.2f}s)")
            raise DocumentParserException(error_msg, self.get_service_name(), "processing_failed") from e

    def _process_file_input(self, file_input: str) -> str:
        """把本地文件编码为 Base64；URL 与已有 Base64 内容原样返回。"""
        if os.path.exists(file_input):
            logger.info(f"PP-Structure-V3 本地文件输入: {file_input} ({os.path.getsize(file_input) / 1024 / 1024:.2f} MB)")
            return self._encode_file_to_base64(file_input)

        if file_input.startswith(("http://", "https://")):
            logger.info(f"PP-Structure-V3 URL 输入: {file_input}")
            return file_input

        logger.info(f"PP-Structure-V3 Base64 输入，长度: {len(file_input)} 字符")
        return file_input

    def _call_layout_api(
        self,
        file_input: str,
        file_type: int | None = None,
        use_table_recognition: bool = True,
        use_formula_recognition: bool = True,
        use_seal_recognition: bool = False,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        """调用版面解析 API，返回协议 JSON。"""
        payload = {"file": self._process_file_input(file_input)}
        optional_params = {
            "fileType": file_type,
            "useTableRecognition": use_table_recognition,
            "useFormulaRecognition": use_formula_recognition,
            "useSealRecognition": use_seal_recognition,
        }
        for key, value in optional_params.items():
            if value is not None:
                payload[key] = value

        response = requests.post(
            self.endpoint,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=timeout_seconds,
        )
        if response.status_code == 200:
            return response.json()

        error_prefix = f"PP-Structure-V3 API请求失败: {response.status_code}"
        raise DocumentParserException(f"{error_prefix}: {response.text}", self.get_service_name(), "api_error")

    def _parse_api_result(self, api_result: dict[str, Any], output_dir: Path) -> dict[str, Any]:
        """保存页面图片，汇总 Markdown 正文与表格/公式统计。"""
        layout_results = api_result.get("result", {}).get("layoutParsingResults", [])
        text_parts: list[str] = []
        total_tables = 0
        total_formulas = 0

        for page_result in layout_results:
            if "markdown" in page_result:
                markdown = page_result["markdown"]
                text = markdown.get("text")
                if text:
                    mapping = {}
                    for image_path, image_url in (markdown.get("images") or {}).items():
                        response = requests.get(image_url, timeout=60)
                        response.raise_for_status()
                        suffix = Path(image_path).suffix or ".png"
                        local_path = save_resource(output_dir, f"images/{uuid4().hex}{suffix}", response.content)
                        mapping[str(image_path)] = local_path
                        mapping[str(image_url)] = local_path
                    text_parts.append(replace_image_links(text, mapping))

            if "prunedResult" in page_result:
                pruned = page_result["prunedResult"]
                total_tables += len(pruned.get("table_result", []))
                total_formulas += len(pruned.get("formula_result", []))

        full_text = "\n\n".join(text_parts)
        return {
            "full_text": full_text,
            "summary": {
                "total_tables": total_tables,
                "total_formulas": total_formulas,
                "total_characters": len(full_text),
            },
        }

    def _encode_file_to_base64(self, file_path: str) -> str:
        """将文件编码为 Base64。"""
        with open(file_path, "rb") as file:
            return base64.b64encode(file.read()).decode("utf-8")
