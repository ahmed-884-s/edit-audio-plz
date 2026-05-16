"""
downloader.py — wrapper فوق yt-dlp
يدعم جلب الجودات المتاحة فعلاً + حل مشكلة YouTube bot detection
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import tempfile

import yt_dlp

logger = logging.getLogger(__name__)

# ─── Auto-update yt-dlp عند الشغيل (مهم جداً لـ Railway) ───────────────────
def _auto_update_ytdlp() -> None:
    """بتحدث yt-dlp تلقائياً لحل مشاكل YouTube اللي بتتغير باستمرار."""
    try:
        logger.info("🔄 جاري تحديث yt-dlp...")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "--upgrade", "yt-dlp"],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            logger.info("✅ yt-dlp تم تحديثه بنجاح")
        else:
            logger.warning("⚠️ تحديث yt-dlp: %s", result.stderr[:200])
    except Exception as e:
        logger.warning("⚠️ فشل تحديث yt-dlp: %s", e)

# شغّل التحديث مرة واحدة عند import المودول
_auto_update_ytdlp()

# ─── إعدادات yt-dlp الأساسية لتجاوز bot detection ──────────────────────────
_BASE_OPTS: dict = {
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    # الحل الرئيسي لـ YouTube bot detection على datacenter IPs
    "extractor_args": {
        "youtube": {
            "player_client": ["mweb", "web_embedded", "web"],
        }
    },
    "http_headers": {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 13; SM-G991B) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Mobile Safari/537.36"
        )
    },
}

# ─── جلب معلومات الفيديو ────────────────────────────────────────────────────
def get_info(url: str) -> dict:
    """يرجع dict بمعلومات الفيديو (بدون تحميل)."""
    opts = {**_BASE_OPTS, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False) or {}


# ─── جلب الجودات المتاحة فعلاً ─────────────────────────────────────────────
def get_available_qualities(url: str) -> dict:
    """
    يرجع dict:
    {
        "video": ["1080", "720", "480", "360"],   # الجودات المتاحة
        "audio": ["320", "128"],                   # دايماً متاح لو في صوت
        "title": "عنوان الفيديو",
        "uploader": "القناة",
        "duration": 123,
        "view_count": 45678,
        "has_video": True,
        "has_audio": True,
    }
    """
    info = get_info(url)
    formats = info.get("formats") or []

    # ── استخرج الجودات الفيديو المتاحة ──────────────────────────────────
    video_heights: list[int] = []
    has_audio = False

    for f in formats:
        h = f.get("height")
        vcodec = f.get("vcodec", "none")
        acodec = f.get("acodec", "none")

        if vcodec and vcodec != "none" and h:
            video_heights.append(int(h))

        if acodec and acodec != "none":
            has_audio = True

    # رتّب وادّي القيم الفريدة فقط
    STANDARD_HEIGHTS = [2160, 1440, 1080, 720, 480, 360, 240]
    available_video: list[str] = []
    for target in STANDARD_HEIGHTS:
        # لو في جودة ± 10% من الجودة المطلوبة
        if any(abs(h - target) <= target * 0.15 for h in video_heights):
            available_video.append(str(target))

    # لو مفيش جودات واضحة، استخدم fallback من الجودات الموجودة
    if not available_video and video_heights:
        for h in sorted(set(video_heights), reverse=True)[:4]:
            available_video.append(str(h))

    # الصوت دايماً 320k و128k لو في صوت
    available_audio = ["320", "128"] if has_audio or not available_video else []

    return {
        "video": available_video,
        "audio": available_audio,
        "title": (info.get("title") or "بدون عنوان")[:80],
        "uploader": info.get("uploader") or info.get("channel") or "—",
        "duration": info.get("duration"),
        "view_count": info.get("view_count"),
        "has_video": bool(available_video),
        "has_audio": bool(available_audio),
        "thumbnail": info.get("thumbnail"),
        "webpage_url": info.get("webpage_url") or url,
    }


# ─── التحميل ────────────────────────────────────────────────────────────────
def download_media(url: str, fmt: str, quality: str) -> tuple[str, str]:
    """
    يحمّل الوسيط ويرجع (out_path, out_name).
    fmt: "video" | "audio"
    quality: "1080" | "720" | "480" | "360" | "320" | "128"
    """
    tmpdir = tempfile.mkdtemp()

    if fmt == "audio":
        # ── صوت MP3 ────────────────────────────────────────────────────
        audio_quality = "0" if quality == "320" else "5"  # 0=320k, 5=128k
        opts = {
            **_BASE_OPTS,
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": quality,
            }],
            "outtmpl": os.path.join(tmpdir, "%(title).60s.%(ext)s"),
        }
    else:
        # ── فيديو MP4 ───────────────────────────────────────────────────
        h = quality
        # جرّب الجودة المطلوبة، لو مش موجودة خد أقرب جودة أقل
        fmt_selector = (
            f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/"
            f"bestvideo[height<={h}]+bestaudio/"
            f"best[height<={h}]/"
            "best"
        )
        opts = {
            **_BASE_OPTS,
            "format": fmt_selector,
            "merge_output_format": "mp4",
            "postprocessors": [{
                "key": "FFmpegVideoConvertor",
                "preferedformat": "mp4",
            }],
            "outtmpl": os.path.join(tmpdir, "%(title).60s.%(ext)s"),
        }

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    # ابحث عن الملف اللي اتحمّل
    files = [f for f in os.listdir(tmpdir) if not f.endswith(".part")]
    if not files:
        raise FileNotFoundError("لم يُحمَّل أي ملف — تحقق من الرابط أو الجودة")

    # اختار الملف الأكبر (الفيديو الرئيسي)
    files.sort(key=lambda f: os.path.getsize(os.path.join(tmpdir, f)), reverse=True)
    chosen = files[0]
    out_path = os.path.join(tmpdir, chosen)

    # تنظيف اسم الملف
    safe_name = re.sub(r'[^\w\s\-\u0600-\u06FF.]', '', chosen)[:80]
    safe_name = safe_name or f"video_{quality}.mp4"

    return out_path, safe_name
