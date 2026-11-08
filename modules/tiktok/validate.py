"""validate: check every downloaded file and repair missing audio.

TikTok's high-quality streams sometimes come down with no audio. The fix
(from the old validate.py): download TikTok's 'download' format, which
reliably has audio, and copy that audio track into the high-quality video
(no re-encoding). The repaired file replaces the original, and the catalog
records the repair with the original file's hash, so if yt-dlp ever gets
HQ audio working you can find these and fetch them again.

Per file:
  OK          video and audio both there
  REPAIRED    had no audio, now fixed in place
  AUDIO ONLY  no video stream (TikTok photo slideshows); .mp4 renamed to
              .m4a if rename_audio_only is on
  QUARANTINE  unreadable, or no audio and the repair failed. Moved to the
              quarantine folder. Nothing is deleted.
  MISSING     cataloged but not on disk (scan --forget-missing to re-download)

Files already checked and unchanged since are skipped (--recheck to redo).
Videos that really are silent: mark them with "mogul.py tiktok silent".
"""

import os
import shutil
import subprocess

from mogul_core import store

from . import naming
from .common import add_filters, setup, write_report
from .media import ProbeError, describe, probe, unchanged
from .ytdlp import Ytdlp, video_url

DONE = ("ok", "repaired", "audio_only", "silent")


def mux(video_path, audio_path, out_path, timeout=300):
    """HQ video from one file + audio from another, no re-encoding."""
    cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error",
           "-i", video_path, "-i", audio_path,
           "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", "-shortest", out_path]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "ffmpeg timed out"
    if r.returncode != 0 or not os.path.isfile(out_path):
        err = (r.stderr or "").strip().splitlines()
        return err[-1] if err else f"ffmpeg exit {r.returncode}"
    return None


def repair(s, yt, vid, path, timeout):
    """Fix a no-audio file in place. Returns None on success, else the reason."""
    folder = os.path.dirname(path)
    ext = os.path.splitext(path)[1]
    src = os.path.join(folder, f".{vid}.audio-src.mp4")
    out = os.path.join(folder, f".{vid}.repaired{ext}")
    try:
        print("    fetching audio from the 'download' format...", end="", flush=True)
        ok, reason = yt.fetch_audio_source(vid, src, timeout)
        if not ok:
            print(" failed")
            return f"couldn't get the download format ({reason or 'no file'})"
        try:
            if not probe(src)["has_audio"]:
                print(" it has no audio either")
                return "download format has no audio either"
        except ProbeError as e:
            print(" unreadable")
            return f"download format unreadable ({e})"
        print(" OK\n    copying audio into the HQ video...", end="", flush=True)
        err = mux(path, src, out)
        if err:
            print(" failed")
            return f"mux failed ({err})"
        try:
            check = probe(out)
        except ProbeError as e:
            print(" failed")
            return f"repaired file unreadable ({e})"
        if not (check["has_video"] and check["has_audio"]):
            print(" failed")
            return "repaired file is missing a stream"
        os.replace(out, path)
        print(" OK")
        return None
    finally:
        for tmp in (src, out):
            try:
                os.remove(tmp)
            except OSError:
                pass


def quarantine(s, acc, v, path, dry_run):
    dest_dir = naming.account_folder(s, acc, s.quarantine_dir)
    dest = os.path.join(dest_dir, os.path.basename(path))
    if dry_run:
        print(f"    would move to {dest_dir}")
        return
    os.makedirs(dest_dir, exist_ok=True)
    if os.path.exists(dest):
        print("    a file with that name is already in quarantine; left in place")
        return
    shutil.move(path, dest)
    v["file"]["location"] = "quarantine"
    print(f"    moved to {dest_dir}")


def run(args, config):
    s, cat = setup(config)
    if args.list:
        return list_problems(s, cat, args)
    accs = cat.select(name=args.name, category=args.category, statuses=None)
    if not accs:
        print("No accounts match.")
        return
    yt = Ytdlp(s, use_cookies=not args.no_cookies)
    report = {k: [] for k in ("ok", "repaired", "audio_only", "quarantined", "no_audio",
                              "missing")}
    skipped = 0
    print(f"\nValidating {len(accs)} account(s)" + (" (dry run)" if args.dry_run else "") + "...\n")

    for i, acc in enumerate(accs, 1):
        if acc.blocked and not args.name:
            continue  # blocked: you're sorting those by hand
        files = [(vid, v) for vid, v in acc.files() if v["file"].get("location") != "quarantine"]
        if not files:
            continue
        print(f"[{i}/{len(accs)}] {acc.label()}  ({len(files)} files)")
        counts = {"ok": 0, "fixed": 0, "bad": 0, "skip": 0}
        for vid, v in files:
            f = v["file"]
            status = v.setdefault("status", {})
            path = naming.file_path(s, acc, v)
            name = f["filename"]
            if not os.path.exists(path):
                print(f"  MISSING    {name}")
                report["missing"].append({"uploader_id": acc.uid, "video_id": vid, "file": name})
                continue
            if (status.get("check") or {}).get("result") in DONE and unchanged(path, f) \
                    and not args.recheck:
                counts["skip"] += 1
                continue
            when = store.now()
            item = {"uploader_id": acc.uid, "video_id": vid, "file": name}

            try:
                details = probe(path)
            except ProbeError as e:
                print(f"  QUARANTINE {name}  (unreadable: {e})")
                status["check"] = {"result": "unreadable", "date": when, "error": str(e)}
                quarantine(s, acc, v, path, args.dry_run)
                report["quarantined"].append({**item, "why": f"unreadable: {e}"})
                counts["bad"] += 1
                if not args.dry_run:
                    acc.save()
                continue

            if details["kind"] == "audio_only":
                new_path = path
                if s.rename_audio_only and path.lower().endswith(".mp4"):
                    new_path = path[:-4] + ".m4a"
                    if os.path.exists(new_path):
                        new_path = path
                    elif not args.dry_run:
                        os.replace(path, new_path)
                print(f"  AUDIO ONLY {name}"
                      + (f"  → {os.path.basename(new_path)}" if new_path != path else ""))
                if not args.dry_run:
                    v["file"] = {**describe(new_path, s.hashes), "location": "library",
                                 "added": f.get("added")}
                    status["check"] = {"result": "audio_only", "date": when}
                report["audio_only"].append(item)
                counts["ok"] += 1

            elif details["has_audio"]:
                if not unchanged(path, f) and not args.dry_run:
                    v["file"] = {**describe(path, s.hashes), "location": "library",
                                 "added": f.get("added")}
                if (status.get("check") or {}).get("result") != "repaired":
                    status["check"] = {"result": "ok", "date": when}
                counts["ok"] += 1
                report["ok"].append(item)

            elif args.no_repair:
                print(f"  NO AUDIO   {name}")
                report["no_audio"].append(item)
                counts["bad"] += 1
                continue

            else:
                print(f"  NO AUDIO   {name}  {video_url(vid, acc.handle)}")
                if args.dry_run:
                    print("    would fetch the 'download' format and copy its audio in")
                    report["repaired"].append(item)
                    continue
                before = {"size": f.get("size"), "xxh64": (f.get("hashes") or {}).get("xxh64")}
                err = repair(s, yt, vid, path, args.timeout or s.timeout)
                if err is None:
                    v["file"] = {**describe(path, s.hashes), "location": "library",
                                 "added": f.get("added")}
                    status["check"] = {"result": "repaired", "date": when}
                    status["repaired"] = {"date": when, "original": before,
                                          "note": "audio copied in from TikTok's 'download' "
                                                  "format; HQ video kept"}
                    report["repaired"].append(item)
                    counts["fixed"] += 1
                else:
                    print(f"    repair failed: {err}")
                    status["check"] = {"result": "no_audio", "date": when, "error": err}
                    status["repair_attempts"] = status.get("repair_attempts", 0) + 1
                    quarantine(s, acc, v, path, False)
                    report["quarantined"].append({**item, "why": f"no audio: {err}"})
                    counts["bad"] += 1
            if not args.dry_run:
                acc.save()
        skipped += counts["skip"]
        print(f"  ok {counts['ok']}   repaired {counts['fixed']}   problems {counts['bad']}"
              f"   already checked {counts['skip']}")

    print(f"\n{'═' * 50}")
    print(f"OK           : {len(report['ok'])}")
    print(f"Repaired     : {len(report['repaired'])}")
    print(f"Audio only   : {len(report['audio_only'])}")
    print(f"Quarantined  : {len(report['quarantined'])}  ({s.quarantine_dir})")
    if report["no_audio"]:
        print(f"No audio     : {len(report['no_audio'])}  (not repaired: --no-repair)")
    if report["missing"]:
        print(f"Missing      : {len(report['missing'])}")
    print(f"Already done : {skipped}")
    if args.dry_run:
        print("\nDRY RUN — nothing changed")
    else:
        write_report(s, "validate", report)


def list_problems(s, cat, args):
    accs = cat.select(name=args.name, category=args.category, statuses=None)
    found = 0
    repaired = 0
    for acc in accs:
        rows = []
        for vid, v in acc.files():
            st = v.get("status") or {}
            if st.get("repaired"):
                repaired += 1
            if v["file"].get("location") == "quarantine":
                chk = st.get("check") or {}
                rows.append((v["file"]["filename"], chk.get("result", "?"), chk.get("error", ""),
                             video_url(vid, acc.handle)))
        if rows:
            print(f"\n{acc.label()}  — quarantined: {len(rows)}")
            for name, result, err, url in rows:
                print(f"  {name}  [{result}] {err}\n    {url}")
            found += len(rows)
    print(f"\n{found} quarantined, {repaired} repaired so far.")
    if found:
        print(f"Quarantine folder: {s.quarantine_dir}\n"
              "Really silent? Mark them: mogul.py tiktok silent VIDEO_ID ... "
              "(or --folder PATH)")


def silent(args, config):
    """Mark videos as really silent (fine with no audio) and bring them back
    from quarantine. Replaces the old mark_valid.py + validate.sh."""
    s, cat = setup(config)
    ids = [i for i in (args.ids or [])]
    if args.folder:
        for name in sorted(os.listdir(args.folder)):
            vid = naming.video_id_from_name(name)
            if vid:
                ids.append(vid)
            elif not name.startswith("."):
                print(f"SKIP (no video ID in name): {name}")
    if not ids:
        raise SystemExit("Give video IDs, or --folder with the files (e.g. a quarantine folder).")
    owners = {}
    for acc in cat.all():
        for vid in acc.videos:
            owners.setdefault(vid, acc)
    marked = 0
    for vid in ids:
        acc = owners.get(vid)
        v = acc.videos.get(vid) if acc else None
        if not v or not v.get("file"):
            print(f"NOT FOUND: {vid} has no cataloged file")
            continue
        f = v["file"]
        when = store.now()
        if f.get("location") == "quarantine":
            src = naming.file_path(s, acc, v)
            dest_dir = naming.account_folder(s, acc)
            dest = os.path.join(dest_dir, f["filename"])
            if os.path.exists(dest):
                print(f"  {vid}: a file named {f['filename']} is already in the library; "
                      "left in quarantine")
                continue
            if os.path.exists(src):
                os.makedirs(dest_dir, exist_ok=True)
                shutil.move(src, dest)
            f["location"] = "library"
            moved = " (moved back to the library)"
        else:
            moved = ""
        v.setdefault("status", {})["check"] = {"result": "silent", "date": when}
        acc.save()
        marked += 1
        print(f"SILENT: @{acc.handle} {f['filename']}{moved}")
    print(f"\nMarked {marked} of {len(ids)}.")


def add_arguments(action, p):
    if action == "validate":
        add_filters(p)
        p.add_argument("--recheck", action="store_true",
                       help="check files again even if already checked and unchanged")
        p.add_argument("--no-repair", action="store_true",
                       help="only report files with no audio, don't repair or move them")
        p.add_argument("--list", action="store_true",
                       help="show quarantined files and why, change nothing")
        p.add_argument("--timeout", type=int, help="seconds for the repair download")
        p.add_argument("--dry-run", action="store_true", help="report only, change nothing")
        p.add_argument("--no-cookies", action="store_true", help="don't use cookies.txt")
    else:
        p.add_argument("ids", nargs="*", help="TikTok video IDs")
        p.add_argument("--folder", help="mark every video in this folder (IDs from filenames)")
