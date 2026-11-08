"""download: fetch every listed video that doesn't have a file yet.

Run update first so the catalog knows what each account has posted.

Per video:
  OK       downloaded, renamed to filename_template, details + hashes saved
  SKIP     a problem with that one video (deleted, private, photo post...).
           Saved with the reason so it isn't tried again every run.
           See them with: mogul.py tiktok skipped
  ERROR    a problem with the account or connection (rate limit, login
           needed, timeout). Counts toward flagging the account.

Files that come down with no audio are left for validate to repair.
"""

import glob
import os
import time

from mogul_core import store

from . import naming
from .common import add_filters, elapsed, pause, setup, write_report, ytdlp_escape
from .media import ProbeError, describe
from .ytdlp import DISCARDED, PERMANENT, Ytdlp, video_url


def pending(acc):
    """Listed videos with no file and not skipped, newest first."""
    out = []
    for vid, v in acc.videos.items():
        if v.get("listing") and not v.get("file") and not (v.get("status") or {}).get("skip"):
            out.append(vid)
    return sorted(out, key=int, reverse=True)


def find_downloaded(folder, vid):
    hits = [p for p in glob.glob(os.path.join(glob.escape(folder), f"{vid}.*"))
            if not p.endswith((".part", ".ytdl", ".tmp")) and os.path.isfile(p)]
    return max(hits, key=os.path.getsize) if hits else None


def unique_path(path):
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{stem}-{n}{ext}"):
        n += 1
    return f"{stem}-{n}{ext}"


def store_file(s, acc, vid, path, when):
    """Rename a freshly downloaded file into place and record it."""
    v = acc.video(vid)
    status = v.setdefault("status", {})
    try:
        details = describe(path, s.hashes)
    except ProbeError as e:
        details = None
        problem = str(e)
    ext = os.path.splitext(path)[1].lstrip(".").lower() or "mp4"
    if details and details["kind"] == "audio_only" and ext == "mp4" and s.rename_audio_only:
        ext = "m4a"
    final = unique_path(os.path.join(os.path.dirname(path),
                                     naming.video_filename(s, vid, v, ext)))
    os.replace(path, final)
    if details is None:
        st = os.stat(final)
        v["file"] = {"filename": os.path.basename(final), "size": st.st_size,
                     "mtime": store.utc_from_timestamp(st.st_mtime)}
        status["check"] = {"result": "unreadable", "date": when, "error": problem}
    else:
        details["filename"] = os.path.basename(final)
        v["file"] = details
        if details["kind"] == "audio_only":
            status["check"] = {"result": "audio_only", "date": when}
        elif details["has_audio"]:
            status["check"] = {"result": "ok", "date": when}
        # video with no audio: left unchecked so validate repairs it
    v["file"]["location"] = "library"
    v["file"]["added"] = when
    status["downloaded"] = when
    status.pop("skip", None)
    return v["file"], status.get("check", {}).get("result", "needs repair")


def run(args, config):
    s, cat = setup(config)
    accs = cat.select(name=args.name, category=args.category)
    if not accs:
        print("No accounts to download.")
        return
    yt = Ytdlp(s, use_cookies=not args.no_cookies)
    timeout = args.timeout or s.timeout
    report = {"downloaded": [], "skipped": [], "errors": [], "accounts_skipped": []}
    start = time.monotonic()
    print(f"\nDownloading for {len(accs)} account(s)...\n")

    for i, acc in enumerate(accs, 1):
        print(f"{elapsed(start)} [{i}/{len(accs)}] @{acc.handle} ({acc.category})")
        if acc.flagged and not args.force:
            print("  SKIPPED — flagged (see mogul.py tiktok flagged)")
            report["accounts_skipped"].append({"uploader_id": acc.uid, "why": "flagged"})
            continue
        listed = sum(1 for v in acc.videos.values() if v.get("listing"))
        if not listed:
            print("  SKIPPED — no video list yet (run update first)")
            report["accounts_skipped"].append({"uploader_id": acc.uid, "why": "not updated"})
            continue

        todo = pending(acc)
        have = sum(1 for v in acc.videos.values() if v.get("file"))
        skips = sum(1 for v in acc.videos.values() if (v.get("status") or {}).get("skip"))
        capped = bool(args.limit and len(todo) > args.limit)
        if args.limit:
            todo = todo[:args.limit]
        print(f"  listed {listed:,}   have {have:,}   skipped {skips:,}   "
              f"to download {len(todo):,}" + ("  (capped by --limit)" if capped else ""))
        if not todo:
            continue

        folder = naming.account_folder(s, acc)
        if args.dry_run:
            for vid in todo:
                v = acc.videos[vid]
                title = ((v.get("listing") or {}).get("title") or "")[:60]
                print(f"    would get {naming.video_filename(s, vid, v, 'mp4')}  {title}")
            continue
        os.makedirs(folder, exist_ok=True)

        ok = skipped = errors = 0
        for j, vid in enumerate(todo, 1):
            v = acc.videos[vid]
            listing = v.get("listing") or {}
            title = (listing.get("title") or "")[:50]
            print(f"    [{j}/{len(todo)}] {vid}  {title}", end="", flush=True)
            when = store.now()
            url = listing.get("url") or video_url(vid, acc.handle)
            template = os.path.join(ytdlp_escape(folder), f"{vid}.%(ext)s")
            success, reason, level, stderr = yt.download(url, template, timeout)

            if success:
                path = find_downloaded(folder, vid)
                if not path:
                    success, reason, level = False, "yt-dlp finished but no file appeared", "video"
            if success:
                info, result = store_file(s, acc, vid, path, when)
                print(f" — OK ({info['size'] / 1048576:.1f} MB"
                      + ("" if result == "ok" else f", {result.replace('_', ' ')}") + ")")
                report["downloaded"].append({"uploader_id": acc.uid, "video_id": vid,
                                             "filename": info["filename"], "check": result})
                ok += 1
            elif level == "video":
                v.setdefault("status", {})["skip"] = {
                    "reason": reason, "permanent": reason in PERMANENT, "date": when}
                print(f" — SKIP: {reason}")
                report["skipped"].append({"uploader_id": acc.uid, "video_id": vid,
                                          "reason": reason,
                                          "yt_dlp": stderr.splitlines()[-3:] if stderr else []})
                skipped += 1
            else:
                print(f" — ERROR: {reason}")
                report["errors"].append({"uploader_id": acc.uid, "video_id": vid,
                                         "reason": reason,
                                         "yt_dlp": stderr.splitlines()[-3:] if stderr else []})
                errors += 1
                if acc.record_error(reason, s.error_threshold, when):
                    print(f"  ⚑ FLAGGED after {s.error_threshold} errors in a row — "
                          "stopping this account")
                    acc.save()
                    break
            acc.save()  # after every video, so Ctrl-C keeps progress
            if j < len(todo):
                pause(s.video_delay_min, s.video_delay_max)

        if ok:
            acc.state["last_downloaded"] = store.now()
            acc.clear_errors()
            acc.save()
        print(f"  done: {ok} downloaded, {skipped} skipped, {errors} errors")
        if i < len(accs):
            pause(s.rate_min, s.rate_max)

    print(f"\n{'═' * 50}")
    print(f"Time        : {elapsed(start)}")
    print(f"Downloaded  : {len(report['downloaded'])}")
    print(f"Skipped     : {len(report['skipped'])}  (see mogul.py tiktok skipped)")
    print(f"Errors      : {len(report['errors'])}")
    needs = sum(1 for d in report["downloaded"] if d["check"] == "needs repair")
    if needs:
        print(f"No audio    : {needs}  (run mogul.py tiktok validate to repair)")
    if args.dry_run:
        print("\nDRY RUN — nothing was downloaded")
    else:
        write_report(s, "download", report)


def skipped(args, config):
    """List skipped videos by reason, or clear them so download retries."""
    s, cat = setup(config)
    accs = cat.select(name=args.name, category=args.category, statuses=None)
    want = (args.reason or "").lower()
    groups = {}
    for acc in accs:
        for vid, v in acc.videos.items():
            sk = (v.get("status") or {}).get("skip")
            if sk and want in sk["reason"].lower():
                groups.setdefault(sk["reason"], []).append((acc, vid, v))
    if not groups:
        print("No skipped videos" + (f" matching '{args.reason}'" if want else "") + ".")
        return

    if not args.retry:
        for reason, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            perm = " (permanent)" if reason in PERMANENT else ""
            print(f"\n{reason}{perm}: {len(items)}")
            if args.verbose:
                for acc, vid, v in items:
                    print(f"  @{acc.handle}  {video_url(vid, acc.handle)}")
        total = sum(len(i) for i in groups.values())
        print(f"\n{total} skipped. Retry with: skipped --retry [--reason TEXT] [--all-reasons]")
        return

    cleared, kept = 0, 0
    touched = set()
    for reason, items in groups.items():
        if reason == DISCARDED and "discard" not in want:
            kept += len(items)  # your own deletions: only with --reason discarded
            continue
        if reason in PERMANENT and not args.all_reasons:
            kept += len(items)
            continue
        for acc, vid, v in items:
            if not args.dry_run:
                v["status"].pop("skip", None)
                touched.add(acc)
            cleared += 1
    for acc in touched:
        acc.save()
    verb = "Would clear" if args.dry_run else "Cleared"
    print(f"{verb} {cleared} skip(s); download will try them again.")
    if kept:
        print(f"Left {kept} permanent ones alone (deleted, private, photo posts, ones you "
              "discarded). --all-reasons retries the TikTok ones; --reason discarded "
              "brings back your own discards.")


def add_arguments(action, p):
    add_filters(p)
    if action == "download":
        p.add_argument("--limit", type=int, help="at most this many new videos per account")
        p.add_argument("--force", action="store_true", help="download for flagged accounts too")
        p.add_argument("--timeout", type=int, help="seconds per video (default from mogul.toml)")
        p.add_argument("--dry-run", action="store_true", help="list what would be downloaded")
        p.add_argument("--no-cookies", action="store_true", help="don't use cookies.txt")
    else:
        p.add_argument("--reason", help="only skips whose reason contains this text")
        p.add_argument("--retry", action="store_true",
                       help="clear the skips so download tries again")
        p.add_argument("--all-reasons", action="store_true",
                       help="with --retry: include permanent ones (deleted, private, photo posts)")
        p.add_argument("--verbose", action="store_true", help="list every skipped video's link")
        p.add_argument("--dry-run", action="store_true", help="with --retry: just count")
