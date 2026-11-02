"""图片上传共用处理：校验、Pillow 缩放压缩、转 base64 data URL（供多模态 LLM 使用）。

局域网手机端经 <input capture> 拍照直传原图（可达数 MB），统一在此服务端缩放，
控制多模态请求体积与 token 消耗。
"""
import base64
import io

from fastapi import HTTPException, UploadFile
from PIL import Image

# 单张原图上限（手机直出 JPEG 通常 2~8MB）
MAX_IMAGE_BYTES = 10 * 1024 * 1024
# 自设像素帽（5000 万像素 ≈ 8000×6000）：Pillow 默认炸弹阈值 89M~179M px 区间仅
# warning 仍全量解码（约 0.5GB RGB 位图），这里收紧到安全区间
_MAX_PIXELS = 50_000_000
# 压缩后最长边与 JPEG 质量：1600px 在文档/题目拍摄场景下 OCR 细节与体积的最佳平衡
_MAX_SIDE = 1600
_JPEG_QUALITY = 82


def _check_image(upload: UploadFile, index: int) -> bytes:
    """校验并读取单张图片：先 seek 到尾部取真实大小再读，杜绝先整读进内存的 RAM 尖峰。"""
    name = upload.filename or f"image_{index + 1}"
    ctype = (upload.content_type or "").lower()
    if not ctype.startswith("image/"):
        raise HTTPException(status_code=400, detail=f"第 {index + 1} 个文件不是图片（收到：{name}），仅支持拍照或图片上传")
    f = upload.file
    f.seek(0, 2)  # 文件部分是 SpooledTemporaryFile：先取大小再有界读取
    size = f.tell()
    f.seek(0)
    if size == 0:
        raise HTTPException(status_code=400, detail=f"第 {index + 1} 个文件为空（{name}）")
    if size > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"第 {index + 1} 张图片超过 10MB 上限（{name}），请拍摄后适当裁剪再上传",
        )
    return f.read(size)


def compress_to_data_urls(uploads: list[UploadFile], max_count: int) -> list[str]:
    """校验并压缩上传图片，返回 data URL 列表（image/jpeg;base64）。

    超出 max_count 报 400；EXIF 方向自动转正（手机竖拍照片必需）。
    """
    if not uploads:
        raise HTTPException(status_code=400, detail="请先拍照或选择图片")
    if len(uploads) > max_count:
        raise HTTPException(status_code=400, detail=f"最多上传 {max_count} 张图片")

    data_urls: list[str] = []
    for i, upload in enumerate(uploads):
        raw = _check_image(upload, i)
        try:
            img = Image.open(io.BytesIO(raw))
            if img.width * img.height > _MAX_PIXELS:
                raise HTTPException(
                    status_code=400,
                    detail=f"第 {i + 1} 张图片尺寸过大（{img.width}×{img.height}），请缩小后再上传",
                )
            # 手机竖拍带 EXIF Orientation：不经 transpose 会横倒
            from PIL import ImageOps

            img = ImageOps.exif_transpose(img)
            if img.mode != "RGB":
                # PNG 透明通道 / 灰度统一转 RGB，JPEG 不支持透明
                img = img.convert("RGB")
            w, h = img.size
            if max(w, h) > _MAX_SIDE:
                scale = _MAX_SIDE / max(w, h)
                img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=_JPEG_QUALITY)
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            data_urls.append(f"data:image/jpeg;base64,{b64}")
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise HTTPException(
                status_code=400, detail=f"第 {i + 1} 张图片无法解析（{upload.filename or '未命名'}）：{e}"
            ) from e
    return data_urls


def build_vision_messages(system_prompt: str, instruction: str, data_urls: list[str]) -> list[dict]:
    """构造多模态 messages：system + user（文本指令在前，图片 data URL 按序跟随）。"""
    content: list[dict] = [{"type": "text", "text": instruction}]
    for url in data_urls:
        content.append({"type": "image_url", "image_url": {"url": url}})
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content},
    ]
