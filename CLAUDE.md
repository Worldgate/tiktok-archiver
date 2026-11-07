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
videos already on disk) on the new JSON catalog. Started fresh: no
migration from the old SQLite databases (decided 2026-11-07).

## Keeping it mergeable (the main rule)

- **CLI shape:** `archiver.py tiktok <action> [options]`, exactly like
  `mogul.py <media type> <action>`. `archiver.py` is a copy of `mogul.py`
  with only `tiktok` in `MEDIA_TYPES`.
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

Merging later = copy `modules/tiktok/` into MOGUL, add
`"tiktok": "modules.tiktok"` to `MEDIA_TYPES` in `mogul.py`, paste the
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
archiver.py            CLI entry point (copy of mogul.py)
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
  update.py            video lists into the catalog
  download.py          download + skipped
  scan.py              catalog files already on disk
  validate.py          validate + silent
```

## Data storage

- **JSON is the source of truth**, one file per account:
  `mogul_json/tiktok/<uploader_id>.json`. Saved after every
  account (update) or every video (download, scan, validate), written
  safely (temp file + rename) by `mogul_core/store.py`.
- **No paths in the JSON.** A file's location = `library` (or
  `quarantine` if `file.location` says so) + `folder_template` +
  `file.filename`.
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
      "listing": {"title": "...", "timestamp": 1730172800, "url": "...",
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
- **silent**: marks videos `check.result = silent` and moves them back
  from quarantine. Replaces `mark_valid.py` and `validate.sh`.

## Testing without TikTok

There's no network to TikTok in Claude's sandbox. Test with a fake
`yt-dlp` script on PATH that prints canned listings and copies sample
files made with ffmpeg (video+audio, video only, audio only). All actions
were run end to end this way on 2026-11-07; nothing has run against real
TikTok yet.

## Not built yet (from the old scripts)

- **lostmedia**: identify unknown video files via TikTok's oEmbed API
  (batched, cached), then hand matched files to import.
- **import**: move `<uid>_<handle>/` folders from an incoming folder into
  the library, adding the accounts. (scan already reads those folder names.)
- **sort**: the old `sort_by_category.py` is now just a `folder_template`
  change (`{category}/{uid19}`) plus a mover to put files where the new
  template says. scan reports them as MISPLACED until then.
- `--move` for scan to fix MISPLACED files.
- **export**: accounts to CSV (JSON is already the backup).
