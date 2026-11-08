# TikTok Archiver

Mirrors TikTok accounts: lists what each account has posted, downloads it,
checks the files and repairs missing audio. Built as a **MOGUL module in
waiting**: same CLI, same core, same rules, so merging into
[MOGUL](https://github.com/Worldgate/mogul) is mostly copying a folder.

## Working with Mavrick

- He doesn't write code. Deliver **complete, drop-in files**, never patches
  or "change line 40" instructions.
- Explain in plain terms what a file does and how to run it.
- He thinks out loud and decides as he goes. When something is undecided,
  pick a sensible default, say what you picked, and keep it easy to change
  (usually a setting in `mogul.toml`).
- Don't build ahead of the current goal. Note future ideas below instead.

## Current goal

The core loop (accounts → update → download → validate, plus scan for
videos already on disk) on the new JSON catalog, plus `import-old` to pull
in the old scripts' accounts.db and years of old flatdumps (decided
2026-11-07, replacing the earlier "start fresh" plan). Next step:
Mavrick runs it against his real old data and real TikTok.

Planned, not built: a SQLite index rebuilt from the JSON (JSON stays the
truth; the DB is a disposable failsafe/speed-up, same rule as MOGUL).

## Keeping it mergeable (the main rule)

- **CLI shape:** `mogul.py tiktok <action> [options]`. `mogul.py` here is
  MOGUL's own `mogul.py` with only `tiktok` in `MEDIA_TYPES` (plus help
  examples). Mavrick wants the final commands to be `./mogul.py tiktok ...`
  from day one (decided 2026-11-07).
- **`mogul_core/` is a copy of MOGUL's core. Don't change it here.** If the
  TikTok module needs something general, put it in the module (or change
  it in MOGUL first and copy it back).
- **All TikTok code lives in `modules/tiktok/`** and uses the same module
  interface as `modules/radio`: `ACTIONS`, `add_arguments(action, parser)`,
  `run(action, args, config)`.
- **Settings live in `[tiktok]` in `mogul.toml`.** Same file name and
  layering as MOGUL (`mogul.local.toml` overrides, gitignored).
- **Folders use MOGUL's names** with a `tiktok` subfolder:
  `mogul_json/tiktok/`, `mogul_library/tiktok/`, `mogul_quarantine/tiktok/`.
- **`mogul_userdata/` holds anything private or user-specific** (decided
  2026-11-07; meant to become a MOGUL-wide convention): `[core] userdata`,
  one subfolder per module. TikTok: `mogul_userdata/tiktok/` holds
  `cookies.txt`, `blocked.json`, `reports/`, `state/`. The `state`,
  `reports`, `cookies` settings default to "" = that folder.
  (`mogul.local.toml` has to stay next to `mogul.toml`: the core looks for
  it there.)
- **Catalog:** `mogul_json/tiktok/<uploader_id>.json`, flat. Not shared
  (Mavrick: nobody wants to mirror all of it), so gitignored. Settings: `mogul.toml` public with safe defaults,
  `mogul.local.toml` private (gitignored), `.example` is the template.

Merging later = copy `modules/tiktok/` into MOGUL (don't copy this
`mogul.py` over MOGUL's), add `"tiktok": "modules.tiktok"` to
`MEDIA_TYPES` in MOGUL's `mogul.py`, paste the
`[tiktok]` section into MOGUL's `mogul.toml`, and copy over `mogul_json/tiktok/`.
Things to check at merge time: MOGUL's `.gitignore` pushes `mogul_json/`,
so add `mogul_json/tiktok/` and `mogul_userdata/` to its `.gitignore`, and `media.py`'s ffprobe helper could move
into MOGUL's core for future video modules.

## Environment

- Python 3.11+ (built-in `tomllib`).
- `ffmpeg`/`ffprobe`, and yt-dlp installed with `yt-dlp[default,curl-cffi]`
  (impersonation is required; plain yt-dlp gets blocked by TikTok).
- Old scripts (pre-rewrite) used `tiktok_cache/` (videos),
  `tiktok_metadata/` (SQLite DBs, flatdumps, cookies), `tiktok_validate/`.
  The default folder and file naming here matches the old video layout,
  so pointing `library` at the old `tiktok_cache` and running `scan` works.

## Code layout

```
mogul.py               CLI entry point (MOGUL's mogul.py, tiktok only)
mogul.toml             settings ([core] shared, [tiktok] module)
mogul_core/            copy of MOGUL's core: config, store, progress, hashing, ...
modules/tiktok/
  __init__.py          ACTIONS + dispatch
  settings.py          [tiktok] settings with defaults, folder paths
  catalog.py           per-account JSON files, lookup by ID/handle, block list
  naming.py            folder/filename templates, video ID from filename
  media.py             ffprobe details + whole-file hashes
  ytdlp.py             every yt-dlp call, error sorting
  common.py            reports, pauses, shared options
  accounts.py          add, list, info, tag, untag, check, remove, block,
                       unblock, flagged, unflag, timeout
  listing.py           merging yt-dlp listings: dates, kept metadata fields
  update.py            video lists into the catalog
  legacy.py            import-old: old accounts.db, flatdumps, skips
  move.py              move account folders to where the settings say
  download.py          download + skipped
  scan.py              catalog files already on disk
  validate.py          validate + silent
```

## Data storage

- **JSON is the source of truth**, one file per account:
  `mogul_json/tiktok/<uploader_id>.json`. Saved after every
  account (update) or every video (download, scan, validate), written
  safely (temp file + rename) by `mogul_core/store.py`.
- **No paths in the JSON.** A file's location = the account's library
  (`[tiktok.drives]` entry for its primary category, else `library`), or
  `quarantine` if `file.location` says so, + `folder_template` +
  `file.filename`. So changing drives/templates needs no catalog edits,
  just `move`.
- **Drives per category** (decided 2026-11-07): `[tiktok.drives]` in
  `mogul.local.toml`, `category = "/path"`, keyed by primary category.
  Mavrick has two old drives (e.g. aigen on drive1, commentary on drive2)
  and plans to move to a third drive later. Quarantine is still one
  folder for all drives (could go per-drive later).
- IDs (account and video) are **strings**: 19 digits is too big for
  JavaScript numbers.
- Videos are never removed from the catalog. Missing from a listing →
  `listing.not_listed_since`; seen again → cleared.
- Raw yt-dlp listings (`--dump-single-json` output, gzipped) are working
  state in `mogul_userdata/tiktok/state/dumps/<uid>.json.gz` (latest only). The old flatdump snapshot archive was dropped:
  the catalog keeps every video ever seen anyway.

### Account file layout

```json
{
  "header": {"schema": "mogul.tiktok.account", "schema_version": 1,
             "media_type": "tiktok", "created": "...", "updated": "...",
             "video_count": 6, "file_count": 4, "mogul_version": "0.1.0"},
  "account": {"uploader_id": "7000000000000000001", "handle": "alpha_new",
              "handles": [{"handle": "alpha", "first_seen": "..."}, ...],
              "display_name": "...", "channel_url": "...",
              "category": "comedy", "tags": ["comedy", "yeti"],
              "status": "active", "notes": null, "added": "..."},
  "state": {"last_checked": "...", "last_updated": "...", "last_downloaded": "...",
            "last_duration": 12.3, "listed_count": 5, "stale_count": 0,
            "error_count": 0, "error_last": "...", "flagged": true,
            "timeout_override": 600},
  "videos": {
    "7400000000000000002": {
      "listing": {"title": "...", "description": "...", "timestamp": 1730172800,
                  "duration": 31, "view_count": 1, "like_count": 1, "comment_count": 1,
                  "repost_count": 1, "save_count": 1, "track": "...", "artists": [],
                  "hashtags": ["yeti"], "url": "...",
                  "first_seen": "...", "last_seen": "...", "not_listed_since": "..."},
      "status": {"downloaded": "...",
                 "check": {"result": "ok|repaired|audio_only|silent|unreadable|no_audio",
                           "date": "...", "error": "..."},
                 "repaired": {"date": "...", "original": {"size": 1, "xxh64": "..."}, "note": "..."},
                 "skip": {"reason": "video removed", "permanent": true, "date": "..."}},
      "file": {"filename": "2024.10.29-7400000000000000002.mp4", "size": 34488,
               "mtime": "...Z", "hashes": {"xxh64": "...", "blake3": "...", "sha256": "..."},
               "container": "...", "duration": 2.0, "has_video": true, "has_audio": true,
               "video_codec": "h264", "width": 1080, "height": 1920, "audio_codec": "aac",
               "kind": "video|audio_only", "location": "library|quarantine", "added": "..."}
    }
  }
}
```

- `status`: `active`, `empty` (no videos posted yet), `removed`.
- Account statuses, tags and handle history replace the old `accounts`,
  `account_categories` tables; `status.skip` replaces `skipped_videos`;
  `status.check`/`repaired` replace the validate DBs and `audio_fixed.jsonl`.

## How the actions work

- **add**: peeks the newest video to get the numeric ID, handle, display
  name. Empty accounts can only be added by numeric ID. Asks before adding
  accounts over `warn_over` videos (`--yes`/`--force` skip the question).
  Checks the block list. First `--category` tag = primary category.
- **check**: one-video peek by ID (falls back to handle). Records handle
  changes, counts errors toward flagging.
- **update**: if the account already has listings, peeks the newest
  `dormant_peek` videos; all known → "nothing new", skip the full listing,
  `stale_count` +1. Otherwise full listing. Accounts with
  `large_channel`+ videos are listed twice (by channel URL/ID and by
  handle) and merged, because TikTok returns different slices of big
  accounts per URL. Timeout per account: override, else 3x last duration,
  else default. Writes `mogul_userdata/tiktok/state/update-queue.txt`; `--resume`
  continues an interrupted run.
- **download**: listed videos with no file and no skip, newest first.
  yt-dlp writes `<id>.<ext>` into the account folder, then it's renamed to
  `filename_template`. Video-level errors → `status.skip` (with
  `permanent` for deleted/private/photo posts); account-level errors
  (rate limit, login, timeout) count toward flagging and stop the account
  once flagged. Audio-only downloads (photo slideshows) become `.m4a`.
  Files with no audio are left unchecked for validate.
- **skipped**: groups skips by reason; `--retry` clears non-permanent ones
  (`--all-reasons` for all, `--reason` to filter).
- **scan**: read-only. Matches files to accounts by numeric folder name
  (also old `<uid>_<handle>` incoming folders) or by video ID already in a
  listing. ADDED / ALREADY / RELINKED / CHANGED / DUPLICATE / MISPLACED /
  UNKNOWN / NO ID, then MISSING (`--forget-missing` clears so download
  refetches).
- **validate**: skips files already checked and unchanged (size + mtime).
  No audio → fetch the `download` format (`download/b[vcodec=h264]/b`),
  `ffmpeg -c copy` its audio into the HQ video, verify, replace in place,
  record the original's hash. Repair failed or unreadable → quarantine
  (moved, never deleted). `--list` shows quarantined files.
- **Listing merges** (listing.py, used by update and import-old): dates
  are compared as real times (old data is UTC `Z`, new is local offset).
  first_seen = earliest listing, last_seen = latest; metadata only from a
  listing at least as new as last_seen, so old dumps never overwrite newer
  info. not_listed_since = first listing after last_seen without it;
  cleared by a newer listing. Kept fields: title, description (dropped if
  same as title), timestamp, duration, view/like/comment/repost/save
  counts, track/artist(s)/album, tags/categories, url, plus hashtags
  parsed from title+description. Thumbnails/CDN links skipped (expire).
- **import-old** `--from <old tiktok_metadata>` `[--dumps PATH ...]`:
  read-only on the old data. accounts.db → accounts (create, or fill in
  missing fields; current handle never replaced, old one added to
  history; tags merged; earliest `added` wins), block list, timeout
  overrides. Dumps: `flatdump_archive/<uid>/YYYY-MM-DD_HH-MM-SS.json.gz`
  (date from name, UTC), `flatdumps/<uid>.json` (date = mtime), and any
  `--dumps` folders (uid from content, date from a stamp in the name or
  mtime), merged oldest first. `validate/<uid>.db`: skipped_videos →
  status.skip, valid_silent → check silent, audio_fixed → status.repaired;
  plus `audio_fixed.jsonl`. Error flags are not carried over. Old status
  `blocked` (old `block` marked the account too) → `removed`.
  `--category` (tags from the old DB, comma = all) / `--name` import
  in chunks; the block list only comes over on an unfiltered run. Safe to
  rerun (tested: second run changes nothing). Dumps for accounts not in
  the DB are reported, not created. Then run scan for the files.
- **move**: for each account, looks for its folder under every library
  root (default + drives + `--from` paths, e.g. a drive removed from the
  settings) with the current folder_template (plus `--old-template`), and
  moves every file into the folder the settings point at now. Same
  filesystem → rename; otherwise copy to `.part`, check size + xxh64,
  rename, delete original. Never overwrites: DUPLICATE (same bytes) /
  CONFLICT (differs) leave the original in place. Removes emptied
  folders. scan reports files in the wrong place as MISPLACED (not
  MISSING). `tag --primary` prints a move hint when the folder changes.
  Tested across two filesystems (/dev/shm vs disk).
- **silent**: marks videos `check.result = silent` and moves them back
  from quarantine. Replaces `mark_valid.py` and `validate.sh`.

## Mavrick's import plan (2026-11-07)

One category at a time: `import-old --category X` → `move --category X
--from /old/big/tiktok_cache` (copies that category's ID folders to its
drive) → `scan --category X` → later update/download/validate. He likes
seeing which videos people delete (drama vs. dropped ads), which is why
all old dumps go in. Idea, not built: a view listing deleted videos
(`not_listed_since`) per account or across all.

Mavrick's old list (2026-11-07): 860 accounts, ~790 of them aigen, plus
small categories (animation, archive, comedy, commentary, construction,
cooking, cosplay, general, horror, maga, seasonal, trucking, voiceactor,
vrchat). Some old-style short account IDs (`29204145`, `8321177`,
`1303797`, `5550571`, 18-digit ones): folders zero-pad to 19, tested.

## Testing without TikTok

There's no network to TikTok in Claude's sandbox. Test with a fake
`yt-dlp` script on PATH that prints canned listings and copies sample
files made with ffmpeg (video+audio, video only, audio only). All actions
were run end to end this way on 2026-11-07; nothing has run against real
TikTok yet.

## Not built yet (from the old scripts)

- **SQLite index** rebuilt from the JSON (failsafe / faster queries).
- **lostmedia**: identify unknown video files via TikTok's oEmbed API
  (batched, cached), then hand matched files to import.
- **import**: move `<uid>_<handle>/` folders from an incoming folder into
  the library, adding the accounts. (scan already reads those folder names.)
- (The old `sort_by_category.py` is covered: change folder_template or
  [tiktok.drives], then `move`.)
- **export**: accounts to CSV (JSON is already the backup).
