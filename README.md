# 📥 Video Downloader Bot

بوت تيليجرام لتحميل الفيديوهات بجودات مختلفة من أكتر من 1000 موقع.

## المميزات

- ✅ يدعم YouTube · Instagram · TikTok · Twitter/X · Facebook · SoundCloud · Vimeo وأكتر
- 🎬 تحميل فيديو MP4 بجودات: 1080p · 720p · 480p · 360p
- 🎵 تحميل صوت MP3 بجودات: 320 kbps · 128 kbps
- 📋 يعرض معلومات الفيديو (العنوان · المدة · عدد المشاهدات) قبل التحميل
- 🛡 Rate limiting لمنع الإساءة (5 تحميلات / 10 دقايق لكل مستخدم)
- ♻️ حذف الملفات المؤقتة تلقائياً بعد الإرسال

## التشغيل المحلي

```bash
pip install -r requirements.txt
export BOT_TOKEN="your_token_here"
python bot.py
```

## النشر على Railway

1. ارفع المشروع على GitHub
2. اربطه بـ Railway
3. أضف متغير البيئة `BOT_TOKEN`
4. Railway هيبني ويشغّل البوت تلقائياً

## متغيرات البيئة

| المتغير    | الوصف                        |
|------------|------------------------------|
| `BOT_TOKEN`| توكن البوت من @BotFather     |

## البنية

```
video-dl-bot/
├── bot.py          # منطق البوت والـ handlers
├── downloader.py   # wrapper فوق yt-dlp
├── requirements.txt
├── Procfile        # لـ Railway / Heroku
├── railway.json    # إعدادات Railway
└── nixpacks.toml   # ffmpeg + python311
```
