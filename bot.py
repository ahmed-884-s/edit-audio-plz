"""
bot.py — بوت تيليجرام لتحميل الفيديوهات
يدعم YouTube · Instagram · TikTok · Twitter/X · Facebook · وأكتر من 1000 موقع
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from downloader import download_media, get_info

# ─────────────────────────── logging ────────────────────────────────

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─────────────────────────── config ─────────────────────────────────

RATE_LIMIT  = 5                     # أقصى عدد تحميلات
RATE_WINDOW = timedelta(minutes=10) # خلال
MAX_TG_SIZE = 50 * 1024 * 1024     # 50 MB حد تيليجرام

# ─────────────────────────── rate limiter ───────────────────────────

_history: dict[int, list[datetime]] = defaultdict(list)


def check_rate_limit(user_id: int) -> bool:
    """True لو المستخدم تجاوز الحد — بيحدّث السجل تلقائياً."""
    now  = datetime.now()
    hist = [t for t in _history[user_id] if now - t < RATE_WINDOW]
    _history[user_id] = hist
    if len(hist) >= RATE_LIMIT:
        return True
    _history[user_id].append(now)
    return False



# ─────────────────────────── keyboards ──────────────────────────────

def _cancel_row() -> list[list[InlineKeyboardButton]]:
    return [[InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]]


def format_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎬 فيديو  MP4", callback_data="fmt:video"),
            InlineKeyboardButton("🎵 صوت  MP3",  callback_data="fmt:audio"),
        ],
        *_cancel_row(),
    ])


def quality_keyboard(fmt: str) -> InlineKeyboardMarkup:
    if fmt == "audio":
        rows = [
            [
                InlineKeyboardButton("🔊 جودة عالية — 320k", callback_data="q:audio:320"),
                InlineKeyboardButton("🔉 جودة متوسطة — 128k", callback_data="q:audio:128"),
            ],
        ]
    else:
        rows = [
            [
                InlineKeyboardButton("🔵 1080p — Full HD", callback_data="q:video:1080"),
                InlineKeyboardButton("🟢 720p — HD",       callback_data="q:video:720"),
            ],
            [
                InlineKeyboardButton("🟡 480p",            callback_data="q:video:480"),
                InlineKeyboardButton("🔴 360p",            callback_data="q:video:360"),
            ],
        ]
    return InlineKeyboardMarkup([*rows, *_cancel_row()])


# ─────────────────────────── text helpers ───────────────────────────

START_TEXT = (
    "👋 *أهلاً بك في Video Downloader Bot*\n\n"
    "🔗 ابعت أي رابط فيديو وهنزّله ليك فوراً\n\n"
    "✅ *المواقع المدعومة:*\n"
    "YouTube · Instagram · TikTok · Twitter/X\n"
    "Facebook · SoundCloud · Vimeo · وأكتر من 1000 موقع\n\n"
    "🎬 *الصيغ:* MP4 فيديو  |  MP3 صوت\n"
    "📐 *الجودات:* 1080p · 720p · 480p · 360p · 320k · 128k\n\n"
    "ابعت الرابط دلوقتي 👇"
)

HELP_TEXT = (
    "📖 *طريقة الاستخدام:*\n\n"
    "1️⃣ انسخ رابط أي فيديو\n"
    "2️⃣ ابعته هنا مباشرةً\n"
    "3️⃣ اختار الصيغة (فيديو أو صوت)\n"
    "4️⃣ اختار الجودة\n"
    "5️⃣ انتظر التحميل ✅\n\n"
    "⚠️ *ملاحظات:*\n"
    "• الحد الأقصى للملف: 50 MB\n"
    f"• أقصى عدد تحميلات: {RATE_LIMIT} كل 10 دقايق\n"
    "• بعض الفيديوهات ممكن يكون فيها قيود جغرافية\n\n"
    "🆘 أي مشكلة؟ كلّم المطوّر @YourUsername"
)


def _format_duration(secs: int | float | None) -> str:
    if not secs:
        return "—"
    secs = int(secs)
    h, rem = divmod(secs, 3600)
    m, s   = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _qual_label(fmt: str, quality: str) -> str:
    return f"{quality}p" if fmt == "video" else f"{quality} kbps"


# ─────────────────────────── handlers ───────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(START_TEXT, parse_mode=ParseMode.MARKDOWN)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.MARKDOWN)


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    url     = update.message.text.strip()
    user_id = update.effective_user.id

    if not url.startswith(("http://", "https://")):
        await update.message.reply_text(
            "⚠️ *رابط غير صحيح*\n\nابعت رابط يبدأ بـ `https://`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if check_rate_limit(user_id):
        await update.message.reply_text(
            "⏳ *تجاوزت الحد المسموح*\n\n"
            f"ممكن تعمل {RATE_LIMIT} تحميلات كل 10 دقايق.\n"
            "استنّى شوية وحاول تاني 😊",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # ── جيب معلومات الفيديو ──
    status_msg = await update.message.reply_text("🔍 *جاري فحص الرابط…*", parse_mode=ParseMode.MARKDOWN)

    try:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, get_info, url)
    except Exception as exc:
        logger.warning("get_info failed for %s: %s", url, exc)
        await status_msg.edit_text(
            "❌ *تعذّر قراءة الرابط*\n\n"
            "تأكد إن الرابط صحيح وإن الفيديو مش خاص أو محذوف.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    title    = (info.get("title") or "بدون عنوان")[:60]
    uploader = info.get("uploader") or info.get("channel") or "—"
    duration = info.get("duration")
    dur_str  = _format_duration(duration)
    views    = info.get("view_count")
    view_str = f"{views:,}" if views else "—"

    context.user_data.update({"url": url, "title": title, "uploader": uploader})

    await status_msg.edit_text(
        f"🎬 *{title}*\n"
        f"👤 {uploader}  ·  ⏱ {dur_str}  ·  👁 {view_str}\n\n"
        "📥 اختار الصيغة:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=format_keyboard(),
    )


async def cb_format(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        context.user_data.clear()
        await query.edit_message_text("❌ تم الإلغاء.")
        return

    fmt   = query.data.split(":")[1]
    title = context.user_data.get("title", "—")

    context.user_data["fmt"] = fmt

    await query.edit_message_text(
        f"🎬 *{title}*\n\n📐 اختار الجودة:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=quality_keyboard(fmt),
    )


async def cb_quality(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        context.user_data.clear()
        await query.edit_message_text("❌ تم الإلغاء.")
        return

    _, fmt, quality = query.data.split(":")
    url   = context.user_data.get("url")
    title = context.user_data.get("title", "—")

    if not url:
        await query.edit_message_text("❌ حصل خطأ، ابعت الرابط تاني.")
        return

    qlabel = _qual_label(fmt, quality)

    await query.edit_message_text(
        f"⬇️ *جاري التحميل…*\n\n"
        f"📄 {title}\n"
        f"📐 {qlabel}\n\n"
        f"_ده ممكن ياخد وقت حسب حجم الفيديو_",
        parse_mode=ParseMode.MARKDOWN,
    )

    # ── نزّل الملف ──
    try:
        loop = asyncio.get_running_loop()
        out_path, out_name = await loop.run_in_executor(
            None, download_media, url, fmt, quality
        )
    except Exception as exc:
        logger.error("Download failed: %s", exc)
        await query.message.reply_text(
            f"❌ *فشل التحميل*\n\n`{str(exc)[:200]}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        context.user_data.clear()
        return

    # ── ابعت الملف ──
    file_size = os.path.getsize(out_path)
    size_mb   = file_size / (1024 * 1024)
    caption   = f"✅ *{title[:50]}*\n📐 {qlabel}  ·  📦 {size_mb:.1f} MB"

    try:
        if file_size > MAX_TG_SIZE:
            await query.message.reply_text(
                f"⚠️ *الملف كبير جداً* ({size_mb:.1f} MB)\n\n"
                "تيليجرام مش بيسمح بأكتر من 50 MB.\n"
                "جرّب جودة أقل 👇",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=quality_keyboard(fmt),
            )
            return

        with open(out_path, "rb") as fh:
            kwargs = dict(
                filename=out_name,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                write_timeout=300,
                read_timeout=300,
            )
            if fmt == "audio":
                await query.message.reply_audio(audio=fh, **kwargs)
            else:
                await query.message.reply_video(
                    video=fh, supports_streaming=True, **kwargs
                )
    except Exception as exc:
        logger.error("Send failed: %s", exc)
        await query.message.reply_text(
            "❌ *حصل خطأ أثناء الإرسال*\n\nحاول تاني بعد شوية.",
            parse_mode=ParseMode.MARKDOWN,
        )
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)
        context.user_data.clear()


# ─────────────────────────── main ───────────────────────────────────

def main() -> None:
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise EnvironmentError("❌  BOT_TOKEN غير موجود في متغيرات البيئة!")

    app = (
        Application.builder()
        .token(token)
        .read_timeout(300)
        .write_timeout(300)
        .connect_timeout(60)
        .pool_timeout(60)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    app.add_handler(CallbackQueryHandler(cb_format,  pattern=r"^(fmt:|cancel$)"))
    app.add_handler(CallbackQueryHandler(cb_quality, pattern=r"^q:"))

    logger.info("✅  البوت شغّال")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
