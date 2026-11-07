"""Small shared helpers for the TikTok actions."""

import datetime
import os
import random
import time

from mogul_core import store

from .catalog import Catalog
from .settings import Settings


def setup(config):
    settings = Settings(config)
    return settings, Catalog(settings)


def stamp():
    """'2026-11-07_14-30-05' for report filenames."""
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def write_report(settings, action, data):
    """mogul_userdata/tiktok/reports/tiktok-<action>_<date>_<time>.json"""
    path = os.path.join(settings.reports_dir, f"tiktok-{action}_{stamp()}.json")
    data = {"action": f"tiktok {action}", "finished": store.now(), **data}
    store.save(path, data)
    print(f"\nReport: {path}")
    return path


def pause(lo, hi):
    if hi > 0:
        time.sleep(random.uniform(lo, max(lo, hi)))


def ytdlp_escape(path):
    """yt-dlp treats % in --output as a template marker."""
    return path.replace("%", "%%")


def add_filters(parser, name=True, category=True):
    if name:
        parser.add_argument("--name", help="one account, by @handle or numeric ID")
    if category:
        parser.add_argument("--category",
                            help="only accounts with this tag (comma-separated = must have all)")


def elapsed(start):
    secs = int(time.monotonic() - start)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"[{h:02d}:{m:02d}:{s:02d}]"


def days_ago(iso_text):
    """How many days ago an ISO timestamp was (float), or None."""
    if not iso_text:
        return None
    try:
        then = datetime.datetime.fromisoformat(iso_text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.astimezone()
    return (datetime.datetime.now(datetime.timezone.utc) - then).total_seconds() / 86400
