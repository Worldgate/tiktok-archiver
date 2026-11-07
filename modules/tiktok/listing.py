"""Merging yt-dlp listings ("flatdumps") into an account's catalog.

Used by update (today's listing) and import-old (years of old dumps), so
both follow the same rules:

  - Every video ever seen stays in the catalog.
  - first_seen = earliest listing it appeared in, last_seen = latest.
  - Metadata (title, counts...) comes from the newest listing seen so far,
    so importing an old dump never overwrites newer info.
  - not_listed_since = the first listing after last_seen that didn't have
    it (deleted, private, or TikTok just didn't return it that time).
    Seen again in a newer listing → cleared.

Only the useful fields are kept. Thumbnail and CDN links are skipped:
they expire within days.
"""

import datetime
import re

# yt-dlp field → catalog field. Copied when present.
FIELDS = {
    "title": "title",
    "description": "description",
    "timestamp": "timestamp",
    "duration": "duration",
    "view_count": "view_count",
    "like_count": "like_count",
    "comment_count": "comment_count",
    "repost_count": "repost_count",
    "save_count": "save_count",
    "track": "track",
    "artist": "artist",
    "artists": "artists",
    "album": "album",
    "tags": "tags",
    "categories": "categories",
    "url": "url",
}

HASHTAG_RE = re.compile(r"#([^\s#]+)")


def metadata(entry):
    """The fields worth keeping from one yt-dlp entry."""
    out = {}
    for src, dst in FIELDS.items():
        value = entry.get(src)
        if value not in (None, "", []):
            out[dst] = value
    if out.get("description") == out.get("title"):
        out.pop("description", None)  # TikTok often repeats it
    text = " ".join(str(out.get(k) or "") for k in ("title", "description"))
    tags = sorted({h.rstrip(".,!?;:").lower() for h in HASHTAG_RE.findall(text)} - {""})
    if tags:
        out["hashtags"] = tags
    return out


def t(text):
    """ISO text → comparable datetime ('...Z' and '-06:00' both work)."""
    if not text:
        return None
    d = datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    return d if d.tzinfo else d.astimezone()


def entry_ids(entries):
    out = []
    for e in entries or []:
        if e and str(e.get("id") or "").isdigit():
            out.append(str(e["id"]))
    return out


def merge(acc, entries, when, complete=True):
    """Merge one listing taken at time `when` (ISO text) into the account.

    complete=True: this listing should hold every video the account had
    then, so cataloged videos missing from it get not_listed_since.
    Returns the number of videos new to the catalog (with no file yet).
    """
    new = 0
    seen = set()
    now = t(when)
    for e in entries or []:
        if not e:
            continue
        vid = str(e.get("id") or "")
        if not vid.isdigit():
            continue
        seen.add(vid)
        v = acc.video(vid)
        listing = v.get("listing")
        if listing is None:
            listing = v["listing"] = {}
            if not v.get("file"):
                new += 1
        first, last = t(listing.get("first_seen")), t(listing.get("last_seen"))
        if not first or now < first:
            listing["first_seen"] = when
        if not last or now >= last:
            listing.update(metadata(e))
            listing["last_seen"] = when
            gone = t(listing.get("not_listed_since"))
            if gone and now >= gone:
                listing.pop("not_listed_since", None)
    if complete and seen:
        for vid, v in acc.videos.items():
            listing = v.get("listing")
            if not listing or vid in seen:
                continue
            last = t(listing.get("last_seen"))
            gone = t(listing.get("not_listed_since"))
            if (not last or last < now) and (not gone or now < gone):
                listing["not_listed_since"] = when
    return new
