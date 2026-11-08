"""import-old: bring the old scripts' data into the catalog.

Reads the old tiktok_metadata folder (read-only, nothing there is changed):

  accounts.db                 accounts, handles, categories/tags, notes,
                              block list, timeout overrides
  flatdump_archive/<uid>/     old listings, one gzipped JSON per change,
    YYYY-MM-DD_HH-MM-SS.json.gz   named by when it was replaced (UTC)
  flatdumps/<uid>.json        the latest listing per account (dated by the
                              file's modified time)
  validate/<uid>.db           download skip lists, and which files were
                              marked silent or had audio repaired
  audio_fixed.jsonl           log of audio repairs

--dumps PATH adds any other folders of old dumps (.json or .json.gz,
any names, searched in subfolders too). The account comes from the dump
itself, the date from a YYYY-MM-DD_HH-MM-SS in the filename if there is
one, otherwise the file's modified time.

Listings are merged oldest first with the same rules as update
(listing.py): every video ever seen is kept, with first/last seen dates
and not_listed_since for ones that disappeared.

--category / --name import just part of it, so it can be done in chunks
(one category at a time). The block list comes over on an unfiltered run.

Safe to run more than once: it only adds what's missing and never
overwrites newer information with older.

Video files aren't touched: run scan afterwards to catalog them.
"""

import datetime
import gzip
import json
import os
import re
import sqlite3

from mogul_core import store

from . import listing
from .catalog import clean_name, split_tags
from .common import setup, write_report
from .ytdlp import PERMANENT

STAMP_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})")


def iso(value):
    """Old timestamps ('2026-06-16T14:23:11.123456+00:00') → '2026-06-16T14:23:11Z'."""
    if not value:
        return None
    try:
        d = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return (d.astimezone(datetime.timezone.utc).replace(microsecond=0)
            .isoformat().replace("+00:00", "Z"))


def date_from_name(path):
    m = STAMP_RE.search(os.path.basename(path))
    if not m:
        return None
    y, mo, d, h, mi, s = (int(x) for x in m.groups())
    try:
        return datetime.datetime(y, mo, d, h, mi, s, tzinfo=datetime.timezone.utc) \
            .isoformat().replace("+00:00", "Z")
    except ValueError:
        return None


def load_dump(path):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def dump_uid(dump):
    for e in dump.get("entries") or []:
        if e and e.get("uploader_id"):
            return str(e["uploader_id"])
    uid = dump.get("uploader_id") or dump.get("id")
    return str(uid) if uid and str(uid).isdigit() else None


def open_db(path):
    if not os.path.isfile(path):
        return None
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_rows(conn, sql, args=()):
    try:
        return conn.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []  # table missing in older databases


# ─── gathering ──────────────────────────────────────────────────────────

def find_dumps(meta, extra):
    """{uid: [(when, path), ...]} from every dump location."""
    found = {}

    def add(uid, when, path):
        if uid and when:
            found.setdefault(uid, []).append((when, path))

    archive = os.path.join(meta, "flatdump_archive")
    if os.path.isdir(archive):
        for uid in os.listdir(archive):
            folder = os.path.join(archive, uid)
            if uid.isdigit() and os.path.isdir(folder):
                for name in os.listdir(folder):
                    if name.endswith((".json", ".json.gz")):
                        p = os.path.join(folder, name)
                        add(uid, date_from_name(p) or mtime(p), p)
    live = os.path.join(meta, "flatdumps")
    if os.path.isdir(live):
        for name in os.listdir(live):
            uid = name.split(".", 1)[0]
            if uid.isdigit() and name.endswith((".json", ".json.gz")):
                p = os.path.join(live, name)
                add(uid, mtime(p), p)
    unknown = []
    for folder in extra:
        for dirpath, _, names in os.walk(folder):
            for name in names:
                if not name.endswith((".json", ".json.gz")) or name == "manifest.json":
                    continue
                p = os.path.join(dirpath, name)
                try:
                    uid = dump_uid(load_dump(p))
                except (OSError, ValueError, EOFError):
                    unknown.append(p)
                    continue
                if uid:
                    add(uid, date_from_name(p) or mtime(p), p)
                else:
                    unknown.append(p)
    for uid in found:
        found[uid] = sorted(set(found[uid]), key=lambda wp: listing.t(wp[0]))
    return found, unknown


def mtime(path):
    return store.utc_from_timestamp(os.path.getmtime(path))


# ─── the import ─────────────────────────────────────────────────────────

def merge_account(cat, row, tags, when_now):
    """Create or fill in one account from an accounts.db row."""
    keys = row.keys()
    get = lambda k: row[k] if k in keys else None  # noqa: E731
    uid = str(get("uploader_id"))
    category = (get("category") or "general").lower().strip()
    tags = [category] + [t for t in sorted(set(tags)) if t != category]
    added = iso(get("added_at")) or when_now
    status = (get("status") or "active").lower()
    old_blocked = status == "blocked"
    if old_blocked:
        status = "removed"  # blocked = removed + a "blocked" mark (see below)
    elif status not in ("active", "empty", "removed"):
        status = "active"
    acc = cat.by_uid(uid)
    created = acc is None
    if created:
        acc = cat.create(uid, get("handle") or uid, added,
                         display_name=get("display_name"), channel_url=get("channel_url"),
                         category=category, tags=tags,
                         status=status, notes=get("notes"))
        acc.info["added"] = added
        for h in acc.info.get("handles", []):
            h["first_seen"] = added
    else:
        acc.info["tags"] = sorted(set(acc.tags) | set(tags),
                                  key=lambda t: (t != acc.category, t))
        for key in ("display_name", "channel_url", "notes"):
            if not acc.info.get(key) and get(key):
                acc.info[key] = get(key)
        old_added = listing.t(acc.info.get("added"))
        if added and old_added and listing.t(added) < old_added:
            acc.info["added"] = added
        old = (get("handle") or "").lstrip("@")
        history = acc.info.setdefault("handles", [])
        if old and not old.isdigit() and not any(h["handle"].lower() == old.lower() for h in history):
            history.insert(0, {"handle": old, "first_seen": added})  # history only
    if old_blocked and not acc.info.get("blocked"):
        acc.info["blocked"] = {"date": when_now, "reason": "blocked in the old scripts"}
        acc.info["status"] = "removed"
    if get("timeout_override") and not acc.state.get("timeout_override"):
        acc.state["timeout_override"] = get("timeout_override")
    if get("last_duration") and not acc.state.get("last_duration"):
        acc.state["last_duration"] = get("last_duration")
    return acc, created


def run(args, config):
    s, cat = setup(config)
    meta = os.path.abspath(os.path.expanduser(args.source))
    if not os.path.isdir(meta):
        raise SystemExit(f"Folder not found: {meta} (point --from at the old tiktok_metadata folder)")
    extra = [os.path.abspath(os.path.expanduser(p)) for p in (args.dumps or [])]
    for p in extra:
        if not os.path.isdir(p):
            raise SystemExit(f"Folder not found: {p}")
    now = store.now()
    report = {"accounts_added": [], "accounts_updated": [], "blocked_added": 0,
              "dumps": 0, "bad_dumps": [], "dumps_without_account": {},
              "videos_added": 0, "skips_added": 0, "silent": 0, "repaired": 0,
              "unknown_dumps": []}
    # Which accounts to import: None = all. --name and --category narrow it.
    want_tags = split_tags(args.category)
    filtered = bool(args.name or want_tags)
    selected = set()
    for acc in cat.select(name=args.name, category=args.category, statuses=None) \
            if filtered else []:
        selected.add(acc.uid)

    # 1. accounts + block list from accounts.db
    db = open_db(os.path.join(meta, "accounts.db"))
    if db:
        tagmap = {}
        for r in table_rows(db, "SELECT uploader_id, category FROM account_categories"):
            tagmap.setdefault(str(r["uploader_id"]), []).append(r["category"].lower().strip())
        rows = table_rows(db, "SELECT * FROM accounts ORDER BY added_at")
        if filtered:
            name = clean_name(args.name) if args.name else None
            for row in rows:
                uid = str(row["uploader_id"])
                tags = {(row["category"] or "general").lower().strip()} | set(tagmap.get(uid, []))
                if name and name not in (uid, clean_name(row["handle"] or "")):
                    continue
                if want_tags and not all(t in tags for t in want_tags):
                    continue
                selected.add(uid)
        print(f"accounts.db: {len(rows)} account(s)"
              + (f", importing {len(selected)} that match" if filtered else ""))
        for row in rows:
            uid = str(row["uploader_id"])
            if filtered and uid not in selected:
                continue
            acc, created = merge_account(cat, row, tagmap.get(uid, []), now)
            (report["accounts_added"] if created else report["accounts_updated"]).append(acc.uid)
            if not args.dry_run:
                acc.save()
        if not filtered:
            blocked = cat.blocked()
            for r in table_rows(db, "SELECT * FROM blocked"):
                handle = (r["handle"] or "").lstrip("@").lower() or None
                uid = str(r["uploader_id"]) if r["uploader_id"] else None
                if any((handle and handle == (b.get("handle") or "").lower())
                       or (uid and uid == b.get("uploader_id")) for b in blocked["blocked"]):
                    continue
                blocked["blocked"].append({"handle": handle, "uploader_id": uid,
                                           "reason": r["reason"],
                                           "blocked": iso(r["blocked_at"]) or now})
                report["blocked_added"] += 1
            if report["blocked_added"] and not args.dry_run:
                cat.save_blocked(blocked)
        db.close()
        print(f"  added {len(report['accounts_added'])}, filled in "
              f"{len(report['accounts_updated'])}, block list +{report['blocked_added']}")
    else:
        print("No accounts.db found; only accounts already in the catalog get dumps.")

    # 2. listings, oldest first
    dumps, report["unknown_dumps"] = find_dumps(meta, extra)
    total = sum(len(v) for v in dumps.values())
    print(f"\nOld listings: {total:,} dump(s) for {len(dumps):,} account(s)")
    for uid, items in sorted(dumps.items()):
        if filtered and uid not in selected:
            continue
        acc = cat.by_uid(uid)
        if not acc:
            report["dumps_without_account"][uid] = len(items)
            continue
        before = sum(1 for v in acc.videos.values() if v.get("listing"))
        for when, path in items:
            try:
                dump = load_dump(path)
            except (OSError, ValueError, EOFError) as e:
                report["bad_dumps"].append({"path": path, "error": str(e)})
                continue
            listing.merge(acc, dump.get("entries") or [], when, complete=True)
            report["dumps"] += 1
        after = sum(1 for v in acc.videos.values() if v.get("listing"))
        gone = sum(1 for v in acc.videos.values()
                   if (v.get("listing") or {}).get("not_listed_since"))
        report["videos_added"] += after - before
        if not acc.state.get("listed_count"):
            acc.state["listed_count"] = after - gone
        print(f"  @{acc.handle}: {len(items)} dump(s), {after:,} videos "
              f"(+{after - before:,})" + (f", {gone:,} no longer listed" if gone else ""))
        if not args.dry_run:
            acc.save()

    # 3. skips, silent marks and repairs from validate/<uid>.db + audio_fixed.jsonl
    vdir = os.path.join(meta, "validate")
    if os.path.isdir(vdir):
        for name in sorted(os.listdir(vdir)):
            uid = name[:-3] if name.endswith(".db") else ""
            acc = cat.by_uid(uid) if uid.isdigit() else None
            if not acc or (filtered and uid not in selected):
                continue
            conn = open_db(os.path.join(vdir, name))
            changed = False
            for r in table_rows(conn, "SELECT video_id, reason, skipped_at FROM skipped_videos"):
                v = acc.video(str(r["video_id"]))
                st = v.setdefault("status", {})
                if not v.get("file") and not st.get("skip"):
                    st["skip"] = {"reason": r["reason"], "permanent": r["reason"] in PERMANENT,
                                  "date": iso(r["skipped_at"]) or now}
                    report["skips_added"] += 1
                    changed = True
            for r in table_rows(conn, "SELECT video_id, status, checked_at FROM files "
                                      "WHERE status IN ('valid_silent', 'audio_fixed')"):
                if not r["video_id"]:
                    continue
                st = acc.video(str(r["video_id"])).setdefault("status", {})
                when = iso(r["checked_at"]) or now
                if r["status"] == "valid_silent" and not st.get("check"):
                    st["check"] = {"result": "silent", "date": when}
                    report["silent"] += 1
                    changed = True
                elif r["status"] == "audio_fixed" and not st.get("repaired"):
                    st["repaired"] = {"date": when, "note": "repaired by the old validate.py"}
                    report["repaired"] += 1
                    changed = True
            conn.close()
            if changed and not args.dry_run:
                acc.save()
    log = os.path.join(meta, "audio_fixed.jsonl")
    if os.path.isfile(log):
        touched = set()
        with open(log, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                acc = cat.by_uid(str(r.get("uploader_id") or ""))
                vid = str(r.get("video_id") or "")
                if not acc or not vid.isdigit() or (filtered and acc.uid not in selected):
                    continue
                st = acc.video(vid).setdefault("status", {})
                if not st.get("repaired"):
                    st["repaired"] = {"date": iso(r.get("fixed_at")) or now,
                                      "note": r.get("note") or "repaired by the old validate.py"}
                    report["repaired"] += 1
                    touched.add(acc)
        if not args.dry_run:
            for acc in touched:
                acc.save()

    print(f"\n{'─' * 50}")
    print(f"Accounts added    : {len(report['accounts_added'])}")
    print(f"Accounts filled in: {len(report['accounts_updated'])}")
    print(f"Dumps merged      : {report['dumps']:,}")
    print(f"Videos added      : {report['videos_added']:,}")
    print(f"Skips carried over: {report['skips_added']:,}")
    print(f"Silent / repaired : {report['silent']:,} / {report['repaired']:,}")
    if report["dumps_without_account"]:
        print(f"Dumps with no account: {len(report['dumps_without_account'])} account(s) "
              "(add them, then run import-old again)")
    if report["bad_dumps"] or report["unknown_dumps"]:
        print(f"Unreadable dumps  : {len(report['bad_dumps']) + len(report['unknown_dumps'])} "
              "(listed in the report)")
    if args.dry_run:
        print("\nDRY RUN — catalog not changed")
    else:
        print("\nNext: point library at your old tiktok_cache in mogul.local.toml, then run scan.")
    write_report(s, "import-old", report)


def add_arguments(p):
    p.add_argument("--from", dest="source", required=True,
                   help="the old tiktok_metadata folder (has accounts.db, flatdumps/, ...)")
    p.add_argument("--dumps", action="append", metavar="PATH",
                   help="another folder of old dumps to include (can be given more than once)")
    p.add_argument("--name", help="only this account (@handle or ID)")
    p.add_argument("--category",
                   help="only accounts with this category/tag in the old database "
                        "(comma-separated = must have all); run again per category")
    p.add_argument("--dry-run", action="store_true", help="show what would be imported")
