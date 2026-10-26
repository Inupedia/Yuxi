"""RapidOCR 本地 ONNX 文字识别解析器。"""

import os
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
import pypdfium2 as pdfium
from PIL import Image
from rapidocr import EngineType, LangDet, LangRec, ModelType, OCRVersion, RapidOCR

from yuxi.infrastructure.document_parsing import OCRException
from yuxi.infrastructure.document_parsing.engines import DocumentEngine
from yuxi.infrastructure.document_parsing.pdf_utils import PDFIUM_LOCK, render_pdf_page_image
from yuxi.infrastructure.observability.logging import logger


class RapidOCRParser(DocumentEngine):
    """RapidOCR 解析器，使用本地 ONNX 模型进行文字识别。"""

    engine_id = "rapid_ocr"

    def __init__(self, det_box_thresh: float = 0.3):
        self.ocr: RapidOCR | None = None
        self.det_box_thresh = det_box_thresh

    def process_file(self, file_path: str, output_dir: Path, params: dict[str, Any] | None = None) -> str:
        """按扩展名选择 PDF 或单图 OCR。"""
        file_ext = Path(file_path).suffix.lower()
        if not self.supports_file_type(file_ext):
            raise OCRException(f"不支持的文件类型: {file_ext}", self.get_service_name(), "unsupported_file_type")

        if file_ext == ".pdf":
            return self.process_pdf(file_path, params)
        return self.process_image(file_path, params)

    def check_health(self) -> dict[str, Any]:
        """报告本地组件状态，避免选择器刷新时重复加载模型。"""
        return {
            "status": "healthy",
            "message": "RapidOCR PP-OCRv5 组件可用",
            "details": {
                "ocr_version": "PP-OCRv5",
                "engine": "onnxruntime",
                "det_box_thresh": self.det_box_thresh,
            },
        }

    def process_image(self, image: Image.Image | np.ndarray | str, params: dict[str, Any] | None = None) -> str:
        """识别文件路径、PIL 图像或 numpy 数组中的文字。"""
        self._load_model()

        try:
            image_path = image if isinstance(image, str) else self._create_temp_image_file(image)
            try:
                start_time = time.time()
                result = self.ocr(image_path)
                processing_time = time.time() - start_time

                if result.txts:
                    source_name = os.path.basename(image_path) if isinstance(image, str) else "temp_image"
                    logger.info(f"RapidOCR 成功: {source_name} ({processing_time:.2f}s)")
                    return "\n".join(result.txts)

                logger.warning(f"RapidOCR 未识别到文本: {image_path}")
                return ""

            finally:
                if not isinstance(image, str) and os.path.exists(image_path):
                    try:
                        os.remove(image_path)
                    except Exception as e:
                        logger.warning(f"临时文件清理失败: {image_path} - {e}")

        except Exception as e:
            error_msg = f"图像OCR处理失败: {str(e)}"
            logger.error(error_msg)
            raise OCRException(error_msg, self.get_service_name(), "processing_failed") from e

    def process_pdf(self, pdf_path: str, params: dict[str, Any] | None = None) -> str:
        """逐页渲染并 OCR，原生资源在锁内释放后再消费复制图像。"""
        if not os.path.exists(pdf_path):
            raise OCRException(f"PDF 文件不存在: {pdf_path}", self.get_service_name(), "file_not_found")

        params = params or {}
        zoom_x = params.get("zoom_x", 2)

        try:
            all_text: list[str] = []
            with PDFIUM_LOCK:
                pdf_doc = pdfium.PdfDocument(pdf_path)
            try:
                with PDFIUM_LOCK:
                    total_pages = len(pdf_doc)

                logger.info(f"开始处理 PDF: {os.path.basename(pdf_path)} ({total_pages} 页)")

                # 原生资源在锁内释放，耗时 OCR 只消费已复制的图像并在锁外执行。
                for page_num in range(total_pages):
                    with render_pdf_page_image(pdf_doc, page_num, scale=zoom_x) as image:
                        text = self.process_image(image)
                    all_text.append(text)

                    if (page_num + 1) % 10 == 0:
                        logger.info(f"已处理 {page_num + 1}/{total_pages} 页")
            finally:
                with PDFIUM_LOCK:
                    pdf_doc.close()

            result_text = "\n\n".join(all_text)
            logger.info(f"PDF OCR 完成: {os.path.basename(pdf_path)} - {len(result_text)} 字符")
            return result_text

        except OCRException:
            raise
        except Exception as e:
            error_msg = f"PDF OCR 处理失败: {str(e)}"
            logger.error(error_msg)
            raise OCRException(error_msg, self.get_service_name(), "pdf_processing_failed") from e

    @staticmethod
    def _resolve_model_dir() -> Path:
        """获取并确保可写的 RapidOCR 模型存放目录。"""
        env_dir = os.getenv("RAPIDOCR_MODEL_DIR")
        if env_dir:
            model_dir = Path(env_dir).expanduser().resolve()
            model_dir.mkdir(parents=True, exist_ok=True)
            return model_dir

        try:
            import rapidocr

            default_dir = Path(rapidocr.__file__).resolve().parent / "models"
            if default_dir.exists() and os.access(default_dir, os.W_OK):
                return default_dir
        except Exception:
            # 本地安装布局差异或不可写时退回用户缓存。
            pass

        cache_dir = Path.home() / ".cache" / "rapidocr" / "models"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    def _get_model_params(self) -> dict[str, object]:
        """返回 PP-OCRv5 ONNX 检测与识别参数。"""
        model_dir = self._resolve_model_dir()
        return {
            "Global.model_root_dir": str(model_dir),
            "Det.engine_type": EngineType.ONNXRUNTIME,
            "Det.lang_type": LangDet.CH,
            "Det.model_type": ModelType.MOBILE,
            "Det.ocr_version": OCRVersion.PPOCRV5,
            "Det.box_thresh": self.det_box_thresh,
            "Cls.engine_type": EngineType.ONNXRUNTIME,
            "Rec.engine_type": EngineType.ONNXRUNTIME,
            "Rec.lang_type": LangRec.CH,
            "Rec.model_type": ModelType.MOBILE,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
        }

    def _load_model(self) -> None:
        """延迟加载 OCR 模型。"""
        if self.ocr is not None:
            return

        logger.info("加载 RapidOCR 模型...")
        try:
            self.ocr = RapidOCR(params=self._get_model_params())
            logger.info(f"RapidOCR PP-OCRv5 模型加载成功 (det_box_thresh={self.det_box_thresh})")
        except Exception as e:
            raise OCRException(f"RapidOCR模型加载失败: {str(e)}", self.get_service_name(), "load_failed") from e

    def _create_temp_image_file(self, image: Image.Image | np.ndarray) -> str:
        """把内存图像保存为临时 PNG 并返回路径。"""
        try:
            with tempfile.NamedTemporaryFile(mode="wb", suffix=".png", delete=False) as tmp_file:
                temp_path = tmp_file.name

                if isinstance(image, Image.Image):
                    image.save(temp_path)
                elif isinstance(image, np.ndarray):
                    Image.fromarray(image).save(temp_path)
                else:
                    raise ValueError("不支持的图像类型,必须是 PIL.Image 或 numpy.ndarray")

                return temp_path

        except Exception as e:
            raise OCRException(f"临时图像文件创建失败: {str(e)}", self.get_service_name(), "temp_file_error") from e
