import csv
import os
from typing import List

import aiofiles

import config
from media_platform.jd.field import LicenseInfo
from tools import utils


async def save_license_image(license_info: LicenseInfo, image_data: bytes):
    """保存营业执照图片到本地，并追加 CSV 元数据"""
    save_dir = config.JD_LICENSE_SAVE_DIR or "data/jd/licenses"

    # 用 shop_id+shop_name 作为子目录，清理非法文件名字符
    safe_name = _safe_filename(f"{license_info.shop_id}_{license_info.shop_name}")
    shop_dir = os.path.join(save_dir, safe_name)
    os.makedirs(shop_dir, exist_ok=True)

    # 从 URL 推断文件扩展名
    ext = _ext_from_url(license_info.license_image_url)
    filename = f"license{ext}"
    filepath = os.path.join(shop_dir, filename)

    async with aiofiles.open(filepath, "wb") as f:
        await f.write(image_data)

    license_info.local_path = filepath
    utils.logger.info(f"[jd_store] 营业执照已保存: {filepath}")

    # 追加 CSV 元数据
    await _append_csv_metadata(license_info)


async def _append_csv_metadata(license_info: LicenseInfo):
    """将执照信息追加到 CSV"""
    csv_path = config.JD_METADATA_CSV_PATH or "data/jd/shop_licenses.csv"
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)

    write_header = not os.path.exists(csv_path)

    async with aiofiles.open(csv_path, "a", encoding="utf-8", newline="") as f:
        if write_header:
            await f.write("shop_id,shop_name,license_type,license_image_url,local_path\n")
        line = (
            f'"{license_info.shop_id}",'
            f'"{license_info.shop_name}",'
            f'"{license_info.license_type}",'
            f'"{license_info.license_image_url}",'
            f'"{license_info.local_path}"\n'
        )
        await f.write(line)


def _safe_filename(name: str) -> str:
    """清理文件名中的非法字符"""
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, "_")
    return name.strip("_ ")[:100]


def _ext_from_url(url: str) -> str:
    """从 URL 推断图片扩展名"""
    url_lower = url.lower().split("?")[0]
    if url_lower.endswith(".webp"):
        return ".webp"
    elif url_lower.endswith(".png"):
        return ".png"
    elif url_lower.endswith(".gif"):
        return ".gif"
    elif url_lower.endswith(".jpg") or url_lower.endswith(".jpeg"):
        return ".jpg"
    # 京东图片 URL 格式如 .jpg.webp，去掉 .webp 后是 jpg
    if ".jpg.webp" in url_lower or ".jpeg.webp" in url_lower:
        return ".jpg"
    if ".png.webp" in url_lower:
        return ".png"
    return ".jpg"
