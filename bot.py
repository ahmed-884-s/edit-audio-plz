"""
bot.py — بوت تيليجرام لتحميل الفيديوهات والصوتيات
يدعم YouTube · Instagram · TikTok · Twitter/X · Facebook · SoundCloud · Vimeo · وأكتر
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from downloader import download_media, get_info

# ══════════════════════════════════════════════
#  إعداد الـ Logging
# ══════════════════════════════════════════════
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════
#  الإعدادات العامة
# ══════════════════════════════════════════════
RATE_LIMIT   = int(os.getenv("RATE_LIMIT", "5"))       # أقصى عدد تحميلات
RATE_WINDOW  = timedelta(minutes=int(os.getenv("RATE_WINDOW_MINUTES", "10")))
MAX_TG_SIZE  = 50 * 1024 * 1024                        # 50 MB حد تيليجرام
TEMP_DIR     = Path(tempfile.gettempdir()) / "tg_dl_bot"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

VIDEO_QUALITIES = ["2160", "1440", "1080", "720", "480", "360"]
AUDIO_QUALITIES = ["320", "192", "128", "64"]

# ══════════════════════════════════════════════
#  Rate Limiter
# ══════════════════════════════════════════════
_history: dict[int, list[datetime]] = defaultdict(list)

def check_rate_limit(user_id: int) -> tuple[bool, int]:
    """
    يرجع (exceeded, remaining_seconds).
    exceeded=True لو المستخدم تجاوز الحد.
    """
    now = datetime.now()
    hist = [t for t in _history[user_id] if now - t < RATE_WINDOW]
    _history[user_id] = hist

    if len(hist) >= RATE_LIMIT:
        oldest = min(hist)
        wait = int((oldest + RATE_WINDOW - now).total_seconds()) + 1
        return True, wait

    _history[user_id].append(now)
    return False, 0

# ══════════════════════════════════════════════
#  Keyboards
# ══════════════════════════════════════════════
def _cancel_btn() -> InlineKeyboardButton:
    return InlineKeyboardButton("❌ إلغاء", callback_data="cancel")

def format_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎬 فيديو  MP4", callback_data="fmt:video"),
            InlineKeyboardButton("🎵 صوت  MP3",  callback_data="fmt:audio"),
        ],
        [_cancel_btn()],
    ])

def quality_keyboard(fmt: str, available: list[str] | None = None) -> InlineKeyboardMarkup:
    if fmt == "audio":
        options = [
            ("🔊 320 kbps — عالية جداً", "q:audio:320"),
            ("🔉 192 kbps — عالية",       "q:audio:192"),
            ("🔈 128 kbps — متوسطة",      "q:audio:128"),
            ("📻  64 kbps — منخفضة",      "q:audio:64"),
        ]
    else:
        options = [
            ("🔵 2160p — 4K",    "q:video:2160"),
            ("🟣 1440p — 2K",    "q:video:1440"),
            ("🟢 1080p — FHD",   "q:video:1080"),
            ("🟡  720p — HD",    "q:video:720"),
            ("🟠  480p — SD",    "q:video:480"),
            ("🔴  360p — منخفضة","q:video:360"),
        ]

    rows: list[list[InlineKeyboardButton]] = []
    pair: list[InlineKeyboardButton] = []
    for label, data in options:
        pair.append(InlineKeyboardButton(label, callback_data=data))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)

    rows.append([_cancel_btn()])
    return InlineKeyboardMarkup(rows)

# ══════════════════════════════════════════════
#  نصوص الرسائل
# ══════════════════════════════════════════════
START_TEXT = (
    "👋 *أهلاً بك في Video & Audio Downloader Bot*\n\n"
    "🔗 ابعت أي رابط وهنزّله ليك فوراً!\n\n"
    "━━━━━━━━━━━━━━━━━━━━━\n"
    "📺 *المواقع المدعومة:*\n"
    "YouTube · Instagram · TikTok\n"
    "Twitter/X · Facebook · SoundCloud\n"
    "Vimeo · Dailymotion · وأكتر من 1000 موقع\n\n"
    "🎬 *فيديو:*  4K · 2K · 1080p · 720p · 480p · 360p\n"
    "🎵 *صوت:*  320k · 192k · 128k · 64k\n"
    "━━━━━━━━━━━━━━━━━━━━━\n\n"
    "👇 ابعت الرابط دلوقتي!"
)

HELP_TEXT = (
    "📖 *طريقة الاستخدام:*\n\n"
    "1️⃣  انسخ رابط الفيديو\n"
    "2️⃣  ابعته هنا مباشرةً\n"
    "3️⃣  اختار الصيغة: فيديو MP4 أو صوت MP3\n"
    "4️⃣  اختار الجودة المناسبة\n"
    "5️⃣  انتظر التحميل ✅\n\n"
    "━━━━━━━━━━━━━━━━━━━━━\n"
    "⚠️ *ملاحظات مهمة:*\n\n"
    "• الحد الأقصى لحجم الملف: *50 MB*\n"
    f"• أقصى عدد تحميلات: *{RATE_LIMIT}* كل 10 دقايق لكل مستخدم\n"
    "• بعض الفيديوهات قد تكون محمية أو غير متاحة جغرافياً\n"
    "• إذا طلبت جودة غير متاحة، ستحصل على أعلى جودة ممكنة\n\n"
    "━━━━━━━━━━━━━━━━━━━━━\n"
    "🆘 مشكلة؟ تواصل مع المطوّر: @YourUsername"
)

# ══════════════════════════════════════════════
#  أدوات مساعدة
# ══════════════════════════════════════════════
def _fmt_duration(secs: int | float | None) -> str:
    if not secs:
        return "—"
    secs = int(secs)
    h, rem = divmod(secs, 3600)
    m, s   = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def _fmt_views(n: int | None) -> str:
    if n is None:
        return "—"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)

def _fmt_size(b: int) -> str:
    if b >= 1024**2:
        return f"{b/1024**2:.1f} MB"
    return f"{b/1024:.0f} KB"

def _qual_label(fmt: str, quality: str) -> str:
    return f"{quality}p" if fmt == "video" else f"{quality} kbps"

def _sanitize_filename(name: str) -> str:
    """يحذف الأحرف غير المسموح بها في أسماء الملفات."""
    import re
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()[:80]

# ══════════════════════════════════════════════
#  الـ Handlers
# ══════════════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    logger.info("START — user=%s (%s)", user.id, user.username)
    await update.message.reply_text(START_TEXT, parse_mode=ParseMode.MARKDOWN)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.MARKDOWN)


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    url     = update.message.text.strip()
    user    = update.effective_user
    user_id = user.id

    # ── تحقق من صحة الرابط ──
    if not url.startswith(("http://", "https://")):
        await update.message.reply_text(
            "⚠️ *رابط غير صالح*\n\nابعت رابط يبدأ بـ `https://`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # ── Rate Limit ──
    exceeded, wait_secs = check_rate_limit(user_id)
    if exceeded:
        mins, secs = divmod(wait_secs, 60)
        wait_str = f"{mins}:{secs:02d} دقيقة" if mins else f"{secs} ثانية"
        await update.message.reply_text(
            f"⏳ *تجاوزت الحد المسموح*\n\n"
            f"الحد المسموح: {RATE_LIMIT} تحميلات كل 10 دقايق.\n"
            f"انتظر: *{wait_str}* ثم حاول مجدداً 😊",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    logger.info("URL received — user=%s url=%s", user_id, url[:60])

    # ── جلب معلومات الفيديو ──
    status = await update.message.reply_text(
        "🔍 *جاري فحص الرابط…*\n_قد يستغرق بضع ثوانٍ_",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, get_info, url)
    except Exception as exc:
        logger.warning("get_info failed — user=%s url=%s err=%s", user_id, url[:60], exc)
        await status.edit_text(
            "❌ *تعذّر قراءة الرابط*\n\n"
            "• تأكد إن الرابط صحيح\n"
            "• الفيديو مش خاص أو محذوف\n"
            "• جرّب مرة تانية بعد قليل",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # ── تجهيز المعلومات ──
    title    = _sanitize_filename(info.get("title") or "بدون عنوان")
    uploader = info.get("uploader") or info.get("channel") or "—"
    dur_str  = _fmt_duration(info.get("duration"))
    view_str = _fmt_views(info.get("view_count"))
    thumb    = info.get("thumbnail")

    context.user_data.update({
        "url":      url,
        "title":    title,
        "uploader": uploader,
        "thumb":    thumb,
    })

    info_text = (
        f"🎬 *{title}*\n\n"
        f"👤 {uploader}\n"
        f"⏱ المدة: {dur_str}   👁 المشاهدات: {view_str}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📥 اختار صيغة التحميل:"
    )

    await status.edit_text(
        info_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=format_keyboard(),
    )


async def cb_format(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        context.user_data.clear()
        await query.edit_message_text("❌ *تم إلغاء العملية.*", parse_mode=ParseMode.MARKDOWN)
        return

    fmt   = query.data.split(":")[1]
    title = context.user_data.get("title", "—")
    context.user_data["fmt"] = fmt

    fmt_name = "فيديو MP4 🎬" if fmt == "video" else "صوت MP3 🎵"

    await query.edit_message_text(
        f"*{title}*\n\n"
        f"الصيغة المختارة: {fmt_name}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📐 اختار الجودة:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=quality_keyboard(fmt),
    )


async def cb_quality(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        context.user_data.clear()
        await query.edit_message_text("❌ *تم إلغاء العملية.*", parse_mode=ParseMode.MARKDOWN)
        return

    _, fmt, quality = query.data.split(":")
    url   = context.user_data.get("url")
    title = context.user_data.get("title", "—")

    if not url:
        await query.edit_message_text(
            "❌ *حدث خطأ*\n\nابعت الرابط مجدداً.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    qlabel = _qual_label(fmt, quality)
    user_id = update.effective_user.id
    logger.info("Downloading — user=%s fmt=%s quality=%s url=%s", user_id, fmt, quality, url[:60])

    await query.edit_message_text(
        f"⬇️ *جاري التحميل…*\n\n"
        f"📄 {title}\n"
        f"📐 الجودة: {qlabel}\n\n"
        f"_قد يستغرق ذلك بعض الوقت حسب حجم الملف…_",
        parse_mode=ParseMode.MARKDOWN,
    )

    # ── تحميل الملف ──
    out_path = out_name = None
    try:
        loop = asyncio.get_running_loop()
        out_path, out_name = await loop.run_in_executor(
            None, download_media, url, fmt, quality
        )
    except Exception as exc:
        logger.error("Download failed — user=%s err=%s", user_id, exc)
        await query.message.reply_text(
            "❌ *فشل التحميل*\n\n"
            f"السبب: `{str(exc)[:200]}`\n\n"
            "💡 *اقتراحات:*\n"
            "• جرّب جودة أقل\n"
            "• تأكد إن الرابط لا يزال صالحاً\n"
            "• حاول مرة أخرى بعد قليل",
            parse_mode=ParseMode.MARKDOWN,
        )
        context.user_data.clear()
        return

    # ── إرسال الملف ──
    try:
        file_size = os.path.getsize(out_path)

        if file_size > MAX_TG_SIZE:
            await query.message.reply_text(
                f"⚠️ *الملف كبير جداً*\n\n"
                f"الحجم: *{_fmt_size(file_size)}* (الحد: 50 MB)\n\n"
                "💡 جرّب جودة أقل:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=quality_keyboard(fmt),
            )
            return

        caption = (
            f"✅ *{title[:50]}*\n\n"
            f"📐 {qlabel}  •  📦 {_fmt_size(file_size)}\n"
            f"🤖 @YourBotUsername"
        )
        send_kwargs = dict(
            caption=caption,
            parse_mode=ParseMode.MARKDOWN,
            filename=out_name,
            write_timeout=300,
            read_timeout=300,
            connect_timeout=60,
        )

        with open(out_path, "rb") as fh:
            if fmt == "audio":
                await query.message.reply_audio(audio=fh, **send_kwargs)
            else:
                await query.message.reply_video(
                    video=fh, supports_streaming=True, **send_kwargs
                )

        logger.info("Sent successfully — user=%s size=%s", user_id, _fmt_size(file_size))

    except TelegramError as exc:
        logger.error("Telegram send error — user=%s err=%s", user_id, exc)
        await query.message.reply_text(
            "❌ *حصل خطأ أثناء الإرسال*\n\nحاول مجدداً بعد قليل.",
            parse_mode=ParseMode.MARKDOWN,
        )
    finally:
        if out_path and os.path.exists(out_path):
            os.unlink(out_path)
        context.user_data.clear()


async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يتعامل مع الأوامر غير المعروفة."""
    await update.message.reply_text(
        "❓ أمر غير معروف.\n\n"
        "ابعت /help لمعرفة طريقة الاستخدام، أو ابعت رابط الفيديو مباشرةً.",
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled error: %s", context.error, exc_info=context.error)

# ══════════════════════════════════════════════
#  الدالة الرئيسية
# ══════════════════════════════════════════════
def main() -> None:
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise EnvironmentError("❌ BOT_TOKEN غير موجود في متغيرات البيئة!")

    app = (
        Application.builder()
        .token(token)
        .read_timeout(300)
        .write_timeout(300)
        .connect_timeout(60)
        .pool_timeout(60)
        .build()
    )

    # Handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    app.add_handler(MessageHandler(filters.COMMAND, handle_unknown))
    app.add_handler(CallbackQueryHandler(cb_format,  pattern=r"^(fmt:|cancel$)"))
    app.add_handler(CallbackQueryHandler(cb_quality, pattern=r"^q:"))

    # Error handler
    app.add_error_handler(error_handler)

    logger.info("✅ البوت بدأ التشغيل")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
