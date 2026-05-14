import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters, ContextTypes
)
from editor import edit_audio_tags
import tempfile

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# States
WAITING_FILE, WAITING_TITLE, WAITING_ARTIST, WAITING_ALBUM, WAITING_YEAR, WAITING_GENRE, WAITING_CONFIRM = range(7)

FIELD_LABELS = {
    "title":  "🎵 عنوان الأغنية",
    "artist": "🎤 اسم الفنان",
    "album":  "💿 اسم الألبوم",
    "year":   "📅 سنة الإصدار",
    "genre":  "🎸 النوع (Genre)",
}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلاً!\n\n"
        "ابعتلي أي ملف صوتي وهعدّل معلوماته (ID3 Tags) وأرجعهولك نظيف.\n\n"
        "📎 ابعت الملف كـ *Document* مش كـ Audio عشان ميتضغطش.",
        parse_mode="Markdown"
    )
    return WAITING_FILE


async def receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document or update.message.audio

    if not doc:
        await update.message.reply_text("⚠️ ابعت ملف صوتي (mp3, m4a, flac, ogg, wav...)")
        return WAITING_FILE

    filename = doc.file_name or "audio_file"
    ext = os.path.splitext(filename)[1].lower()

    supported = [".mp3", ".m4a", ".flac", ".ogg", ".wav", ".aac", ".wma"]
    if ext not in supported:
        await update.message.reply_text(
            f"❌ الامتداد `{ext}` مش مدعوم.\n\n✅ المدعوم: mp3, m4a, flac, ogg, wav",
            parse_mode="Markdown"
        )
        return WAITING_FILE

    msg = await update.message.reply_text("⬇️ بحمّل الملف...")

    file = await doc.get_file()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    await file.download_to_drive(tmp.name)
    tmp.close()

    context.user_data["file_path"] = tmp.name
    context.user_data["original_name"] = filename
    context.user_data["tags"] = {}

    await msg.delete()
    await update.message.reply_text(
        f"✅ استلمت: `{filename}`\n\n"
        "دلوقتي هنعبي معلومات الملف.\n"
        "اكتب **.** لو عاوز تسيب الخانة فاضية.\n\n"
        f"{FIELD_LABELS['title']}:",
        parse_mode="Markdown"
    )
    return WAITING_TITLE


async def get_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    context.user_data["tags"]["title"] = "" if val == "." else val
    await update.message.reply_text(f"{FIELD_LABELS['artist']}:")
    return WAITING_ARTIST


async def get_artist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    context.user_data["tags"]["artist"] = "" if val == "." else val
    await update.message.reply_text(f"{FIELD_LABELS['album']}:")
    return WAITING_ALBUM


async def get_album(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    context.user_data["tags"]["album"] = "" if val == "." else val
    await update.message.reply_text(f"{FIELD_LABELS['year']}:")
    return WAITING_YEAR


async def get_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    context.user_data["tags"]["year"] = "" if val == "." else val
    await update.message.reply_text(f"{FIELD_LABELS['genre']}:")
    return WAITING_GENRE


async def get_genre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    context.user_data["tags"]["genre"] = "" if val == "." else val

    tags = context.user_data["tags"]
    fname = context.user_data["original_name"]

    summary = f"📋 *مراجعة المعلومات:*\n\n📁 الملف: `{fname}`\n\n"
    for key, label in FIELD_LABELS.items():
        v = tags.get(key, "")
        summary += f"{label}: {v if v else '_(فاضي)_'}\n"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تمام، طبّق!", callback_data="confirm")],
        [InlineKeyboardButton("🔄 من الأول", callback_data="restart")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="cancel")],
    ])

    await update.message.reply_text(summary, parse_mode="Markdown", reply_markup=kb)
    return WAITING_CONFIRM


async def confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "cancel":
        _cleanup(context)
        await query.edit_message_text("❌ اتلغى الأمر. ابعت ملف جديد لو حابب.")
        return ConversationHandler.END

    if data == "restart":
        _cleanup(context)
        await query.edit_message_text("🔄 تمام، ابعت الملف من أول.")
        return WAITING_FILE

    if data == "confirm":
        await query.edit_message_text("⚙️ بعدّل الملف...")

        file_path = context.user_data["file_path"]
        tags = context.user_data["tags"]
        original_name = context.user_data["original_name"]

        try:
            out_path = edit_audio_tags(file_path, tags)
        except Exception as e:
            logger.error(f"Tag edit error: {e}")
            await query.message.reply_text(f"❌ حصل خطأ أثناء التعديل:\n`{e}`", parse_mode="Markdown")
            _cleanup(context)
            return ConversationHandler.END

        await query.message.reply_document(
            document=open(out_path, "rb"),
            filename=original_name,
            caption="✅ الملف جاهز بالمعلومات الجديدة!"
        )

        os.unlink(out_path)
        _cleanup(context)
        return ConversationHandler.END


def _cleanup(context: ContextTypes.DEFAULT_TYPE):
    fp = context.user_data.get("file_path")
    if fp and os.path.exists(fp):
        try:
            os.unlink(fp)
        except Exception:
            pass
    context.user_data.clear()


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _cleanup(context)
    await update.message.reply_text("❌ اتلغى.")
    return ConversationHandler.END


def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN مش موجود في environment variables!")

    app = Application.builder().token(token).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Document.ALL | filters.AUDIO, receive_file),
        ],
        states={
            WAITING_FILE:    [MessageHandler(filters.Document.ALL | filters.AUDIO, receive_file)],
            WAITING_TITLE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_title)],
            WAITING_ARTIST:  [MessageHandler(filters.TEXT & ~filters.COMMAND, get_artist)],
            WAITING_ALBUM:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_album)],
            WAITING_YEAR:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_year)],
            WAITING_GENRE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_genre)],
            WAITING_CONFIRM: [CallbackQueryHandler(confirm_callback)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("start", start))

    logger.info("البوت شغّال ✅")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
