"""scan: catalog videos already sitting in the library.

For starting fresh with an existing collection (point library at your old
tiktok_cache in mogul.local.toml, add the accounts, then scan), and as a
health check later. Read-only: never moves, renames or deletes anything.

A file is matched to an account by its folder (the folder name holds the
account ID with the default folder_template), or by its video ID if update
already listed it. The video ID comes from the filename.

Results per file:
  ADDED      new to the catalog: details and hashes saved
  ALREADY    already cataloged, unchanged
  RELINKED   cataloged under another filename that's gone; now points here
  CHANGED    same file name, but size or date changed: re-read and saved
  DUPLICATE  a second file for a video that already has one; not recorded
  MISPLACED  belongs to a known account but isn't in that account's folder
  UNKNOWN    no account matches (add the account, then scan again)
  NO ID      no video ID in the filename
Then:
  MISSING    cataloged files that aren't on disk anymore
             (--forget-missing clears them so download fetches them again)
"""

import os

from mogul_core import store
from mogul_core.progress import Progress

from . import naming
from .common import add_filters, setup, write_report
from .media import ProbeError, describe, unchanged


def account_from_path(cat, path, root):
    """Find an account from a numeric folder name anywhere in the path."""
    rel = os.path.relpath(os.path.dirname(path), root)
    for part in reversed(rel.split(os.sep)):
        digits = part.split("_", 1)[0]  # also accepts old "<uid>_<handle>" folders
        if digits.isdigit():
            acc = cat.by_uid(digits)
            if acc:
                return acc
    return None


def walk(folder, exts):
    out = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            if os.path.splitext(name)[1].lower() in exts:
                out.append(os.path.join(dirpath, name))
    return out


def run(args, config):
    s, cat = setup(config)
    root = os.path.abspath(args.path) if args.path else s.library_dir
    if not os.path.isdir(root):
        print(f"Folder not found: {root}")
        return
    if args.name or args.category:
        accs = cat.select(name=args.name, category=args.category, statuses=None)
        if not accs:
            print("No accounts match.")
            return
        folders = [naming.account_folder(s, a) for a in accs]
        files = [f for d in folders if os.path.isdir(d) for f in walk(d, s.ext_set)]
        limit_to = {a.uid for a in accs}
    else:
        files = walk(root, s.ext_set)
        limit_to = None

    by_video = {}
    for acc in cat.all():
        for vid in acc.videos:
            by_video.setdefault(vid, acc)

    print(f"Scanning {len(files):,} file(s) in {root}" + (" (dry run)" if args.dry_run else "") + "\n")
    progress = Progress(files)
    report = {k: [] for k in ("added", "already", "relinked", "changed", "duplicate",
                              "misplaced", "unknown", "no_id", "problems", "missing")}
    seen = set()

    for n, path in enumerate(files, 1):
        tag = progress.tag(n)
        name = os.path.basename(path)
        vid = naming.video_id_from_name(name)
        if not vid:
            print(f"{tag} NO ID      {name}")
            report["no_id"].append(path)
            continue
        acc = account_from_path(cat, path, root) or by_video.get(vid)
        if not acc:
            print(f"{tag} UNKNOWN    {name}")
            report["unknown"].append({"path": path, "video_id": vid})
            continue
        expected = naming.account_folder(s, acc)
        if os.path.abspath(os.path.dirname(path)) != os.path.abspath(expected):
            print(f"{tag} MISPLACED  {name}  (belongs to @{acc.handle}: {expected})")
            report["misplaced"].append({"path": path, "video_id": vid,
                                        "uploader_id": acc.uid, "should_be_in": expected})
            continue

        v = acc.video(vid)
        f = v.get("file")
        seen.add((acc.uid, vid))
        if f and f.get("location") != "quarantine":
            current = naming.file_path(s, acc, v)
            if f["filename"] == name:
                if unchanged(path, f):
                    report["already"].append(path)
                    continue
                action = "CHANGED"
            elif os.path.exists(current):
                print(f"{tag} DUPLICATE  {name}  (already have {f['filename']})")
                report["duplicate"].append({"path": path, "video_id": vid,
                                            "uploader_id": acc.uid, "cataloged": f["filename"]})
                continue
            else:
                action = "RELINKED"
        else:
            action = "ADDED"

        when = store.now()
        status = v.setdefault("status", {})
        try:
            info = describe(path, s.hashes)
        except ProbeError as e:
            st = os.stat(path)
            info = {"filename": name, "size": st.st_size,
                    "mtime": store.utc_from_timestamp(st.st_mtime)}
            status["check"] = {"result": "unreadable", "date": when, "error": str(e)}
            report["problems"].append({"path": path, "error": str(e)})
            print(f"{tag} {action:<10} {name}  (can't read it: {e})")
        else:
            if info["kind"] == "audio_only":
                status["check"] = {"result": "audio_only", "date": when}
            elif info["has_audio"]:
                if (status.get("check") or {}).get("result") not in ("ok", "repaired"):
                    status["check"] = {"result": "ok", "date": when}
            elif (status.get("check") or {}).get("result") != "silent":
                status.pop("check", None)  # no audio: validate will repair
            print(f"{tag} {action:<10} {name}" + ("" if info["has_audio"] else "  (no audio)"))
        info["location"] = "library"
        info["added"] = (f or {}).get("added") or when
        v["file"] = info
        status.setdefault("downloaded", info["mtime"])
        status.pop("skip", None)
        report[action.lower()].append({"path": path, "video_id": vid, "uploader_id": acc.uid})
        if not args.dry_run:
            acc.save()  # after every file, so Ctrl-C keeps progress

    # Cataloged library files that weren't found (only for the folders scanned).
    if not args.path:
        for acc in cat.all():
            if limit_to is not None and acc.uid not in limit_to:
                continue
            changed = False
            for vid, v in acc.files():
                if v["file"].get("location") == "quarantine" or (acc.uid, vid) in seen:
                    continue
                if os.path.exists(naming.file_path(s, acc, v)):
                    continue
                print(f"MISSING    @{acc.handle}  {v['file']['filename']}")
                report["missing"].append({"uploader_id": acc.uid, "video_id": vid,
                                          "filename": v["file"]["filename"]})
                if args.forget_missing:
                    v.pop("file", None)
                    v.get("status", {}).pop("check", None)
                    v.get("status", {}).pop("downloaded", None)
                    changed = True
            if changed and not args.dry_run:
                acc.save()

    print(f"\n{'─' * 50}")
    for key in ("added", "already", "relinked", "changed", "duplicate", "misplaced",
                "unknown", "no_id", "problems", "missing"):
        if report[key]:
            print(f"{key.replace('_', ' ').title():<11}: {len(report[key]):,}")
    print(f"Time       : {progress.elapsed()}")
    if report["unknown"]:
        print("\nUNKNOWN files: add their accounts (archiver.py tiktok add ID --category X), "
              "then scan again.")
    if report["missing"] and not args.forget_missing:
        print("MISSING files: scan --forget-missing clears them so download gets them again.")
    if args.dry_run:
        print("\nDRY RUN — catalog not changed")
    write_report(s, "scan", report)


def add_arguments(p):
    add_filters(p)
    p.add_argument("--path", help="scan this folder instead of the library (reports only "
                                  "what's there; files outside the library aren't cataloged)")
    p.add_argument("--forget-missing", action="store_true",
                   help="for cataloged files no longer on disk, clear the file record so "
                        "download fetches them again")
    p.add_argument("--dry-run", action="store_true", help="write nothing to the catalog")
