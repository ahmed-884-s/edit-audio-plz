"""
editor.py — تعديل ID3 Tags لملفات الصوت
يدعم: mp3, m4a, flac, ogg, wav, aac, wma
"""

import os
import shutil
import tempfile
import logging

logger = logging.getLogger(__name__)


def edit_audio_tags(file_path: str, tags: dict) -> str:
    """
    تعدّل tags الملف الصوتي وترجع مسار الملف المعدّل.
    tags: dict فيه أي من: title, artist, album, year, genre
    """
    ext = os.path.splitext(file_path)[1].lower()

    # نعمل نسخة مؤقتة عشان نشتغل عليها
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    tmp.close()
    shutil.copy2(file_path, tmp.name)
    out_path = tmp.name

    try:
        if ext == ".mp3":
            _edit_mp3(out_path, tags)
        elif ext == ".m4a" or ext == ".aac":
            _edit_m4a(out_path, tags)
        elif ext == ".flac":
            _edit_flac(out_path, tags)
        elif ext == ".ogg":
            _edit_ogg(out_path, tags)
        elif ext in (".wav", ".wma"):
            _edit_generic(out_path, tags)
        else:
            raise ValueError(f"امتداد غير مدعوم: {ext}")
    except Exception as e:
        if os.path.exists(out_path):
            os.unlink(out_path)
        raise e

    return out_path


def _edit_mp3(path: str, tags: dict):
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TCON, ID3NoHeaderError
    try:
        audio = ID3(path)
    except ID3NoHeaderError:
        audio = ID3()

    mapping = {
        "title":  ("TIT2", TIT2),
        "artist": ("TPE1", TPE1),
        "album":  ("TALB", TALB),
        "year":   ("TDRC", TDRC),
        "genre":  ("TCON", TCON),
    }

    for field, (tag_id, tag_cls) in mapping.items():
        val = tags.get(field, "")
        if val:
            audio[tag_id] = tag_cls(encoding=3, text=val)
        elif tag_id in audio:
            del audio[tag_id]

    audio.save(path, v2_version=3)
    logger.info(f"MP3 tags saved: {path}")


def _edit_m4a(path: str, tags: dict):
    from mutagen.mp4 import MP4

    audio = MP4(path)

    mapping = {
        "title":  "\xa9nam",
        "artist": "\xa9ART",
        "album":  "\xa9alb",
        "year":   "\xa9day",
        "genre":  "\xa9gen",
    }

    for field, tag_id in mapping.items():
        val = tags.get(field, "")
        if val:
            audio[tag_id] = [val]
        elif tag_id in audio:
            del audio[tag_id]

    audio.save()
    logger.info(f"M4A tags saved: {path}")


def _edit_flac(path: str, tags: dict):
    from mutagen.flac import FLAC

    audio = FLAC(path)

    mapping = {
        "title":  "title",
        "artist": "artist",
        "album":  "album",
        "year":   "date",
        "genre":  "genre",
    }

    for field, tag_id in mapping.items():
        val = tags.get(field, "")
        if val:
            audio[tag_id] = val
        elif tag_id in audio:
            del audio[tag_id]

    audio.save()
    logger.info(f"FLAC tags saved: {path}")


def _edit_ogg(path: str, tags: dict):
    from mutagen.oggvorbis import OggVorbis

    audio = OggVorbis(path)

    mapping = {
        "title":  "title",
        "artist": "artist",
        "album":  "album",
        "year":   "date",
        "genre":  "genre",
    }

    for field, tag_id in mapping.items():
        val = tags.get(field, "")
        if val:
            audio[tag_id] = val
        elif tag_id in audio:
            del audio[tag_id]

    audio.save()
    logger.info(f"OGG tags saved: {path}")


def _edit_generic(path: str, tags: dict):
    """WAV / WMA عبر mutagen generic"""
    from mutagen import File

    audio = File(path, easy=True)
    if audio is None:
        raise ValueError("mutagen مش قادر يفتح الملف ده")

    mapping = {
        "title":  "title",
        "artist": "artist",
        "album":  "album",
        "year":   "date",
        "genre":  "genre",
    }

    for field, tag_id in mapping.items():
        val = tags.get(field, "")
        try:
            if val:
                audio[tag_id] = val
            elif tag_id in audio:
                del audio[tag_id]
        except Exception:
            pass  # بعض الفورمات مش بتدعم كل الـ tags

    audio.save()
    logger.info(f"Generic tags saved: {path}")
