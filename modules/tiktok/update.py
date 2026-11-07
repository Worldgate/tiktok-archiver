"""update: fetch each account's video list from TikTok into the catalog.

Nothing is downloaded here. Each video TikTok lists gets an entry with its
title and upload date; download then fetches the ones without a file.

Videos are never removed from the catalog. When a video stops showing up
in an account's listing it gets "not_listed_since" (deleted, made private,
or TikTok just didn't return it that time). If it shows up again, that
mark is cleared.
"""

import gzip
import json
import os
import time

from mogul_core import store

from .common import add_filters, days_ago, elapsed, pause, setup, write_report
from .ytdlp import Ytdlp, tiktok_url

LISTING_KEYS = ("title", "timestamp", "duration", "view_count", "like_count",
                "comment_count", "repost_count")


def queue_path(s):
    return os.path.join(s.state_dir, "update-queue.txt")


def write_queue(s, uids):
    os.makedirs(s.state_dir, exist_ok=True)
    with open(queue_path(s), "w", encoding="utf-8") as f:
        f.write("".join(u + "\n" for u in uids))


def read_queue(s):
    try:
        with open(queue_path(s), encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except OSError:
        return None


def done_in_queue(s, uid):
    q = read_queue(s)
    if q is None:
        return
    q = [u for u in q if u != uid]
    if q:
        write_queue(s, q)
    else:
        try:
            os.remove(queue_path(s))
        except OSError:
            pass


def save_dump(s, uid, dump):
    """Keep the latest raw listing (working state, not the catalog)."""
    folder = os.path.join(s.state_dir, "dumps")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{uid}.json.gz")
    tmp = path + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(dump, f, ensure_ascii=False)
    os.replace(tmp, path)


def merge_listing(acc, entries, when, complete):
    """Add/refresh listing info for every entry. Returns number of new videos.
    complete=True means this listing should hold every video, so ones
    missing from it get not_listed_since."""
    new = 0
    seen = set()
    for e in entries:
        vid = str(e.get("id") or "")
        if not vid.isdigit():
            continue
        seen.add(vid)
        v = acc.video(vid)
        listing = v.setdefault("listing", {})
        if not listing.get("first_seen"):
            listing["first_seen"] = when
            if not v.get("file"):
                new += 1
        title = e.get("title") or e.get("description")
        if title:
            listing["title"] = title
        for key in LISTING_KEYS[1:]:
            if e.get(key) is not None:
                listing[key] = e[key]
        if e.get("url"):
            listing["url"] = e["url"]
        listing["last_seen"] = when
        listing.pop("not_listed_since", None)
    if complete and seen:
        for vid, v in acc.videos.items():
            listing = v.get("listing")
            if listing and vid not in seen and not listing.get("not_listed_since"):
                listing["not_listed_since"] = when
    return new


def effective_timeout(s, acc, default):
    override = acc.state.get("timeout_override")
    if override:
        return override, f"{override}s override"
    last = acc.state.get("last_duration")
    if last and last * 3 > default:
        return int(last * 3), f"{int(last * 3)}s, last took {last:.0f}s"
    return default, None


def run(args, config):
    s, cat = setup(config)
    default_timeout = args.timeout or s.timeout

    if args.resume:
        q = read_queue(s)
        if not q:
            print("Nothing to resume (no unfinished update run).")
            return
        accs = cat.select(uids=q)
        print(f"Resuming: {len(accs)} account(s) left from the last run.")
    else:
        accs = cat.select(name=args.name, category=args.category)
        if args.new:
            accs = [a for a in accs if not a.state.get("last_updated")]
        if args.last is not None:
            def stale(a):
                d = days_ago(a.state.get("last_updated"))
                return d is None or d >= args.last
            accs = [a for a in accs if stale(a)]
    if not accs:
        print("No accounts to update.")
        return

    yt = Ytdlp(s, use_cookies=not args.no_cookies)
    if not args.dry_run and not args.resume:
        write_queue(s, [a.uid for a in accs])

    report = {"ok": [], "dormant": [], "empty": [], "errors": [], "skipped_flagged": [],
              "handle_changes": []}
    total_new = 0
    start = time.monotonic()
    width = len(str(len(accs)))
    print(f"\nUpdating {len(accs)} account(s)...\n")

    for i, acc in enumerate(accs, 1):
        print(f"{elapsed(start)} [{i:>{width}}/{len(accs)}] @{acc.handle} ({acc.category})",
              end="", flush=True)

        if acc.flagged and not args.force:
            print(" — SKIPPED (flagged; see archiver.py tiktok flagged)")
            report["skipped_flagged"].append(acc.uid)
            done_in_queue(s, acc.uid)
            continue
        if args.dry_run:
            print(" — DRY RUN")
            continue

        when = store.now()
        known = {vid for vid, v in acc.videos.items() if v.get("listing")}

        # Dormant check: if the newest few videos are all known, skip the
        # full listing (slow on big accounts).
        if known and not args.full:
            peek = yt.peek(acc.uid, default_timeout, count=s.dormant_peek)
            ids = [str(e.get("id")) for e in peek["entries"] if e.get("id")]
            if not peek["error"] and ids and all(v in known for v in ids):
                acc.state["stale_count"] = acc.state.get("stale_count", 0) + 1
                acc.state["last_checked"] = when
                old = acc.set_handle(peek["handle"], when)
                acc.save()
                print(f" — nothing new (newest {len(ids)} known, streak "
                      f"{acc.state['stale_count']})"
                      + (f" (handle: @{old} → @{acc.handle})" if old else ""))
                report["dormant"].append(acc.uid)
                done_in_queue(s, acc.uid)
                if i < len(accs):
                    pause(s.rate_min, s.rate_max)
                continue

        timeout, note = effective_timeout(s, acc, default_timeout)
        if note:
            print(f" [timeout {note}]", end="", flush=True)

        urls = [acc.info.get("channel_url") or tiktok_url(acc.uid)]
        large = len(known) >= s.large_channel or (acc.state.get("listed_count") or 0) >= s.large_channel
        if large and acc.handle != acc.uid:
            urls.append(tiktok_url(acc.handle))
            print(" [big account: fetching by ID and by handle]", end="", flush=True)

        results = [yt.listing(u, timeout) for u in urls]
        seconds = sum(r["seconds"] for r in results)
        good = [r for r in results if r["status"] == "ok"]

        if not good and all(r["status"] == "empty" for r in results):
            acc.info["status"] = "empty"
            acc.state["last_updated"] = when
            acc.clear_errors()
            acc.save()
            print(" — EMPTY (no videos posted)")
            report["empty"].append(acc.uid)
            done_in_queue(s, acc.uid)
            continue
        if not good:
            reason = next((r["error"] for r in results if r["error"]), "listing failed")
            print(f" — ERROR: {reason}")
            if acc.record_error(reason, s.error_threshold, when):
                print(f"  ⚑ FLAGGED after {s.error_threshold} errors in a row")
            acc.save()
            report["errors"].append({"uploader_id": acc.uid, "handle": acc.handle,
                                     "error": reason})
            done_in_queue(s, acc.uid)
            continue

        entries, dropped = {}, 0
        for r in good:
            dropped += r["dropped"]
            for e in r["dump"]["entries"]:
                if e.get("id"):
                    entries.setdefault(str(e["id"]), e)
        entries = list(entries.values())
        complete = len(good) == len(results)
        new = merge_listing(acc, entries, when, complete)
        total_new += new

        merged = dict(good[0]["dump"])
        merged["entries"] = entries
        save_dump(s, acc.uid, merged)

        first = entries[0] if entries else {}
        old = acc.set_handle(first.get("uploader"), when)
        if old:
            report["handle_changes"].append({"uploader_id": acc.uid, "old": old,
                                             "new": acc.handle})
        if first.get("channel_url"):
            acc.info.setdefault("channel_url", first["channel_url"])
        if acc.status == "empty" and entries:
            acc.info["status"] = "active"
        acc.state.update(last_updated=when, last_checked=when, last_duration=round(seconds, 1),
                         listed_count=len(entries), stale_count=0)
        acc.clear_errors()
        acc.save()

        msg = f" — OK ({len(entries):,} listed, {new:,} new, {seconds:.0f}s)"
        if not complete:
            msg += " [only one of the two fetches worked]"
        if dropped:
            msg += f" [{dropped} dead/repeated entries dropped]"
        if old:
            msg += f" (handle: @{old} → @{acc.handle})"
        print(msg)
        report["ok"].append({"uploader_id": acc.uid, "listed": len(entries), "new": new})
        done_in_queue(s, acc.uid)
        if i < len(accs):
            pause(s.rate_min, s.rate_max)

    print(f"\n{'─' * 50}")
    print(f"Time         : {elapsed(start)}")
    print(f"Updated      : {len(report['ok'])}  ({total_new:,} new videos to download)")
    print(f"Nothing new  : {len(report['dormant'])}")
    print(f"Empty        : {len(report['empty'])}")
    print(f"Errors       : {len(report['errors'])}")
    if report["skipped_flagged"]:
        print(f"Flagged      : {len(report['skipped_flagged'])} skipped")
    if not args.dry_run:
        write_report(s, "update", report)


def add_arguments(p):
    add_filters(p)
    p.add_argument("--new", action="store_true", help="only accounts never updated")
    p.add_argument("--last", type=float, metavar="DAYS",
                   help="only accounts not updated in this many days")
    p.add_argument("--resume", action="store_true",
                   help="carry on with the accounts an interrupted run didn't get to")
    p.add_argument("--full", action="store_true",
                   help="always fetch the full list (skip the quick 'anything new?' check)")
    p.add_argument("--force", action="store_true", help="update flagged accounts too")
    p.add_argument("--timeout", type=int, help="seconds per listing (default from mogul.toml)")
    p.add_argument("--dry-run", action="store_true", help="list what would be updated")
    p.add_argument("--no-cookies", action="store_true", help="don't use cookies.txt")
