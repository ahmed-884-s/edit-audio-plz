"""
downloader.py — تحميل الميديا عبر yt-dlp
"""

from __future__ import annotations

import os
import tempfile
import logging
from pathlib import Path

import yt_dlp

logger = logging.getLogger(__name__)

# ───────────────────────────── constants ──────────────────────────────

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_COMMON = {
    "quiet":            True,
    "no_warnings":      True,
    "noplaylist":       True,
    "socket_timeout":   30,
    "retries":          5,
    "fragment_retries": 5,
    "http_headers":     {"User-Agent": _UA},
}

# ───────────────────────────── helpers ────────────────────────────────

def _fmt_duration(secs: int | float | None) -> str:
    if not secs:
        return "—"
    secs = int(secs)
    h, rem = divmod(secs, 3600)
    m, s   = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _largest_file(directory: str) -> Path:
    files = [p for p in Path(directory).iterdir() if p.is_file()]
    if not files:
        raise RuntimeError("لم يُنشأ أي ملف بعد التحميل!")
    return max(files, key=lambda p: p.stat().st_size)


# ───────────────────────────── public API ─────────────────────────────

def get_info(url: str) -> dict:
    """يجيب metadata الفيديو من غير ما ينزّل حاجة."""
    opts = {**_COMMON, "skip_download": True, "socket_timeout": 20}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return info or {}


def download_media(url: str, fmt: str, quality: str) -> tuple[str, str]:
    """
    ينزّل الميديا ويرجع (file_path, file_name).

    Parameters
    ----------
    url     : رابط الفيديو
    fmt     : "video" | "audio"
    quality : "1080" / "720" / "480" / "360"  للفيديو
              "320"  / "128"                   للصوت
    """
    tmp_dir = tempfile.mkdtemp()
    opts    = {
        **_COMMON,
        "outtmpl": os.path.join(tmp_dir, "%(title).80s.%(ext)s"),
    }

    if fmt == "audio":
        opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key":              "FFmpegExtractAudio",
                "preferredcodec":   "mp3",
                "preferredquality": quality,
            }],
        })
    else:
        opts["format"] = (
            f"bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]"
            f"/bestvideo[height<={quality}]+bestaudio"
            f"/best[height<={quality}]"
            "/best"
        )
        opts["merge_output_format"] = "mp4"

    logger.info("Downloading %s  fmt=%s  quality=%s", url, fmt, quality)

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.extract_info(url, download=True)

    out = _largest_file(tmp_dir)
    return str(out), out.name
