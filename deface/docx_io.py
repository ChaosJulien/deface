"""docx 图片抽取与重打包。

docx 本质是 zip,图片放在 `word/media/*`(还有 `word/embeddings`、header/footer
也可能含图)。引用走 relationship,只要保留原文件名替换 bytes,所有引用都还是好的。
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
# Word 把图片塞在这些目录下;扩展模板也可能放更冷门路径,前缀匹配能兜底。
MEDIA_DIRS = ("word/media/", "word/embeddings/")


@dataclass
class DocxImage:
    arcname: str          # zip 内的相对路径,作为唯一 ID,例 "word/media/image1.png"
    data: bytes           # 原始字节
    suffix: str           # 小写后缀,例 ".png"


def _is_image_arcname(name: str) -> bool:
    if not name.startswith(MEDIA_DIRS):
        return False
    return Path(name).suffix.lower() in IMAGE_EXTS


def extract_images(docx_path: Path) -> List[DocxImage]:
    """读 docx,返回所有图片条目(保持 zip 内原顺序)。"""
    images: List[DocxImage] = []
    with zipfile.ZipFile(docx_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            if not _is_image_arcname(info.filename):
                continue
            images.append(
                DocxImage(
                    arcname=info.filename,
                    data=zf.read(info.filename),
                    suffix=Path(info.filename).suffix.lower(),
                )
            )
    return images


def write_docx(
    src_docx: Path,
    dst_docx: Path,
    replacements: Dict[str, bytes],
) -> None:
    """复制 src_docx 到 dst_docx,把 replacements 里的条目替换为新字节。

    其它条目(document.xml、relationships、styles 等)按原顺序、原压缩等级
    完整复制,确保 Word 能正常打开。
    """
    src_docx = Path(src_docx)
    dst_docx = Path(dst_docx)
    if dst_docx.resolve() == src_docx.resolve():
        raise ValueError("dst_docx 不能和 src_docx 相同")
    dst_docx.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(src_docx, "r") as zin, zipfile.ZipFile(
        dst_docx, "w", compression=zipfile.ZIP_DEFLATED
    ) as zout:
        for info in zin.infolist():
            if info.filename in replacements:
                # 用 ZipInfo 保原 mtime / 属性,只换内容
                new_info = zipfile.ZipInfo(filename=info.filename, date_time=info.date_time)
                new_info.compress_type = info.compress_type or zipfile.ZIP_DEFLATED
                new_info.external_attr = info.external_attr
                zout.writestr(new_info, replacements[info.filename])
            else:
                # 直接透传,避免 zipfile 因解压再压而改 CRC / 顺序
                data = zin.read(info.filename)
                new_info = zipfile.ZipInfo(filename=info.filename, date_time=info.date_time)
                new_info.compress_type = info.compress_type
                new_info.external_attr = info.external_attr
                zout.writestr(new_info, data)
