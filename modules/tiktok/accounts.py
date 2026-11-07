"""Account actions: add, tag, untag, list, info, check, remove, block,
unblock, flagged, unflag, timeout."""

import sys

from mogul_core import store

from . import naming
from .catalog import clean_name, is_numeric_id, split_tags
from .common import pause, setup, write_report
from .ytdlp import Ytdlp


def _need(acc, name):
    if not acc:
        sys.exit(f"NOT FOUND: {name} (check archiver.py tiktok list)")
    return acc


# ─── add ────────────────────────────────────────────────────────────────

def add(args, config):
    s, cat = setup(config)
    names = list(args.names or [])
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if line:
                    names.append(line)
    if not names:
        sys.exit("Give one or more @handles or IDs, or --file with one per line.")
    tags = split_tags(args.category)
    if not tags:
        sys.exit("--category is required (e.g. --category comedy). "
                 "Extra comma-separated tags are added too.")
    yt = Ytdlp(s, use_cookies=not args.no_cookies)
    results = {"added": [], "exists": [], "blocked": [], "errors": []}

    for i, name in enumerate(names, 1):
        prefix = f"[{i}/{len(names)}] " if len(names) > 1 else ""
        name = name.strip()
        existing = cat.find(name)
        if existing:
            print(f"{prefix}EXISTS: {name} is already in the catalog as {existing.label()}")
            results["exists"].append(name)
            continue
        blocked = cat.is_blocked(name)
        if blocked and not args.force:
            print(f"{prefix}BLOCKED: {name} ({blocked.get('reason') or 'no reason given'}). "
                  "Use --force to add anyway.")
            results["blocked"].append(name)
            continue

        print(f"{prefix}Looking up {name}...", flush=True)
        info = yt.peek(name, s.timeout)
        if info["error"]:
            print(f"  ERROR: {info['error']}")
            results["errors"].append({"name": name, "error": info["error"]})
            continue

        uid = info["uploader_id"]
        if not uid:
            print("  ERROR: account has no videos, so TikTok didn't say its ID. "
                  "Add it by numeric ID instead.")
            results["errors"].append({"name": name, "error": "empty account, no ID"})
            continue
        existing = cat.by_uid(uid)
        if existing:
            print(f"  EXISTS: that's {existing.label()}, already in the catalog")
            results["exists"].append(name)
            continue
        if cat.is_blocked(uid) and not args.force:
            print(f"  BLOCKED: {uid} is on the block list. Use --force to add anyway.")
            results["blocked"].append(name)
            continue

        count = info["video_count"]
        if count and count > s.warn_over and not (args.force or args.yes):
            answer = input(f"  {name} has {count:,} videos (more than {s.warn_over:,}). "
                           "Add anyway? [y/N] ").strip().lower()
            if answer != "y":
                print("  skipped")
                continue

        when = store.now()
        handle = info["handle"] or (None if is_numeric_id(name) else name.lstrip("@"))
        acc = cat.create(uid, handle or uid, when,
                         display_name=info["display_name"],
                         channel_url=info["channel_url"],
                         category=tags[0], tags=tags,
                         status="empty" if info["empty"] else "active",
                         notes=args.notes)
        if count is not None:
            acc.state["listed_count"] = count
        acc.save()
        print(f"  ADDED: {acc.label()}  category: {tags[0]}"
              + (f"  tags: {', '.join(tags)}" if len(tags) > 1 else "")
              + (f"  videos: {count:,}" if count else "")
              + ("  (no videos posted yet)" if info["empty"] else ""))
        print(f"         folder: {naming.account_folder(s, acc)}")
        results["added"].append({"uploader_id": uid, "handle": acc.handle})
        if i < len(names):
            pause(s.rate_min, s.rate_max)

    if len(names) > 1:
        print(f"\nAdded {len(results['added'])}, already there {len(results['exists'])}, "
              f"blocked {len(results['blocked'])}, errors {len(results['errors'])}")
    if results["errors"] or len(names) > 1:
        write_report(s, "add", results)


# ─── tags ───────────────────────────────────────────────────────────────

def tag(args, config, remove=False):
    s, cat = setup(config)
    acc = _need(cat.find(args.name), args.name)
    tags = split_tags(args.tags)
    if not tags:
        sys.exit("Give the tag(s), e.g. --tags yeti,slop")
    current = list(acc.tags)
    for t in tags:
        if remove:
            if t == acc.category:
                print(f"'{t}' is the primary category; change it with --primary on tag instead.")
            elif t in current:
                current.remove(t)
        elif t not in current:
            current.append(t)
    moved_drive = False
    if not remove and args.primary:
        before = s.library_for(acc.category)
        acc.info["category"] = tags[0]
        moved_drive = s.library_for(acc.category) != before
    if acc.category not in current:
        current.insert(0, acc.category)
    acc.info["tags"] = sorted(set(current), key=lambda t: (t != acc.category, t))
    acc.save()
    print(f"{acc.label()}\n  primary : {acc.category}\n  tags    : {', '.join(acc.tags)}")
    if moved_drive or ("{category}" in s.folder_template and getattr(args, "primary", False)):
        print(f"  Its folder is now {naming.account_folder(s, acc)}\n"
              f"  Run: archiver.py tiktok move --name {acc.uid}")


# ─── list / info ────────────────────────────────────────────────────────

def list_accounts(args, config):
    s, cat = setup(config)
    statuses = None if args.status == "all" else tuple(split_tags(args.status))
    accs = cat.select(category=args.category, statuses=statuses)
    if args.dormant:
        accs = [a for a in accs if a.state.get("stale_count", 0) >= s.dormant_threshold]
    if args.flagged:
        accs = [a for a in accs if a.flagged]
    if not accs:
        print("No accounts match.")
        return
    print(f"{'Handle':<28} {'ID':<20} {'Category':<12} {'Listed':>7} {'Files':>6}  Status")
    print("─" * 92)
    for a in accs:
        flags = [a.status]
        if a.flagged:
            flags.append("FLAGGED")
        stale = a.state.get("stale_count", 0)
        if stale >= s.dormant_threshold:
            flags.append(f"dormant x{stale}")
        listed = sum(1 for v in a.videos.values() if v.get("listing"))
        files = sum(1 for v in a.videos.values() if v.get("file"))
        print(f"@{a.handle[:27]:<27} {a.uid:<20} {a.category[:12]:<12} {listed:>7} {files:>6}  "
              + ", ".join(flags))
    print(f"\n{len(accs)} account(s).")


def info(args, config):
    s, cat = setup(config)
    acc = _need(cat.find(args.name), args.name)
    i, st, vids = acc.info, acc.state, acc.videos
    listed = sum(1 for v in vids.values() if v.get("listing"))
    gone = sum(1 for v in vids.values() if (v.get("listing") or {}).get("gone"))
    files = [v for v in vids.values() if v.get("file")]
    skips = [v for v in vids.values() if (v.get("status") or {}).get("skip")]
    quarantined = sum(1 for v in files if v["file"].get("location") == "quarantine")
    repaired = sum(1 for v in files if (v.get("status") or {}).get("repaired"))
    unchecked = sum(1 for v in files if not (v.get("status") or {}).get("check"))
    print(acc.label())
    print(f"  display name : {i.get('display_name') or '—'}")
    print(f"  status       : {acc.status}" + ("  FLAGGED" if acc.flagged else ""))
    print(f"  category     : {acc.category}   tags: {', '.join(acc.tags) or '—'}")
    past = [h["handle"] for h in i.get("handles", []) if h["handle"].lower() != acc.handle.lower()]
    if past:
        print(f"  past handles : {', '.join('@' + p for p in past)}")
    print(f"  added        : {i.get('added')}")
    if i.get("notes"):
        print(f"  notes        : {i['notes']}")
    print(f"  folder       : {naming.account_folder(s, acc)}")
    print(f"  last checked : {st.get('last_checked') or '—'}")
    print(f"  last updated : {st.get('last_updated') or '—'}"
          + (f"  (took {st['last_duration']:.0f}s)" if st.get("last_duration") else ""))
    print(f"  last download: {st.get('last_downloaded') or '—'}")
    if st.get("timeout_override"):
        print(f"  timeout      : {st['timeout_override']}s (override)")
    if st.get("error_count"):
        print(f"  errors       : {st['error_count']} in a row, last: {st.get('error_last')}")
    print(f"  videos listed: {listed:,}" + (f"  ({gone:,} no longer on TikTok)" if gone else ""))
    print(f"  files        : {len(files):,}"
          + (f"  ({repaired} repaired, {quarantined} quarantined, {unchecked} not validated)"
             if repaired or quarantined or unchecked else ""))
    print(f"  skipped      : {len(skips):,}")


# ─── check ──────────────────────────────────────────────────────────────

def check(args, config):
    """Peek each account (newest video only): still alive? handle changed?"""
    s, cat = setup(config)
    accs = cat.select(name=args.name, category=args.category)
    if not accs:
        print("No accounts to check.")
        return
    yt = Ytdlp(s, use_cookies=not args.no_cookies)
    report = {"ok": [], "handle_changes": [], "errors": [], "skipped_flagged": []}
    print(f"\nChecking {len(accs)} account(s)...\n")
    for i, acc in enumerate(accs, 1):
        print(f"[{i}/{len(accs)}] {acc.label()}", end="", flush=True)
        if acc.flagged and not args.force:
            print(" — SKIPPED (flagged; unflag it or use --force)")
            report["skipped_flagged"].append(acc.uid)
            continue
        when = store.now()
        info = yt.peek(acc.uid, s.timeout)          # by ID: works after a handle change
        if info["error"] and acc.handle != acc.uid:
            info = yt.peek(acc.handle, s.timeout)   # some accounts only answer by handle
        acc.state["last_checked"] = when
        if info["error"]:
            print(f" — ERROR: {info['error']}")
            if acc.record_error(info["error"], s.error_threshold, when):
                print(f"  ⚑ FLAGGED after {s.error_threshold} errors in a row")
            report["errors"].append({"uploader_id": acc.uid, "handle": acc.handle,
                                     "error": info["error"]})
        else:
            note = ""
            old = acc.set_handle(info["handle"], when)
            if old:
                note = f" (handle: @{old} → @{acc.handle})"
                report["handle_changes"].append({"uploader_id": acc.uid, "old": old,
                                                 "new": acc.handle})
            for key in ("display_name", "channel_url"):
                if info.get(key):
                    acc.info[key] = info[key]
            if info["video_count"] is not None:
                acc.state["listed_count"] = info["video_count"]
            acc.clear_errors()
            print(" — OK" + note)
            report["ok"].append(acc.uid)
        acc.save()
        if i < len(accs):
            pause(s.rate_min, s.rate_max)
    print(f"\n{'─' * 50}\nOK: {len(report['ok'])}   handle changes: {len(report['handle_changes'])}"
          f"   errors: {len(report['errors'])}")
    write_report(s, "check", report)


# ─── remove / block ─────────────────────────────────────────────────────

def remove(args, config):
    s, cat = setup(config)
    acc = _need(cat.find(args.name), args.name)
    if args.undo:
        acc.info["status"] = "active"
        acc.save()
        print(f"RESTORED: {acc.label()} is active again")
        return
    acc.info["status"] = "removed"
    acc.info["removed"] = store.now()
    acc.save()
    print(f"REMOVED: {acc.label()}. Its files and catalog entry are kept; "
          "update and download skip it. Undo with: remove --undo")


def block(args, config):
    s, cat = setup(config)
    data = cat.blocked()
    if cat.is_blocked(args.name):
        print(f"ALREADY BLOCKED: {args.name}")
        return
    acc = cat.find(args.name)
    entry = {"handle": acc.handle if acc else (None if is_numeric_id(args.name) else clean_name(args.name)),
             "uploader_id": acc.uid if acc else (clean_name(args.name) if is_numeric_id(args.name) else None),
             "reason": args.reason, "blocked": store.now()}
    data["blocked"].append(entry)
    cat.save_blocked(data)
    print(f"BLOCKED: {args.name}" + (f" ({args.reason})" if args.reason else ""))
    if acc and acc.status != "removed":
        print(f"  It's still in the catalog as {acc.label()}; use remove to stop archiving it.")


def unblock(args, config):
    s, cat = setup(config)
    data = cat.blocked()
    key = clean_name(args.name)
    before = len(data["blocked"])
    data["blocked"] = [b for b in data["blocked"]
                       if key not in (clean_name(b.get("handle") or ""), b.get("uploader_id"))]
    if len(data["blocked"]) == before:
        print(f"NOT BLOCKED: {args.name}")
        return
    cat.save_blocked(data)
    print(f"UNBLOCKED: {args.name}")


# ─── flags ──────────────────────────────────────────────────────────────

def flagged(args, config):
    s, cat = setup(config)
    accs = [a for a in cat.select(statuses=None) if a.flagged]
    if not accs:
        print("No flagged accounts.")
        return
    print(f"{'Handle':<28} {'ID':<20} {'Errors':>6}  Last error")
    print("─" * 90)
    for a in accs:
        print(f"@{a.handle[:27]:<27} {a.uid:<20} {a.state.get('error_count', 0):>6}  "
              f"{a.state.get('error_last') or '—'}")
    print(f"\n{len(accs)} flagged. Clear with: unflag --name @handle   or   unflag --all")


def unflag(args, config):
    s, cat = setup(config)
    if args.all:
        accs = [a for a in cat.select(statuses=None) if a.flagged]
    elif args.name:
        accs = [_need(cat.find(args.name), args.name)]
    else:
        sys.exit("unflag needs --name @handle or --all")
    if not accs:
        print("No flagged accounts.")
        return
    for a in accs:
        was = a.state.get("error_last")
        a.clear_errors()
        a.save()
        print(f"UNFLAGGED: {a.label()}" + (f"  (was: {was})" if was else ""))


def timeout(args, config):
    s, cat = setup(config)
    if args.list:
        accs = [a for a in cat.select(statuses=None)
                if a.state.get("timeout_override") or a.state.get("last_duration")]
        accs.sort(key=lambda a: -(a.state.get("timeout_override")
                                  or (a.state.get("last_duration") or 0) * 3))
        if not accs:
            print("No overrides or recorded fetch times yet.")
            return
        print(f"{'Handle':<28} {'ID':<20} {'Override':>9}  Last listing took")
        print("─" * 80)
        for a in accs:
            o = a.state.get("timeout_override")
            d = a.state.get("last_duration")
            print(f"@{a.handle[:27]:<27} {a.uid:<20} {(str(o) + 's') if o else '—':>9}  "
                  f"{f'{d:.0f}s' if d else '—'}")
        return
    if not args.name:
        sys.exit("timeout needs --name @handle (or --list)")
    acc = _need(cat.find(args.name), args.name)
    current = acc.state.get("timeout_override") or s.timeout
    if args.clear:
        acc.state.pop("timeout_override", None)
        acc.save()
        print(f"CLEARED: {acc.label()} uses the normal timeout ({s.timeout}s) again")
        return
    if args.set is not None:
        new = args.set
    elif args.add is not None:
        new = current + args.add
    else:
        sys.exit("Give --add SECONDS, --set SECONDS or --clear")
    acc.state["timeout_override"] = new
    acc.save()
    print(f"{acc.label()}: timeout {current}s → {new}s")


# ─── arguments ──────────────────────────────────────────────────────────

def add_arguments(action, p):
    if action == "add":
        p.add_argument("names", nargs="*", help="@handles or numeric IDs")
        p.add_argument("--category", help="primary category; extra comma-separated tags are "
                                          "added too (e.g. aigen,yeti)")
        p.add_argument("--file", help="text file with one @handle or ID per line (# = comment)")
        p.add_argument("--notes", help="a note to keep with the account")
        p.add_argument("--force", action="store_true",
                       help="add even if blocked, and don't ask about big accounts")
        p.add_argument("--yes", action="store_true", help="don't ask about big accounts")
        p.add_argument("--no-cookies", action="store_true", help="don't use cookies.txt")
    elif action in ("tag", "untag"):
        p.add_argument("--name", required=True, help="@handle or numeric ID")
        p.add_argument("--tags", required=True, help="tag(s), comma-separated")
        if action == "tag":
            p.add_argument("--primary", action="store_true",
                           help="also make the first tag the primary category")
    elif action == "list":
        p.add_argument("--category", help="only accounts with this tag (comma-separated = all of them)")
        p.add_argument("--status", default="active,empty",
                       help="active, empty, removed, comma-separated, or 'all' (default: active,empty)")
        p.add_argument("--dormant", action="store_true", help="only accounts with nothing new lately")
        p.add_argument("--flagged", action="store_true", help="only flagged accounts")
    elif action == "info":
        p.add_argument("name", help="@handle or numeric ID")
    elif action == "check":
        p.add_argument("--name", help="one account")
        p.add_argument("--category", help="only accounts with this tag")
        p.add_argument("--force", action="store_true", help="check flagged accounts too")
        p.add_argument("--no-cookies", action="store_true", help="don't use cookies.txt")
    elif action == "remove":
        p.add_argument("name", help="@handle or numeric ID")
        p.add_argument("--undo", action="store_true", help="make a removed account active again")
    elif action == "block":
        p.add_argument("name", help="@handle or numeric ID")
        p.add_argument("--reason", help="why (shown if someone tries to add it)")
    elif action == "unblock":
        p.add_argument("name", help="@handle or numeric ID")
    elif action == "unflag":
        p.add_argument("--name", help="one account")
        p.add_argument("--all", action="store_true", help="every flagged account")
    elif action == "timeout":
        p.add_argument("--name", help="@handle or numeric ID")
        p.add_argument("--add", type=int, help="add this many seconds to its timeout")
        p.add_argument("--set", type=int, help="set its timeout to exactly this many seconds")
        p.add_argument("--clear", action="store_true", help="go back to the normal timeout")
        p.add_argument("--list", action="store_true", help="show every override and fetch time")


def run(action, args, config):
    if action == "add":
        return add(args, config)
    if action == "tag":
        return tag(args, config)
    if action == "untag":
        return tag(args, config, remove=True)
    if action == "list":
        return list_accounts(args, config)
    if action == "info":
        return info(args, config)
    if action == "check":
        return check(args, config)
    if action == "remove":
        return remove(args, config)
    if action == "block":
        return block(args, config)
    if action == "unblock":
        return unblock(args, config)
    if action == "flagged":
        return flagged(args, config)
    if action == "unflag":
        return unflag(args, config)
    if action == "timeout":
        return timeout(args, config)
