"""move: put account folders where the settings say they belong.

Use it after changing [tiktok.drives] (moving categories to another
drive), after changing an account's primary category, or after
changing folder_template. Blocked accounts go to the blocked folder.

Also how files get in during migration: drop them in any drive's
mogul_incoming/tiktok/<account id>/ and run move; it checks every drive.

For each account it looks for the account's folder (plain or zero-padded
ID, either works) in every drive's library, blocked and incoming folders,
plus any --from folders you give (e.g. a drive you've already taken out
of the settings), and moves the files into the folder the settings point
at now.

  Same drive:  a quick rename.
  Other drive: copy to a .part file, check size + xxh64 match, rename it
               into place, then remove the original.

Nothing is ever overwritten. If the destination already has a file with
that name, the original is left where it is and reported (DUPLICATE if
it's byte-for-byte the same, CONFLICT if it differs), so you can check
and delete by hand. Empty folders left behind are removed.

Video names don't change and the catalog stores no paths, so nothing in
the catalog needs updating: afterwards it just finds the files in the
new place.
"""

import os
import shutil

from mogul_core import hashing
from mogul_core.progress import Progress

from . import naming
from .common import add_filters, setup, write_report


def same_device(src, dst_dir):
    probe = dst_dir
    while not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            return False
        probe = parent
    return os.stat(src).st_dev == os.stat(probe).st_dev


def move_file(src, dst):
    """Move one file safely. Returns 'renamed' or 'copied'."""
    dst_dir = os.path.dirname(dst)
    if same_device(src, dst_dir):
        os.makedirs(dst_dir, exist_ok=True)
        os.rename(src, dst)
        return "renamed"
    os.makedirs(dst_dir, exist_ok=True)
    part = dst + ".part"
    shutil.copy2(src, part)
    with open(part, "rb") as f:
        os.fsync(f.fileno())
    if os.path.getsize(part) != os.path.getsize(src) or \
            hashing.whole_file_xxh64(part) != hashing.whole_file_xxh64(src):
        os.remove(part)
        raise OSError("copy didn't match the original (original kept)")
    os.replace(part, dst)
    os.remove(src)
    return "copied"


def files_in(folder):
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    return [os.path.join(folder, n) for n in names
            if not n.startswith(".") and not n.endswith(".part")
            and os.path.isfile(os.path.join(folder, n))]


def remove_empty(folder, stop_at):
    """Remove folder and empty parents, up to (not including) stop_at."""
    folder = os.path.abspath(folder)
    stop_at = os.path.abspath(stop_at)
    while folder.startswith(stop_at + os.sep):
        try:
            os.rmdir(folder)
        except OSError:
            return
        folder = os.path.dirname(folder)


def relocate_folder(src_dir, dst_dir):
    """Move every file from one account folder to another (used by block and
    unblock). Never overwrites. Returns (moved, left) lists of filenames."""
    moved, left = [], []
    for src in files_in(src_dir):
        dst = os.path.join(dst_dir, os.path.basename(src))
        if os.path.exists(dst):
            left.append(os.path.basename(src))
            continue
        try:
            move_file(src, dst)
            moved.append(os.path.basename(src))
        except OSError:
            left.append(os.path.basename(src))
    try:
        os.rmdir(src_dir)  # only if it's empty now
    except OSError:
        pass
    return moved, left


def run(args, config):
    s, cat = setup(config)
    accs = cat.select(name=args.name, category=args.category, statuses=None)
    if not accs:
        print("No accounts match.")
        return
    # every drive's library, blocked and incoming folders, plus any --from
    roots = []
    for r in s.library_roots + s.blocked_roots + s.incoming_roots:
        if r not in roots:
            roots.append(r)
    for extra in args.source or []:
        extra = os.path.abspath(os.path.expanduser(extra))
        if not os.path.isdir(extra):
            raise SystemExit(f"Folder not found: {extra}")
        if extra not in roots:
            roots.append(extra)
    templates = [s.folder_template] + ([args.old_template] if args.old_template else [])
    # Folders named with the plain ID or the zero-padded one both count
    # (old Musical.ly-era IDs like 29204145 are shorter than 19 digits).
    for tpl in list(templates):
        for a, b in (("{uid19}", "{uid}"), ("{uid}", "{uid19}")):
            alt = tpl.replace(a, b)
            if a in tpl and alt not in templates:
                templates.append(alt)

    plan = []  # (account, src, dst, root)
    for acc in accs:
        target = naming.account_folder(s, acc)
        for root in roots:
            for tpl in templates:
                folder = naming.account_folder(s, acc, base=root, template=tpl)
                if os.path.abspath(folder) == os.path.abspath(target):
                    continue
                for src in files_in(folder):
                    plan.append((acc, src, os.path.join(target, os.path.basename(src)), root))
    # one file can match more than one way; keep the first
    seen, unique = set(), []
    for item in plan:
        if item[1] not in seen:
            seen.add(item[1])
            unique.append(item)
    plan = unique

    if not plan:
        print("Everything is already where the settings say. Nothing to move.\n"
              "If files are on a drive you've taken out of the settings, point at it: "
              "move --from /that/drive/folder")
        return
    by_acc = {}
    for acc, src, dst, _ in plan:
        by_acc.setdefault(acc.uid, (acc, os.path.dirname(src), os.path.dirname(dst), []))[3].append(src)
    print(f"{len(plan):,} file(s) to move for {len(by_acc)} account(s):\n")
    for acc, src_dir, dst_dir, items in by_acc.values():
        size = sum(os.path.getsize(p) for p in items)
        print(f"  @{acc.handle}: {len(items):,} files, {size / 1073741824:.2f} GB\n"
              f"      from {src_dir}\n      to   {dst_dir}")
    if args.dry_run:
        print("\nDRY RUN — nothing moved")
        return
    print()

    progress = Progress([p[1] for p in plan])
    report = {"moved": [], "duplicate": [], "conflict": [], "errors": []}
    for n, (acc, src, dst, root) in enumerate(plan, 1):
        tag = progress.tag(n)
        name = os.path.basename(src)
        if os.path.exists(dst):
            same = (os.path.getsize(dst) == os.path.getsize(src)
                    and hashing.whole_file_xxh64(dst) == hashing.whole_file_xxh64(src))
            key = "duplicate" if same else "conflict"
            print(f"{tag} {key.upper():<9} {name}  (already in the new folder; original left)")
            report[key].append({"from": src, "to": dst})
            continue
        try:
            how = move_file(src, dst)
        except OSError as e:
            print(f"{tag} ERROR     {name}  ({e})")
            report["errors"].append({"from": src, "to": dst, "error": str(e)})
            continue
        print(f"{tag} {how.upper():<9} {name}")
        report["moved"].append({"from": src, "to": dst, "how": how})
        remove_empty(os.path.dirname(src), root)

    print(f"\n{'─' * 50}")
    print(f"Moved      : {len(report['moved']):,}")
    if report["duplicate"]:
        print(f"Duplicates : {len(report['duplicate']):,} (same file already there; originals left "
              "for you to delete)")
    if report["conflict"]:
        print(f"Conflicts  : {len(report['conflict']):,} (different file with the same name; "
              "both kept, check by hand)")
    if report["errors"]:
        print(f"Errors     : {len(report['errors']):,}")
    print(f"Time       : {progress.elapsed()}")
    write_report(s, "move", report)


def add_arguments(p):
    add_filters(p)
    p.add_argument("--from", dest="source", action="append", metavar="PATH",
                   help="also look in this library folder (e.g. an old drive no longer in "
                        "the settings); can be given more than once")
    p.add_argument("--old-template", metavar="TEMPLATE",
                   help="the folder_template the files are in now, if you changed it "
                        "(e.g. \"{uid19}\")")
    p.add_argument("--dry-run", action="store_true", help="show what would move")
