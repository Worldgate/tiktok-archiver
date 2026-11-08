"""Everything that talks to TikTok, through yt-dlp.

Carried over from the old scripts, which worked through a lot of TikTok's
quirks:
  - a listing ("flatdump") can exit with an error even though it printed
    valid JSON for every video except one dead one, so the JSON is read
    first and the exit code second
  - TikTok sometimes repeats the same page of a listing, so entries are
    de-duplicated by ID
  - the 'download' format (TikTok's share-link MP4) reliably has audio
    when the HQ streams come back video-only (yt-dlp issues #15891, #16622)
"""

import json
import os
import subprocess
import time


class YtdlpMissing(SystemExit):
    pass


def tiktok_url(name):
    """Account URL from a handle or numeric ID (TikTok accepts both)."""
    return f"https://www.tiktok.com/@{name.lstrip('@')}"


def video_url(vid, handle="x"):
    return f"https://www.tiktok.com/@{handle}/video/{vid}"


class Ytdlp:
    def __init__(self, settings, use_cookies=True):
        self.s = settings
        self.cookies = None
        if use_cookies and os.path.isfile(settings.cookies_path):
            self.cookies = settings.cookies_path

    def base(self):
        cmd = ["yt-dlp", "--no-warnings", "--quiet"]
        if self.s.impersonate:
            cmd += ["--impersonate", self.s.impersonate]
        if self.cookies:
            cmd += ["--cookies", self.cookies]
        return cmd

    def _run(self, cmd, timeout):
        start = time.monotonic()
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None, f"timed out after {timeout}s", time.monotonic() - start
        except FileNotFoundError:
            raise YtdlpMissing("yt-dlp not found. Is it installed (pip install \"yt-dlp[default,curl-cffi]\") "
                               "and is your venv active?")
        return r, None, time.monotonic() - start

    # --- listings ---
    def listing(self, url, timeout, count=None):
        """Fetch an account's video list.

        Returns a dict:
          status    "ok", "empty" or "error"
          dump      the yt-dlp JSON (entries de-duplicated, dead ones dropped)
          dropped   how many entries were dead or repeated
          error     reason, when status is "error"
          seconds   how long it took
        """
        cmd = self.base() + ["--flat-playlist", "--dump-single-json"]
        if count:
            cmd += ["--playlist-end", str(count)]
        cmd.append(url)
        r, err, secs = self._run(cmd, timeout)
        out = {"status": "error", "dump": None, "dropped": 0, "error": err, "seconds": secs}
        if r is None:
            return out
        both = (r.stderr or "") + (r.stdout or "")
        if "does not have any videos posted" in both:
            out.update(status="empty", error=None)
            return out
        dump = None
        if (r.stdout or "").strip():
            try:
                dump = json.loads(r.stdout)
            except ValueError:
                dump = None
        if dump is None:
            out["error"] = classify_listing_error(r.returncode, both)
            return out
        raw = dump.get("entries") or []
        seen, entries = set(), []
        for e in raw:
            if not e:
                continue
            vid = str(e.get("id") or "")
            if vid:
                if vid in seen:
                    continue
                seen.add(vid)
            entries.append(e)
        dump["entries"] = entries
        out.update(status="ok", dump=dump, dropped=len(raw) - len(entries), error=None)
        return out

    def peek(self, name, timeout, count=1):
        """Quick look at the newest few videos. Returns account details:
        {uploader_id, handle, display_name, channel_url, video_count,
         entries, empty, error}"""
        res = self.listing(tiktok_url(name), timeout, count=count)
        info = {"uploader_id": None, "handle": None, "display_name": None,
                "channel_url": None, "video_count": None, "entries": [],
                "empty": False, "error": res["error"]}
        if res["status"] == "empty":
            info["empty"] = True
            info["video_count"] = 0
            if name.lstrip("@").isdigit():
                info["uploader_id"] = name.lstrip("@")
            else:
                info["handle"] = name.lstrip("@")
            return info
        if res["status"] == "error":
            return info
        dump = res["dump"]
        entries = dump["entries"]
        first = entries[0] if entries else {}
        uid = first.get("uploader_id") or dump.get("uploader_id")
        if not uid:
            info["error"] = "could not find the account ID in TikTok's answer"
            return info
        info.update(
            uploader_id=str(uid),
            handle=first.get("uploader") or dump.get("uploader")
            or (None if name.lstrip("@").isdigit() else name.lstrip("@")),
            display_name=first.get("channel") or first.get("uploader"),
            channel_url=first.get("channel_url") or dump.get("channel_url"),
            video_count=dump.get("playlist_count"),
            entries=entries,
        )
        return info

    # --- downloads ---
    def download(self, url, out_template, timeout, fmt=None):
        """Download one video. Returns (ok, reason, level, stderr)."""
        cmd = self.base() + ["--no-playlist", "--output", out_template]
        if fmt:
            cmd += ["--format", fmt]
        cmd.append(url)
        r, err, _ = self._run(cmd, timeout)
        if r is None:
            return False, err, "account", ""
        if r.returncode == 0:
            return True, None, None, ""
        both = (r.stderr or "") + (r.stdout or "")
        reason, level = classify_video_error(r.returncode, both, url)
        return False, reason, level, both.strip()

    def fetch_audio_source(self, vid, out_path, timeout):
        """Download TikTok's 'download' format (has audio) to out_path."""
        ok, reason, _, _ = self.download(video_url(vid), out_path, timeout,
                                         fmt="download/b[vcodec=h264]/b")
        return ok and os.path.isfile(out_path), reason


# --- error sorting ---

def classify_listing_error(returncode, text):
    t = text.lower()
    if "does not have any videos posted" in t:
        return "empty — no videos posted"
    if "404" in t or "does not exist" in t:
        return "404 — account not found or deleted"
    if "private" in t:
        return "account is private"
    if "login" in t or "cookie" in t:
        return "auth required — add cookies.txt"
    if "502" in t:
        return "HTTP 502 — rate limited, retry later"
    if "timeout" in t or "timed out" in t:
        return "connection timeout"
    return f"unknown error (exit {returncode})"


# Video-level reasons that never change between runs (deleted, taken down,
# not a video). skipped --retry leaves these alone unless --all-reasons.
# Videos you deleted from a blocked account's folder (set by scan).
DISCARDED = "discarded — you deleted it"

PERMANENT = {
    DISCARDED,
    "photo post — not a video",
    "404 — video deleted",
    "removed — copyright",
    "video is private",
    "unsupported content type",
    "video removed",
    "removed — policy violation",
}


def classify_video_error(returncode, text, url=""):
    """Returns (reason, level). level "video" = skip just this video;
    "account" = something wrong with the account or connection, counts
    toward flagging. Unknown errors count as "video" so one odd failure
    doesn't freeze a whole account."""
    t = text.lower()
    if "/photo/" in url.lower() or "/photo/" in t or "no video formats found" in t:
        return "photo post — not a video", "video"
    if "does not exist" in t or "404" in t:
        return "404 — video deleted", "video"
    if "copyright" in t:
        return "removed — copyright", "video"
    if "private" in t:
        return "video is private", "video"
    if "unsupported url" in t:
        return "unsupported content type", "video"
    if "comfortable for some audiences" in t:
        return "age restricted — needs cookies", "video"
    if "this video is unavailable" in t:
        return "video unavailable", "video"
    if "video has been removed" in t:
        return "video removed", "video"
    if "violated" in t:
        return "removed — policy violation", "video"
    if "content is currently unavailable" in t:
        return "content unavailable", "video"
    if "this video is only available" in t:
        return "region restricted", "video"
    if "couldn't find" in t or "could not find" in t:
        return "video not found", "video"
    if "requested format is not available" in t:
        return "format unavailable", "video"
    if "login" in t or "cookie" in t:
        return "auth required — add cookies.txt", "account"
    if "502" in t:
        return "HTTP 502 — rate limited, retry later", "account"
    if "503" in t:
        return "HTTP 503 — service unavailable", "account"
    if "timeout" in t or "timed out" in t:
        return "connection timeout", "account"
    if "unable to download" in t and "webpage" in t:
        return "page fetch failed", "account"
    return f"unknown error (exit {returncode})", "video"
