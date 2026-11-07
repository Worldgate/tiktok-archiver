"""Where each video lives: folder_template + filename_template."""

import datetime
import os
import re

# TikTok video IDs are 19 digits today; allow a little either way.
VIDEO_ID_RE = re.compile(r"(?<!\d)(\d{15,20})(?!\d)")


def video_id_from_name(filename):
    """'2025.02.03-7467300438342290734.mp4' -> '7467300438342290734'.
    Takes the last long number, so a date in front can't be mistaken for it."""
    found = VIDEO_ID_RE.findall(os.path.splitext(os.path.basename(filename))[0])
    return found[-1] if found else None


def upload_date(listing):
    """(yyyy, mm, dd) strings from a listing, or ('0000', '00', '00')."""
    ts = (listing or {}).get("timestamp")
    if ts:
        d = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
        return f"{d.year:04d}", f"{d.month:02d}", f"{d.day:02d}"
    ud = (listing or {}).get("upload_date")  # "YYYYMMDD" from yt-dlp
    if ud and len(ud) == 8 and ud.isdigit():
        return ud[:4], ud[4:6], ud[6:]
    return "0000", "00", "00"


def account_folder(settings, account, base=None):
    """Folder for an account inside the library (or quarantine)."""
    tokens = {
        "uid": account.uid,
        "uid19": account.uid.zfill(19),
        "handle": safe(account.handle),
        "category": safe(account.category),
    }
    rel = settings.folder_template.format(**tokens)
    return os.path.join(base or settings.library_dir, rel)


def video_filename(settings, vid, video, ext):
    yyyy, mm, dd = upload_date(video.get("listing"))
    stem = settings.filename_template.format(yyyy=yyyy, mm=mm, dd=dd, id=vid)
    return f"{stem}.{ext.lstrip('.').lower()}"


def file_path(settings, account, video):
    """Where a recorded file should be right now (library or quarantine)."""
    f = video["file"]
    base = settings.quarantine_dir if f.get("location") == "quarantine" else settings.library_dir
    return os.path.join(account_folder(settings, account, base), f["filename"])


def safe(text):
    """Make text safe as a folder name."""
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", str(text)).strip(" .")
    return text or "_"
