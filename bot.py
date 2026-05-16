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

from downloader import download_media, get_available_qualities

# ─────────────────────────── logging ──────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─────────────────────────── إعدادات ──────────────────────────────────────────
RATE_LIMIT = 5
RATE_WINDOW = timedelta(minutes=10)
MAX_TG_SIZE = 50 * 1024 * 1024  # 50 MB

# ─────────────────────────── rate limiter ─────────────────────────────────────
_history: dict[int, list[datetime]] = defaultdict(list)


def check_rate_limit(user_id: int) -> bool:
    now = datetime.now()
    hist = [t for t in _history[user_id] if now - t < RATE_WINDOW]
    _history[user_id] = hist
    if len(hist) >= RATE_LIMIT:
        return True
    _history[user_id].append(now)
    return False


# ─────────────────────────── لوحات المفاتيح ───────────────────────────────────
def _cancel_btn() -> InlineKeyboardButton:
    return InlineKeyboardButton("❌ إلغاء", callback_data="cancel")


def format_keyboard(has_video: bool, has_audio: bool) -> InlineKeyboardMarkup:
    rows = []
    if has_video:
        rows.append([InlineKeyboardButton("🎬 فيديو MP4", callback_data="fmt:video")])
    if has_audio:
        rows.append([InlineKeyboardButton("🎵 صوت MP3", callback_data="fmt:audio")])
    rows.append([_cancel_btn()])
    return InlineKeyboardMarkup(rows)


def video_quality_keyboard(qualities: list[str]) -> InlineKeyboardMarkup:
    """يعرض الجودات المتاحة فعلاً من الفيديو."""
    LABELS = {
        "2160": "🔵 4K — 2160p",
        "1440": "🟣 2K — 1440p",
        "1080": "🔵 Full HD — 1080p",
        "720":  "🟢 HD — 720p",
        "480":  "🟡 480p",
        "360":  "🔴 360p",
        "240":  "⚪ 240p",
    }

    btns = []
    row = []
    for q in qualities:
        label = LABELS.get(q, f"📹 {q}p")
        row.append(InlineKeyboardButton(label, callback_data=f"q:video:{q}"))
        if len(row) == 2:
            btns.append(row)
            row = []
    if row:
        btns.append(row)

    btns.append([_cancel_btn()])
    return InlineKeyboardMarkup(btns)


def audio_quality_keyboard(qualities: list[str]) -> InlineKeyboardMarkup:
    LABELS = {
        "320": "🔊 جودة عالية — 320 kbps",
        "128": "🔉 جودة متوسطة — 128 kbps",
    }
    btns = [
        [InlineKeyboardButton(LABELS.get(q, f"🎵 {q} kbps"), callback_data=f"q:audio:{q}")]
        for q in qualities
    ]
    btns.append([_cancel_btn()])
    return InlineKeyboardMarkup(btns)


# ─────────────────────────── نصوص ─────────────────────────────────────────────
START_TEXT = """
🎬 *Video Downloader Bot*

أهلاً بك! ابعتلي أي رابط فيديو وأنا هحمله ليك على طول 🚀

━━━━━━━━━━━━━━━━━━
📌 *المواقع المدعومة:*
YouTube · Instagram · TikTok
Twitter/X · Facebook · Vimeo
SoundCloud · وأكتر من 1000 موقع

🎬 *صيغ التحميل:*
MP4 فيديو | MP3 صوت

📐 *الجودات تتحدد حسب كل فيديو*
━━━━━━━━━━━━━━━━━━

ابعت الرابط دلوقتي 👇
""".strip()

HELP_TEXT = """
📖 *طريقة الاستخدام:*

1️⃣ انسخ رابط أي فيديو
2️⃣ ابعته للبوت مباشرةً
3️⃣ اختار الصيغة (فيديو أو صوت)
4️⃣ اختار الجودة من المتاح
5️⃣ انتظر وهتلاقي الملف ✅

━━━━━━━━━━━━━━━━━━
⚠️ *ملاحظات مهمة:*

• 📦 الحد الأقصى للملف: *50 MB*
• ⏱ أقصى عدد تحميلات: *{RATE_LIMIT} كل 10 دقايق*
• 🌍 بعض الفيديوهات ممكن تكون محظورة جغرافياً
• 🔒 الفيديوهات الخاصة أو المحذوفة مش ممكن تتحمّل
━━━━━━━━━━━━━━━━━━

/start — الرسالة الترحيبية
/help — هذه الرسالة
""".strip().replace("{RATE_LIMIT}", str(RATE_LIMIT))


def _fmt_duration(secs) -> str:
    if not secs:
        return "—"
    secs = int(secs)
    h, r = divmod(secs, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _fmt_views(n) -> str:
    if not n:
        return "—"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def _qual_label(fmt: str, quality: str) -> str:
    return f"{quality}p" if fmt == "video" else f"{quality} kbps"


# ─────────────────────────── Handlers ─────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(START_TEXT, parse_mode=ParseMode.MARKDOWN)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.MARKDOWN)


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    url = update.message.text.strip()
    user_id = update.effective_user.id

    # ── تحقق من الرابط ────────────────────────────────────────────────────
    if not url.startswith(("http://", "https://")):
        await update.message.reply_text(
            "⚠️ *رابط غير صحيح*\n\nابعت رابط يبدأ بـ `https://`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # ── تحقق من rate limit ────────────────────────────────────────────────
    if check_rate_limit(user_id):
        await update.message.reply_text(
            f"⏳ *وصلت للحد المسموح*\n\n"
            f"ممكن تعمل {RATE_LIMIT} تحميلات كل 10 دقايق فقط.\n"
            "استنّى شوية وحاول تاني 😊",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # ── جلب معلومات الفيديو ───────────────────────────────────────────────
    status_msg = await update.message.reply_text(
        "🔍 *جاري فحص الرابط…*\n_ده ممكن ياخد ثواني_",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, get_available_qualities, url)
    except Exception as exc:
        logger.warning("get_available_qualities failed: %s", exc)
        err_str = str(exc)
        # رسائل خطأ مفيدة حسب نوع المشكلة
        if "Sign in" in err_str or "bot" in err_str.lower():
            hint = "⛔ يوتيوب طالب تسجيل دخول.\nجرّب بعد دقايق أو جرّب رابط من موقع تاني."
        elif "Private" in err_str or "private" in err_str:
            hint = "🔒 الفيديو خاص أو محذوف."
        elif "Unsupported" in err_str or "unsupported" in err_str:
            hint = "❌ الموقع ده مش مدعوم."
        elif "404" in err_str or "not found" in err_str.lower():
            hint = "🔎 الفيديو مش موجود أو الرابط غلط."
        else:
            hint = f"_تفاصيل: `{err_str[:150]}`_"
        await status_msg.edit_text(
            f"❌ *تعذّر قراءة الرابط*\n\n{hint}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # ── خزّن البيانات ─────────────────────────────────────────────────────
    context.user_data.update({
        "url": url,
        "title": data["title"],
        "uploader": data["uploader"],
        "video_qualities": data["video"],
        "audio_qualities": data["audio"],
    })

    # ── كوّن رسالة المعلومات ──────────────────────────────────────────────
    dur = _fmt_duration(data.get("duration"))
    views = _fmt_views(data.get("view_count"))
    title = data["title"]
    uploader = data["uploader"]

    # عرض الجودات المتاحة
    vq = " · ".join(f"{q}p" for q in data["video"]) if data["video"] else "—"
    aq = " · ".join(f"{q}k" for q in data["audio"]) if data["audio"] else "—"

    info_text = (
        f"🎬 *{title}*\n"
        f"👤 {uploader}\n"
        f"⏱ {dur}  👁 {views}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📹 *جودات الفيديو المتاحة:* {vq}\n"
        f"🎵 *جودات الصوت:* {aq}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📥 اختار الصيغة:"
    )

    await status_msg.edit_text(
        info_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=format_keyboard(bool(data["video"]), bool(data["audio"])),
    )


async def cb_format(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        context.user_data.clear()
        await query.edit_message_text("❌ *تم الإلغاء*", parse_mode=ParseMode.MARKDOWN)
        return

    fmt = query.data.split(":")[1]
    context.user_data["fmt"] = fmt
    title = context.user_data.get("title", "—")

    if fmt == "video":
        qualities = context.user_data.get("video_qualities", ["1080", "720", "480", "360"])
        kb = video_quality_keyboard(qualities)
        fmt_label = "🎬 فيديو MP4"
    else:
        qualities = context.user_data.get("audio_qualities", ["320", "128"])
        kb = audio_quality_keyboard(qualities)
        fmt_label = "🎵 صوت MP3"

    await query.edit_message_text(
        f"*{title}*\n\n"
        f"الصيغة: {fmt_label}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📐 *اختار الجودة:*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb,
    )


async def cb_quality(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        context.user_data.clear()
        await query.edit_message_text("❌ *تم الإلغاء*", parse_mode=ParseMode.MARKDOWN)
        return

    _, fmt, quality = query.data.split(":")
    url = context.user_data.get("url")
    title = context.user_data.get("title", "—")

    if not url:
        await query.edit_message_text(
            "❌ *انتهت الجلسة*\n\nابعت الرابط تاني من الأول.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    qlabel = _qual_label(fmt, quality)

    await query.edit_message_text(
        f"⬇️ *جاري التحميل…*\n\n"
        f"📄 {title}\n"
        f"📐 {qlabel}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"_ده ممكن ياخد وقت حسب حجم الملف_",
        parse_mode=ParseMode.MARKDOWN,
    )

    # ── تحميل الملف ──────────────────────────────────────────────────────
    try:
        loop = asyncio.get_running_loop()
        out_path, out_name = await loop.run_in_executor(
            None, download_media, url, fmt, quality
        )
    except Exception as exc:
        logger.error("Download failed: %s", exc)
        err_str = str(exc)
        if "Sign in" in err_str or "bot" in err_str.lower():
            msg = "⛔ يوتيوب بلوك السيرفر.\nحاول تاني بعد شوية أو جرّب جودة تانية."
        elif "No space" in err_str:
            msg = "💾 مساحة التخزين المؤقتة امتلأت.\nحاول تاني بعد لحظة."
        else:
            msg = f"❌ *فشل التحميل*\n\n`{err_str[:200]}`"
        await query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        context.user_data.clear()
        return

    # ── إرسال الملف ───────────────────────────────────────────────────────
    file_size = os.path.getsize(out_path)
    size_mb = file_size / (1024 * 1024)
    caption = f"✅ *{title[:50]}*\n📐 {qlabel}  |  📦 {size_mb:.1f} MB"

    try:
        if file_size > MAX_TG_SIZE:
            # عرض جودات أقل كبديل
            lower_q = [
                q for q in context.user_data.get("video_qualities", [])
                if fmt == "video" and int(q) < int(quality)
            ]
            extra = ""
            if lower_q:
                extra = "\n\nجرّب جودة أقل 👇"
                kb = video_quality_keyboard(lower_q)
            else:
                kb = None

            msg = (
                f"⚠️ *الملف كبير جداً!*\n\n"
                f"الحجم: {size_mb:.1f} MB\n"
                f"الحد المسموح: 50 MB\n"
                f"{extra}"
            )
            await query.message.reply_text(
                msg,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb,
            )
            return

        with open(out_path, "rb") as fh:
            send_kwargs = dict(
                filename=out_name,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                write_timeout=300,
                read_timeout=300,
            )
            if fmt == "audio":
                await query.message.reply_audio(audio=fh, **send_kwargs)
            else:
                await query.message.reply_video(
                    video=fh, supports_streaming=True, **send_kwargs
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


# ─────────────────────────── main ─────────────────────────────────────────────
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

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    app.add_handler(CallbackQueryHandler(cb_format, pattern=r"^(fmt:|cancel$)"))
    app.add_handler(CallbackQueryHandler(cb_quality, pattern=r"^q:"))

    logger.info("✅ البوت شغّال")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
