"""
downloader.py — wrapper فوق yt-dlp لتحميل الفيديوهات والصوتيات
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path

import yt_dlp

logger = logging.getLogger(__name__)

TEMP_DIR = Path(tempfile.gettempdir()) / "tg_dl_bot"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# خيارات مشتركة لتقليل الضوضاء في السجلات
_BASE_OPTS: dict = {
    "quiet":            True,
    "no_warnings":      True,
    "noplaylist":       True,
    "socket_timeout":   30,
    "retries":          3,
    "fragment_retries": 3,
}


def _sanitize(name: str, max_len: int = 60) -> str:
    """يزيل الأحرف غير المسموح بها في أسماء الملفات."""
    name = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    return name[:max_len] or "download"


# ══════════════════════════════════════════════
#  get_info
# ══════════════════════════════════════════════
def get_info(url: str) -> dict:
    """
    يجلب بيانات الفيديو بدون تحميل.
    يرجع dict يحتوي على: title, uploader, duration, view_count, thumbnail …
    """
    opts = {
        **_BASE_OPTS,
        "extract_flat": False,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    return info or {}


# ══════════════════════════════════════════════
#  download_media
# ══════════════════════════════════════════════
def download_media(url: str, fmt: str, quality: str) -> tuple[str, str]:
    """
    يحمّل الملف ويرجع (out_path, out_name).

    fmt: "video" | "audio"
    quality:
        video → "2160" | "1440" | "1080" | "720" | "480" | "360"
        audio → "320"  | "192"  | "128"  | "64"
    """
    out_tmpl = str(TEMP_DIR / "%(id)s.%(ext)s")

    if fmt == "audio":
        opts = _audio_opts(quality, out_tmpl)
    else:
        opts = _video_opts(quality, out_tmpl)

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)

    if not info:
        raise RuntimeError("لم يتم استخراج معلومات الفيديو.")

    # تحديد مسار الملف المحمّل
    out_path = _resolve_path(ydl, info)
    if not out_path or not os.path.exists(out_path):
        # fallback: ابحث عن الملف في المجلد المؤقت
        vid_id = info.get("id", "")
        matches = list(TEMP_DIR.glob(f"{vid_id}.*"))
        if not matches:
            raise FileNotFoundError("لم يُعثر على الملف بعد التحميل.")
        out_path = str(max(matches, key=lambda p: p.stat().st_size))

    title   = _sanitize(info.get("title") or "download")
    ext     = Path(out_path).suffix.lstrip(".")
    out_name = f"{title}.{ext}"

    logger.info("Downloaded — path=%s size=%d", out_path, os.path.getsize(out_path))
    return out_path, out_name


# ══════════════════════════════════════════════
#  الأوبشنز الخاصة بكل صيغة
# ══════════════════════════════════════════════
def _video_opts(quality: str, out_tmpl: str) -> dict:
    q = int(quality)
    # نحاول أفضل جودة متاحة <= المطلوبة
    fmt_selector = (
        f"bestvideo[height<={q}][ext=mp4]+bestaudio[ext=m4a]"
        f"/bestvideo[height<={q}]+bestaudio"
        f"/best[height<={q}]"
        "/best"
    )
    return {
        **_BASE_OPTS,
        "format":          fmt_selector,
        "outtmpl":         out_tmpl,
        "merge_output_format": "mp4",
        "postprocessors": [
            {
                "key":            "FFmpegVideoConvertor",
                "preferedformat": "mp4",
            }
        ],
    }


def _audio_opts(quality: str, out_tmpl: str) -> dict:
    return {
        **_BASE_OPTS,
        "format":    "bestaudio/best",
        "outtmpl":   out_tmpl,
        "postprocessors": [
            {
                "key":            "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": quality,
            }
        ],
    }


# ══════════════════════════════════════════════
#  مساعد لتحديد مسار الملف
# ══════════════════════════════════════════════
def _resolve_path(ydl: yt_dlp.YoutubeDL, info: dict) -> str | None:
    try:
        return ydl.prepare_filename(info)
    except Exception:
        pass

    # fallback للملفات المُحوَّلة (مثلاً mp3 بعد extraction)
    entries = info.get("requested_downloads") or []
    if entries:
        return entries[0].get("filepath") or entries[0].get("filename")

    return None
