"""轻量 PDF 提取（pypdfium2，Apache-2.0）：文本层直取 + 扫描版栅格化。

设计取向：不引重型 OCR 依赖。有文本层的 PDF 直接抽取文本（零 LLM 零消耗）；
扫描版/图片型 PDF 栅格化成页图后，复用既有视觉转写链路（import_transcribe prompt）。
"""
import base64
import io

from fastapi import HTTPException

# 扫描版 PDF 单次视觉转写的页数上限（讲义级分批导入）
MAX_OCR_PAGES = 16
# 栅格化长边与 JPEG 质量：与拍照导入对齐（1600px 在文档 OCR 细节与体积间的最佳平衡）
_RENDER_MAX_SIDE = 1600
# 栅格化像素总量帽（40MP ≈ 拍照路径 60MP 帽的 2/3，防超大 MediaBox 巨型位图）
_MAX_RENDER_PIXELS = 40_000_000
_JPEG_QUALITY = 82


def extract_pdf_text(data: bytes) -> tuple[str, int]:
    """提取 PDF 全部文本层，页间以空行连接。返回 (text, page_count)。

    无法解析（损坏/加密）时抛异常，由调用方转 400。
    """
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(data)
    try:
        parts: list[str] = []
        page_count = 0
        for page in doc:
            page_count += 1
            textpage = page.get_textpage()
            try:
                parts.append(textpage.get_text_bounded() or "")
            finally:
                textpage.close()
                page.close()
        return "\n\n".join(parts), page_count
    finally:
        doc.close()


def pdf_needs_ocr(text: str, page_count: int) -> bool:
    """判断 PDF 是否为扫描版/图片型：文本总量低于阈值（平均每页约 30 字符，下限 200）。"""
    return len((text or "").strip()) < max(200, page_count * 30)


def rasterize_pdf_to_data_urls(data: bytes, max_pages: int = MAX_OCR_PAGES) -> list[str]:
    """逐页渲染为 JPEG data URL（长边 ~1600px），供视觉模型转写扫描版 PDF。

    超过 max_pages 报 400（提示分批），防止一次视觉请求打包几十页拖垮上下文。
    """
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(data)
    try:
        page_count = len(doc)
        if page_count > max_pages:
            raise HTTPException(
                status_code=400,
                detail=f"该扫描版 PDF 共 {page_count} 页，超过单次转写上限 {max_pages} 页，请拆分后分批导入",
            )
        data_urls: list[str] = []
        for page in doc:
            w, h = page.get_size()
            # 像素帽反推 scale（v0.5.3 体检 P3）：此前 max(0.5, ...) 下限会让超大 MediaBox
            # （>3200pt）渲染出巨型位图（数百 MB 内存，且在线程池内执行）；对照 images 路径有 60MP 帽
            scale = _RENDER_MAX_SIDE / max(w, h, 1.0)
            if w * h * scale * scale > _MAX_RENDER_PIXELS:
                scale = (_MAX_RENDER_PIXELS / (w * h)) ** 0.5
            bitmap = page.render(scale=scale)
            try:
                pil = bitmap.to_pil()
            finally:
                bitmap.close()
                page.close()
            if pil.mode != "RGB":
                pil = pil.convert("RGB")
            buf = io.BytesIO()
            pil.save(buf, format="JPEG", quality=_JPEG_QUALITY)
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            data_urls.append(f"data:image/jpeg;base64,{b64}")
        return data_urls
    finally:
        doc.close()
