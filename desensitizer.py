"""PDF脱敏工具 — 核心引擎：敏感数据检测与脱敏（支持扫描件OCR）"""

import io
from pathlib import Path
from typing import Callable, Optional
import fitz
fitz.TOOLS.mupdf_warnings(False)

import pytesseract
from PIL import Image

from patterns import (
    DetectionResult,
    FileDetectionSummary,
    PATTERN_LIST,
    is_hospital_or_department,
    is_invalid_name,
)

OCR_DPI = 300
OCR_LANG = "chi_sim"
OCR_CONFIDENCE_MIN = 50  # Tier 2 模式最低平均置信度


class Desensitizer:
    """PDF敏感数据检测和脱敏引擎"""

    def __init__(self):
        self._progress_callback: Optional[Callable[[str, float], None]] = None

    def set_progress_callback(self, callback: Callable[[str, float], None]) -> None:
        self._progress_callback = callback

    def _report(self, message: str, progress: float = 0.0) -> None:
        if self._progress_callback:
            self._progress_callback(message, progress)

    # ------------------------------------------------------------------
    # 公共方法
    # ------------------------------------------------------------------

    def scan(self, pdf_path: str | Path) -> FileDetectionSummary:
        """扫描PDF，检测全部敏感数据，返回汇总结果。"""
        pdf_path = Path(pdf_path)
        doc = fitz.open(str(pdf_path))
        total_pages = len(doc)
        detections: list[DetectionResult] = []

        try:
            for page_num in range(total_pages):
                page = doc[page_num]
                frac = (page_num + 1) / total_pages
                self._report(f"正在扫描第 {page_num + 1}/{total_pages} 页...", frac)
                page_detections = self._scan_page(page, page_num)
                detections.extend(page_detections)
        finally:
            doc.close()

        return FileDetectionSummary(
            filename=pdf_path.name,
            total_pages=total_pages,
            detections=detections,
        )

    def redact(self, pdf_path: str | Path, output_path: str | Path) -> int:
        """脱敏PDF，返回覆盖处数。"""
        pdf_path = Path(pdf_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(str(pdf_path))
        total_pages = len(doc)
        total_redacted = 0

        try:
            for page_num in range(total_pages):
                page = doc[page_num]
                frac = (page_num + 1) / total_pages
                self._report(f"正在脱敏第 {page_num + 1}/{total_pages} 页...", frac)

                detections = self._scan_page(page, page_num)
                for det in detections:
                    # 将同目标的多个rect合并为一个覆盖区域
                    if len(det.rects) >= 2:
                        merged = det.rects[0]
                        for r in det.rects[1:]:
                            merged = merged | r
                    else:
                        merged = det.rects[0]
                    # 扩大边距，补偿OCR坐标偏差
                    margin_x = max(merged.width * 0.15, 8)
                    margin_y = max(merged.height * 0.10, 6)
                    expanded = fitz.Rect(
                        merged.x0 - margin_x, merged.y0 - margin_y,
                        merged.x1 + margin_x, merged.y1 + margin_y,
                    )
                    page.add_redact_annot(expanded, fill=(0, 0, 0))
                    total_redacted += 1

                if detections:
                    page.apply_redactions()

            self._report("正在保存文件...", 0.95)
            doc.save(
                str(output_path),
                garbage=4,
                deflate=True,
                clean=True,
                no_new_id=False,
            )
        finally:
            doc.close()

        self._report(f"脱敏完成，共覆盖 {total_redacted} 处", 1.0)
        return total_redacted

    # ------------------------------------------------------------------
    # 单页扫描（自动判断文本/扫描件）
    # ------------------------------------------------------------------

    def _scan_page(self, page: fitz.Page, page_num: int) -> list[DetectionResult]:
        """对单页执行检测，自动识别扫描件并使用OCR。"""
        blocks = page.get_text("blocks")
        text_blocks = [b for b in blocks if b[6] == 0 and b[4].strip()]

        if text_blocks:
            return self._scan_text_page(page, page_num, text_blocks)
        else:
            self._report(f"  第{page_num+1}页: 扫描件，启用OCR识别...", 0)
            return self._scan_ocr_page(page, page_num)

    # ------------------------------------------------------------------
    # 文字层扫描
    # ------------------------------------------------------------------

    def _scan_text_page(
        self, page: fitz.Page, page_num: int, text_blocks: list
    ) -> list[DetectionResult]:
        """对含文字层的页面执行模式匹配。"""
        detections: list[DetectionResult] = []

        for block in text_blocks:
            text = block[4]

            for pattern_type, pattern, is_tier1 in PATTERN_LIST:
                for match in pattern.finditer(text):
                    matched_text = match.group()

                    if not is_tier1 and match.groups():
                        captured = match.group(1) if match.lastindex else match.group()
                        target = captured
                    else:
                        target = matched_text

                    target = target.strip()
                    if not target:
                        continue

                    if pattern_type != "医疗机构" and is_hospital_or_department(matched_text):
                        continue
                    if pattern_type in ("患者姓名", "医生护士") and is_invalid_name(target):
                        continue

                    rects = page.search_for(target)
                    if not rects and target != matched_text:
                        rects = page.search_for(matched_text)
                    if not rects:
                        rects = self._fallback_locate(page, target, block)

                    if rects:
                        detections.append(
                            DetectionResult(page_num, pattern_type, target, rects)
                        )

        return detections

    # ------------------------------------------------------------------
    # OCR扫描（扫描件）
    # ------------------------------------------------------------------

    def _scan_ocr_page(
        self, page: fitz.Page, page_num: int
    ) -> list[DetectionResult]:
        """对扫描件页面执行OCR识别 + 模式匹配。"""
        detections: list[DetectionResult] = []

        # 渲染页面为高分辨率图像
        pix = page.get_pixmap(dpi=OCR_DPI)
        img_data = pix.tobytes("ppm")
        image = Image.open(io.BytesIO(img_data))

        # OCR识别，获取词级坐标
        try:
            ocr_data = pytesseract.image_to_data(
                image, lang=OCR_LANG, output_type=pytesseract.Output.DICT,
                config="--psm 4",  # 单列可变大小文本
            )
            words_found = sum(1 for t in ocr_data["text"] if t.strip())
            self._report(f"    OCR完成: tesseract={pytesseract.pytesseract.tesseract_cmd}, "
                         f"lang={OCR_LANG}, 识别词数={words_found}, "
                         f"页面尺寸={pix.width}x{pix.height}")
        except Exception as e:
            self._report(f"    OCR失败: {e}", 0)
            return []

        # 将OCR结果按行分组
        lines = self._group_ocr_lines(ocr_data)

        # 缩放因子：图像像素 → PDF坐标
        scale = 72.0 / OCR_DPI

        for line_text, line_words in lines:
            for pattern_type, pattern, is_tier1 in PATTERN_LIST:
                for match in pattern.finditer(line_text):
                    matched_text = match.group()

                    if not is_tier1 and match.groups():
                        captured = match.group(1) if match.lastindex else match.group()
                        target = captured
                    else:
                        target = matched_text

                    target = target.strip()
                    if not target:
                        continue

                    if pattern_type != "医疗机构" and is_hospital_or_department(matched_text):
                        continue
                    if pattern_type in ("患者姓名", "医生护士") and is_invalid_name(target):
                        continue

                    # 在行文本中定位target的位置
                    idx = line_text.find(target)
                    if idx == -1:
                        continue

                    # Tier2 模式：过滤低置信度OCR结果
                    if not is_tier1:
                        char_pos = 0
                        target_confs = []
                        for w in line_words:
                            w_end_pos = char_pos + len(w["text"])
                            if w_end_pos > idx and char_pos < idx + len(target):
                                if w["conf"] >= 0:
                                    target_confs.append(w["conf"])
                            char_pos = w_end_pos
                        avg_conf = sum(target_confs) / len(target_confs) if target_confs else 0
                        if avg_conf < OCR_CONFIDENCE_MIN:
                            continue

                    # 累积字符位置，找到覆盖target的OCR词
                    rects = self._ocr_target_rects(
                        line_words, idx, idx + len(target), scale
                    )
                    if rects:
                        detections.append(
                            DetectionResult(page_num, pattern_type, target, rects)
                        )

        return detections

    def _group_ocr_lines(self, ocr_data: dict) -> list[tuple[str, list[dict]]]:
        """将OCR词级结果按Y坐标分组为行。"""
        entries = []
        for i in range(len(ocr_data["text"])):
            text = ocr_data["text"][i].strip()
            conf = ocr_data["conf"][i]
            if not text or conf < 0:
                continue
            entries.append({
                "text": text,
                "x": ocr_data["left"][i],
                "y": ocr_data["top"][i],
                "w": ocr_data["width"][i],
                "h": ocr_data["height"][i],
                "conf": conf,
            })

        if not entries:
            return []

        # 按Y坐标排序，然后按X坐标排序
        entries.sort(key=lambda e: (e["y"], e["x"]))

        # 基于Y坐标聚类：相邻词Y差小于平均字高的0.6倍视为同一行
        heights = [e["h"] for e in entries if e["h"] > 0]
        avg_height = sum(heights) / len(heights) if heights else 20
        y_threshold = max(avg_height * 0.6, 5)

        lines = []
        current_line = [entries[0]]
        current_y = entries[0]["y"]

        for e in entries[1:]:
            if abs(e["y"] - current_y) < y_threshold:
                current_line.append(e)
            else:
                current_line.sort(key=lambda w: w["x"])
                line_text = "".join(w["text"] for w in current_line)
                lines.append((line_text, current_line))
                current_line = [e]
                current_y = e["y"]

        if current_line:
            current_line.sort(key=lambda w: w["x"])
            line_text = "".join(w["text"] for w in current_line)
            lines.append((line_text, current_line))

        return lines

    def _ocr_target_rects(
        self, line_words: list[dict], start: int, end: int, scale: float
    ) -> list[fitz.Rect]:
        """定位覆盖target字符范围的OCR词，转换为PDF坐标。"""
        char_pos = 0
        rects = []
        for w in line_words:
            w_start = char_pos
            w_end = char_pos + len(w["text"])
            char_pos = w_end

            if w_end > start and w_start < end:
                rects.append(fitz.Rect(
                    w["x"] * scale,
                    w["y"] * scale,
                    (w["x"] + w["w"]) * scale,
                    (w["y"] + w["h"]) * scale,
                ))

        return rects

    # ------------------------------------------------------------------
    # 降级定位：当 search_for() 无法找到文本时
    # ------------------------------------------------------------------

    def _fallback_locate(
        self, page: fitz.Page, target: str, block: tuple
    ) -> list[fitz.Rect]:
        """通过 word 级文本提取重建目标文本坐标。"""
        try:
            words = page.get_text("words")
        except Exception:
            return []

        bx0, by0, bx1, by1 = block[0], block[1], block[2], block[3]
        block_rect = fitz.Rect(bx0, by0, bx1, by1)

        block_words = [
            w for w in words
            if fitz.Rect(w[0], w[1], w[2], w[3]).intersects(block_rect)
        ]

        if not block_words:
            return []

        block_words.sort(key=lambda w: (round(w[1], 1), w[0]))

        lines: list[list] = []
        current_line = []
        current_y = None

        for w in block_words:
            wy = round(w[1], 1)
            if current_y is None or abs(wy - current_y) < 5:
                current_line.append(w)
            else:
                if current_line:
                    lines.append(current_line)
                current_line = [w]
            current_y = wy
        if current_line:
            lines.append(current_line)

        for line_words in lines:
            line_text = "".join(w[4] for w in line_words)
            idx = line_text.find(target)
            if idx == -1:
                continue

            char_pos = 0
            target_rects = []
            for w in line_words:
                w_text = w[4]
                w_start = char_pos
                w_end = char_pos + len(w_text)
                char_pos = w_end

                if w_end > idx and w_start < idx + len(target):
                    target_rects.append(fitz.Rect(w[0], w[1], w[2], w[3]))

            if target_rects:
                return target_rects

        return []
