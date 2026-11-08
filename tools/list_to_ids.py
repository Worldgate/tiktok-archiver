#!/usr/bin/env python3
"""
list_to_ids.py - turn the old scripts' account list into ID files.

Standalone helper (not part of mogul.py). Reads the output of the old
"accounts.py list" (the "[ aigen ]" sections with one account per line)
and writes, into an output folder:

  <category>.txt   one account ID per line, handle as a comment:
                       7535456377386288150  # @_rofls.ai
                   ready for:
                       mogul.py tiktok add --file aigen.txt --category aigen
  blocked.txt      accounts the old list marked [blocked], kept apart so
                   they don't get added by accident (add, then
                   "mogul.py tiktok block ID" if you want them archived
                   as blocked)
  accounts.csv     everything in one table: id,category,status,handle,videos

IDs, not handles, because handles change and IDs don't.

Usage:
  python tools/list_to_ids.py old_list.txt
  python tools/list_to_ids.py old_list.txt --out ids/
"""

import argparse
import csv
import os
import re
import sys

SECTION = re.compile(r"^\s*\[\s*([^\]]+?)\s*\]\s*$")
ACCOUNT = re.compile(
    r"^\s*\[(?P<status>\w+)\]\s+@(?P<handle>\S+)\s+(?P<videos>[\d,]+|\?)\s+videos\s+(?P<id>\d+)"
)


def parse(path):
    rows = []
    category = None
    # the old list sometimes comes through with odd characters (the flag mark)
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = ACCOUNT.match(line)
            if m:
                rows.append({
                    "id": m["id"],
                    "category": category or "general",
                    "status": m["status"].lower(),
                    "handle": m["handle"],
                    "videos": "" if m["videos"] == "?" else m["videos"].replace(",", ""),
                })
                continue
            m = SECTION.match(line)
            if m:
                category = m.group(1).strip().lower()
    return rows


def main():
    p = argparse.ArgumentParser(description="Old account list -> ID files per category")
    p.add_argument("list", help="the saved output of the old accounts list")
    p.add_argument("--out", default="ids", help="folder to write into (default: ids)")
    args = p.parse_args()

    rows = parse(args.list)
    if not rows:
        sys.exit("No accounts found in that file. Is it the old list output?")
    os.makedirs(args.out, exist_ok=True)

    seen, dupes = set(), 0
    by_cat, blocked = {}, []
    for r in rows:
        if r["id"] in seen:
            dupes += 1
            continue
        seen.add(r["id"])
        if r["status"] == "blocked":
            blocked.append(r)
        else:
            by_cat.setdefault(r["category"], []).append(r)

    for cat, items in sorted(by_cat.items()):
        with open(os.path.join(args.out, f"{cat}.txt"), "w", encoding="utf-8") as f:
            f.write(f"# {cat}: {len(items)} account(s)\n")
            f.write(f"# mogul.py tiktok add --file {cat}.txt --category {cat}\n")
            for r in items:
                f.write(f"{r['id']}  # @{r['handle']}"
                        + (" (empty)" if r["status"] == "empty" else "") + "\n")
    if blocked:
        with open(os.path.join(args.out, "blocked.txt"), "w", encoding="utf-8") as f:
            f.write("# Blocked in the old scripts. Not meant for add.\n")
            for r in blocked:
                f.write(f"{r['id']}  # @{r['handle']} ({r['category']})\n")
    with open(os.path.join(args.out, "accounts.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "category", "status", "handle", "videos"])
        w.writeheader()
        w.writerows(rows)

    print(f"{len(seen)} account(s) written to {args.out}/")
    for cat, items in sorted(by_cat.items(), key=lambda kv: -len(kv[1])):
        print(f"  {cat + '.txt':<20} {len(items):>4}")
    if blocked:
        print(f"  {'blocked.txt':<20} {len(blocked):>4}")
    print(f"  {'accounts.csv':<20} {len(rows):>4}  (everything)")
    if dupes:
        print(f"  ({dupes} repeated line(s) skipped)")


if __name__ == "__main__":
    main()
