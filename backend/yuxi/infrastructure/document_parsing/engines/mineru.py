"""
MinerU 文档解析器

使用 MinerU 服务进行文档版面分析和内容提取
"""

import os
import tempfile
import time
from pathlib import Path
from typing import Any

import requests

from yuxi.infrastructure.document_parsing import DocumentParserException
from yuxi.infrastructure.document_parsing.artifacts import extract_markdown_archive
from yuxi.infrastructure.document_parsing.engines import DocumentEngine
from yuxi.infrastructure.observability.logging import logger


class MinerUParser(DocumentEngine):
    """MinerU 文档解析器 - 使用 HTTP API 进行文档理解和解析"""

    engine_id = "mineru_ocr"

    def __init__(self, server_url: str | None = None, backend: str = "hybrid-engine", effort: str = "medium"):
        """接收服务配置作为默认值，单次解析参数优先。"""
        self.server_url = (server_url or os.getenv("MINERU_API_URI") or "http://localhost:30001").rstrip("/")
        self.parse_endpoint = f"{self.server_url}/file_parse"
        self.backend = backend
        self.effort = effort

    def check_health(self) -> dict[str, Any]:
        """检查 MinerU 服务健康状态。"""
        try:
            response = requests.get(f"{self.server_url}/openapi.json", timeout=5)
            if response.status_code != 200:
                return {
                    "status": "unhealthy",
                    "message": f"MinerU 服务响应异常: {response.status_code}",
                    "details": {"server_url": self.server_url},
                }

            try:
                openapi_data = response.json()
                has_file_parse = "/file_parse" in openapi_data.get("paths", {})
                if not has_file_parse:
                    return {
                        "status": "unhealthy",
                        "message": "MinerU 服务缺少必要的端点",
                        "details": {"server_url": self.server_url},
                    }
                return {
                    "status": "healthy",
                    "message": "MinerU 服务运行正常",
                    "details": {
                        "server_url": self.server_url,
                        "api_version": openapi_data.get("info", {}).get("version", "unknown"),
                    },
                }
            except Exception as e:
                return {
                    "status": "unhealthy",
                    "message": f"MinerU 响应格式错误: {str(e)}",
                    "details": {"server_url": self.server_url},
                }

        except requests.exceptions.ConnectionError:
            return {
                "status": "unavailable",
                "message": "MinerU 服务无法连接,请检查服务是否启动",
                "details": {"server_url": self.server_url},
            }
        except requests.exceptions.Timeout:
            return {
                "status": "timeout",
                "message": "MinerU 服务连接超时",
                "details": {"server_url": self.server_url},
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"MinerU 健康检查失败: {str(e)}",
                "details": {"server_url": self.server_url, "error": str(e)},
            }

    def process_file(self, file_path: str, output_dir: Path, params: dict[str, Any] | None = None) -> str:
        """
        使用 MinerU 处理文档

        Args:
            file_path: 文件路径
            params: 处理参数
                - lang_list: 语言列表 (默认: ["ch"])
                - backend: 后端类型 (默认使用实例配置)
                - effort: Hybrid 解析强度 (默认使用实例配置)
                - parse_method: 解析方法 (默认: "auto")
                - start_page_id: 起始页码 (默认: 0)
                - end_page_id: 结束页码 (默认: 99999)
                - formula_enable: 启用公式解析 (默认: True)
                - table_enable: 启用表格解析 (默认: True)
                - image_analysis: 启用图像/图表解析 (默认: True)
                - server_url: OpenAI 兼容服务地址 (*-http-client 后端时可选)

        Returns:
            str: 提取的 Markdown 文本
        """
        if not os.path.exists(file_path):
            raise DocumentParserException(f"文件不存在: {file_path}", self.get_service_name(), "file_not_found")

        file_ext = Path(file_path).suffix.lower()
        if not self.supports_file_type(file_ext):
            raise DocumentParserException(f"不支持的文件类型: {file_ext}", self.get_service_name(), "unsupported_file_type")

        params = params or {}
        data = self._build_request_data(params)
        try:
            start_time = time.time()
            logger.info(
                f"MinerU 开始处理: {os.path.basename(file_path)} "
                f"(backend={data['backend']}, effort={data['effort']}, lang={data['lang_list']})"
            )

            with open(file_path, "rb") as stream:
                response = requests.post(
                    self.parse_endpoint,
                    files={"files": (os.path.basename(file_path), stream, "application/octet-stream")},
                    data=data,
                    timeout=int(params.get("timeout_seconds") or os.environ.get("MINERU_TIMEOUT", 1800)),
                )

            logger.debug(f"MinerU 响应状态: {response.status_code}, Content-Type: {response.headers.get('content-type')}")
            if response.status_code != 200:
                error_detail = self._response_error_detail(response)
                logger.error(f"MinerU HTTP错误 {response.status_code}: {error_detail}")
                raise DocumentParserException(
                    f"MinerU 处理失败: {error_detail}",
                    self.get_service_name(),
                    f"http_{response.status_code}",
                )

            text = self._extract_archive_text(response, output_dir)
            processing_time = time.time() - start_time
            logger.info(f"MinerU 处理成功: {os.path.basename(file_path)} - {len(text)} 字符 ({processing_time:.2f}s)")
            return text

        except DocumentParserException:
            raise
        except requests.exceptions.Timeout:
            error_msg = f"MinerU 处理超时 ({time.time() - start_time:.2f}s), 可以配置 MINERU_TIMEOUT 环境变量。"
            logger.error(error_msg)
            raise DocumentParserException(error_msg, self.get_service_name(), "timeout")
        except requests.exceptions.ConnectionError:
            error_msg = "MinerU 连接失败,请检查服务是否运行"
            logger.error(error_msg)
            raise DocumentParserException(error_msg, self.get_service_name(), "connection_error")
        except Exception as e:
            error_msg = f"MinerU 处理失败: {str(e)}"
            logger.error(f"{error_msg} ({time.time() - start_time:.2f}s)")
            raise DocumentParserException(error_msg, self.get_service_name(), "processing_failed") from e

    def _build_request_data(self, params: dict[str, Any]) -> dict[str, Any]:
        """合并实例默认值、单次任务参数与固定响应选项。"""
        data = {
            "lang_list": params.get("lang_list", ["ch"]),
            "backend": params.get("backend", self.backend),
            "effort": params.get("effort", self.effort),
            "parse_method": params.get("parse_method", "auto"),
            "formula_enable": params.get("formula_enable", True),
            "table_enable": params.get("table_enable", True),
            "image_analysis": params.get("image_analysis", True),
            "start_page_id": params.get("start_page_id", 0),
            "end_page_id": params.get("end_page_id", 99999),
            "return_md": True,
            "response_format_zip": True,
            "return_images": True,
        }
        server_url = params.get("server_url")
        if server_url:
            data["server_url"] = server_url
        return data

    def _response_error_detail(self, response: requests.Response) -> str:
        """读取服务端错误详情，非 JSON 响应回退到正文或状态码。"""
        try:
            error_data = response.json()
        except ValueError:
            return response.text or f"HTTP {response.status_code}"
        if not isinstance(error_data, dict):
            return response.text or f"HTTP {response.status_code}"
        return error_data.get("detail", str(error_data))

    def _extract_archive_text(self, response: requests.Response, output_dir: Path) -> str:
        """把响应 ZIP 解包为 Markdown；失败统一为响应解析错误。"""
        try:
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp_zip:
                tmp_zip.write(response.content)
                tmp_zip.flush()
                try:
                    text = extract_markdown_archive(tmp_zip.name, output_dir)
                finally:
                    os.unlink(tmp_zip.name)

            if not text:
                logger.error("MinerU 未返回任何文本内容")
                raise DocumentParserException("MinerU 未返回任何文本内容", self.get_service_name(), "no_content")
            return text
        except Exception as e:
            raise DocumentParserException(
                f"MinerU 响应解析失败: {str(e)}",
                self.get_service_name(),
                "response_parse_error",
            ) from e
