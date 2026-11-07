"""Reading video files: ffprobe details and hashes.

Unlike radio, a TikTok video already has an ID (the TikTok video ID), so
the hashes here are whole-file hashes that identify the exact file on
disk: xxh64 always, plus whatever [core] hashes lists.
"""

import json
import os
import subprocess

from mogul_core import hashing, store


class ProbeError(Exception):
    pass


def probe(path, timeout=60):
    """ffprobe a file. Returns a dict of details, or raises ProbeError if the
    file can't be read at all (corrupt, truncated, not media)."""
    cmd = ["ffprobe", "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ProbeError("ffprobe timed out")
    except FileNotFoundError:
        raise SystemExit("ffprobe not found. Install ffmpeg (sudo apt install ffmpeg).")
    if result.returncode != 0:
        err = (result.stderr or "").strip().splitlines()
        msg = err[-1] if err else f"ffprobe exit {result.returncode}"
        raise ProbeError(msg.replace(f"{path}: ", "").strip())
    try:
        data = json.loads(result.stdout or "{}")
    except ValueError:
        raise ProbeError("ffprobe returned unreadable output")

    streams = data.get("streams", [])
    # Cover art / thumbnails show up as "video" streams with attached_pic set.
    video = [s for s in streams if s.get("codec_type") == "video"
             and not (s.get("disposition") or {}).get("attached_pic")]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    fmt = data.get("format", {})
    if not video and not audio:
        raise ProbeError("no audio or video streams")

    out = {
        "container": fmt.get("format_name"),
        "duration": _num(fmt.get("duration")),
        "has_video": bool(video),
        "has_audio": bool(audio),
    }
    if video:
        v = video[0]
        out.update(video_codec=v.get("codec_name"), width=v.get("width"),
                   height=v.get("height"))
    if audio:
        out["audio_codec"] = audio[0].get("codec_name")
    out["kind"] = "video" if video else "audio_only"
    return out


def describe(path, hash_names):
    """Everything the catalog stores about a file. Raises ProbeError."""
    details = probe(path)
    st = os.stat(path)
    hashes = {"xxh64": hashing.whole_file_xxh64(path)}
    hashes.update(hashing.file_hashes(path, hash_names))
    info = {
        "filename": os.path.basename(path),
        "size": st.st_size,
        "mtime": store.utc_from_timestamp(st.st_mtime),
        "hashes": hashes,
    }
    info.update(details)
    return info


def unchanged(path, file_info):
    """True if the file on disk still matches the size and date recorded."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    return (st.st_size == file_info.get("size")
            and store.utc_from_timestamp(st.st_mtime) == file_info.get("mtime"))


def _num(value):
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None
