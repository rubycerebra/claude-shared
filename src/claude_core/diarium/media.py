"""Diarium image/media extraction — extracted from claude_core.diarium_ingest."""
from __future__ import annotations

import re
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

IMAGE_CACHE_DIR = Path.home() / ".claude" / "cache" / "diarium-images"


def extract_images_from_docx(file_path, date_str=None):
    """Extract images from DOCX file and return file:// URLs"""
    file_path = Path(file_path)
    images = []

    if file_path.suffix != '.docx':
        return images

    IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if date_str is None:
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', file_path.name)
        date_str = date_match.group(1) if date_match else datetime.now().strftime('%Y-%m-%d')

    try:
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            media_files = [f for f in zip_ref.namelist() if f.startswith('media/')]

            for i, media_file in enumerate(media_files, 1):
                ext = Path(media_file).suffix.lower()
                if ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                    continue

                cached_filename = f"{date_str}_image{i}{ext}"
                cached_path = IMAGE_CACHE_DIR / cached_filename

                with zip_ref.open(media_file) as src:
                    with open(cached_path, 'wb') as dst:
                        dst.write(src.read())

                file_url = f"file://{quote(str(cached_path))}"

                images.append({
                    'filename': cached_filename,
                    'path': str(cached_path),
                    'url': file_url,
                    'size': cached_path.stat().st_size
                })

    except Exception as e:
        images.append({'error': str(e)})

    return images


def extract_images_from_diarium_zip(file_path, date_str=None):
    """Extract images from Diarium ZIP export media folder."""
    file_path = Path(file_path)
    images = []

    if file_path.suffix.lower() != '.zip':
        return images

    IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if date_str is None:
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', file_path.name)
        date_str = date_match.group(1) if date_match else datetime.now().strftime('%Y-%m-%d')

    try:
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            media_files = [f for f in zip_ref.namelist() if f.startswith('media/')]

            for i, media_file in enumerate(media_files, 1):
                ext = Path(media_file).suffix.lower()
                if ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                    continue

                cached_filename = f"{date_str}_image{i}{ext}"
                cached_path = IMAGE_CACHE_DIR / cached_filename

                with zip_ref.open(media_file) as src:
                    with open(cached_path, 'wb') as dst:
                        dst.write(src.read())

                file_url = f"file://{quote(str(cached_path))}"
                images.append({
                    'filename': cached_filename,
                    'path': str(cached_path),
                    'url': file_url,
                    'size': cached_path.stat().st_size
                })
    except Exception as e:
        images.append({'error': str(e)})

    return images


def extract_images_from_file(file_path, date_str=None):
    file_path = Path(file_path)
    suffix = file_path.suffix.lower()

    if suffix == '.zip':
        return extract_images_from_diarium_zip(file_path, date_str=date_str)
    if suffix == '.docx':
        return extract_images_from_docx(file_path, date_str=date_str)
    return []
