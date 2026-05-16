"""
editor.py — تعديل الوسائط باستخدام FFmpeg
(يمكن توسيعه لاحقاً لإضافة ميزات القطع / الضغط / تغيير الصوت …)
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def trim_media(input_path: str, output_path: str, start: str, end: str) -> str:
    """
    يقطع الوسائط من start إلى end.
    start / end بالصيغة "HH:MM:SS" أو "SS".
    يرجع مسار الملف الناتج.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-ss", start,
        "-to", end,
        "-c", "copy",
        output_path,
    ]
    _run(cmd)
    return output_path


def convert_to_mp3(input_path: str, output_path: str, bitrate: str = "192k") -> str:
    """يحوّل أي ملف وسائط إلى MP3."""
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vn",
        "-ar", "44100",
        "-ac", "2",
        "-b:a", bitrate,
        output_path,
    ]
    _run(cmd)
    return output_path


def get_duration(path: str) -> float | None:
    """يرجع مدة الملف بالثواني، أو None في حالة الخطأ."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return float(result.stdout.strip())
    except Exception as exc:
        logger.warning("get_duration failed: %s", exc)
        return None


def _run(cmd: list[str], timeout: int = 120) -> None:
    logger.debug("FFmpeg cmd: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg error:\n{result.stderr[-500:]}")
