"""
downloader.py — wrapper فوق yt-dlp
الإصلاح الرئيسي لـ YouTube: يستخدم ios + web_creator clients مع JS runtime detection
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


# ─── Auto-update yt-dlp عند الشغيل ─────────────────────────────────────────
def _auto_update_ytdlp() -> None:
    try:
        logger.info("🔄 جاري تحديث yt-dlp...")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "--upgrade", "yt-dlp"],
            capture_output=True, text=True, timeout=90,
        )
        if result.returncode == 0:
            logger.info("✅ yt-dlp محدّث")
        else:
            logger.warning("⚠️ yt-dlp update: %s", result.stderr[:200])
    except Exception as e:
        logger.warning("⚠️ فشل تحديث yt-dlp: %s", e)


_auto_update_ytdlp()


# ─── إيجاد JS runtime ──────────────────────────────────────────────────────
def _find_js_runtime() -> list[str]:
    """يحاول يلاقي Deno أو Node، ويرجع القيمة المناسبة لـ js_runtimes."""
    for binary in ("deno", "node", "nodejs"):
        try:
            result = subprocess.run(
                ["which", binary], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                path = result.stdout.strip()
                logger.info("✅ JS runtime: %s (%s)", binary, path)
                return [f"{binary}:{path}"]
        except Exception:
            pass
    logger.warning("⚠️ مفيش JS runtime (Deno/Node) — YouTube ممكن يفشل!")
    return []


_JS_RUNTIMES = _find_js_runtime()


# ─── الإعدادات الأساسية ────────────────────────────────────────────────────
def _build_base_opts(extra: dict | None = None) -> dict:
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        # ios هو الأكثر استقراراً في 2026 مع datacenter IPs
        "extractor_args": {
            "youtube": {
                "player_client": ["ios", "web_creator", "web_embedded"],
            }
        },
        "http_headers": {
            "User-Agent": (
                "com.google.ios.youtube/19.29.1 "
                "(iPhone16,2; U; CPU iOS 17_5_1 like Mac OS X)"
            )
        },
    }
    if _JS_RUNTIMES:
        opts["js_runtimes"] = _JS_RUNTIMES

    if extra:
        opts.update(extra)
    return opts


# ─── جلب المعلومات ─────────────────────────────────────────────────────────
def get_info(url: str) -> dict:
    opts = _build_base_opts({"skip_download": True})
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False) or {}


# ─── جلب الجودات المتاحة فعلاً ────────────────────────────────────────────
def get_available_qualities(url: str) -> dict:
    """
    يرجع dict:
      video: ["1080", "720", ...]
      audio: ["320", "128"]
      title, uploader, duration, view_count
    """
    info = get_info(url)
    formats = info.get("formats") or []

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

    STANDARD = [2160, 1440, 1080, 720, 480, 360, 240]
    available_video: list[str] = []
    for target in STANDARD:
        if any(abs(h - target) <= target * 0.15 for h in video_heights):
            available_video.append(str(target))

    if not available_video and video_heights:
        for h in sorted(set(video_heights), reverse=True)[:4]:
            available_video.append(str(h))

    available_audio = ["320", "128"] if (has_audio or not available_video) else []

    return {
        "video": available_video,
        "audio": available_audio,
        "title": (info.get("title") or "بدون عنوان")[:80],
        "uploader": info.get("uploader") or info.get("channel") or "—",
        "duration": info.get("duration"),
        "view_count": info.get("view_count"),
        "has_video": bool(available_video),
        "has_audio": bool(available_audio),
    }


# ─── التحميل ───────────────────────────────────────────────────────────────
def download_media(url: str, fmt: str, quality: str) -> tuple[str, str]:
    """يحمّل الوسيط ويرجع (out_path, out_name)."""
    tmpdir = tempfile.mkdtemp()

    if fmt == "audio":
        opts = _build_base_opts({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": quality,
            }],
            "outtmpl": os.path.join(tmpdir, "%(title).60s.%(ext)s"),
        })
    else:
        h = quality
        fmt_selector = (
            f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/"
            f"bestvideo[height<={h}]+bestaudio/"
            f"best[height<={h}]/"
            "best"
        )
        opts = _build_base_opts({
            "format": fmt_selector,
            "merge_output_format": "mp4",
            "outtmpl": os.path.join(tmpdir, "%(title).60s.%(ext)s"),
        })

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    files = [f for f in os.listdir(tmpdir) if not f.endswith(".part")]
    if not files:
        raise FileNotFoundError("لم يُحمَّل أي ملف")

    files.sort(key=lambda f: os.path.getsize(os.path.join(tmpdir, f)), reverse=True)
    chosen = files[0]
    out_path = os.path.join(tmpdir, chosen)

    safe_name = re.sub(r'[^\w\s\-\u0600-\u06FF.]', '', chosen)[:80]
    safe_name = safe_name or f"media_{quality}.mp4"

    return out_path, safe_name
