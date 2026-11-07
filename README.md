# tiktok-archiver

A tool I use to mirror TikTok accounts until it breaks. Built in the same
shape as my [MOGUL](https://github.com/Worldgate/mogul) media cataloger so
it can be merged into it later.

```
archiver.py tiktok <action> [options]
```

## Setup

Needs Python 3.11+, `ffmpeg`/`ffprobe`, and yt-dlp **with impersonation
support** (TikTok blocks plain requests).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
yt-dlp --list-impersonate-targets     # Chrome-131:Android-14 should be listed, not "unavailable"
```

Machine-specific settings (drive paths) go in `mogul.local.toml`:

```bash
cp mogul.local.toml.example mogul.local.toml
```

### Cookies

Some accounts need you logged in (age-restricted, "login required",
HTTP 403). Export cookies for tiktok.com in Netscape format with a browser
extension (**Get cookies.txt LOCALLY** for Chrome/Edge, **cookies.txt** for
Firefox) and save them as `mogul_userdata/tiktok/cookies.txt` (or set
`cookies` in `mogul.local.toml`). They're used automatically when the file
exists; `--no-cookies` turns them off for a run. Cookies expire: if
accounts that used to work start asking for a login, export them again.

## Everyday use

```bash
archiver.py tiktok update        # get each account's video list
archiver.py tiktok download      # download what's new
archiver.py tiktok validate      # check files, repair missing audio
```

Most actions take `--name @handle` (or ID) for one account,
`--category horror` for one category, and `--dry-run`.
`archiver.py tiktok <action> --help` lists everything.

## Coming from the old scripts

```bash
archiver.py tiktok import-old --from /path/to/tiktok_metadata
```

Brings in your accounts (handles, categories/tags, notes, block list,
timeout overrides) from `accounts.db`, every old listing from `flatdumps/`
and `flatdump_archive/`, and the skip lists and silent/repaired marks from
`validate/`. Nothing in the old folder is changed. Older dumps kept
somewhere else? Add `--dumps /path/to/folder` (as many as you like).
Videos that were deleted long ago stay in the catalog with the dates they
were seen. Running it again only adds what's missing.

Then point `library` at your old `tiktok_cache` in `mogul.local.toml` and
run `archiver.py tiktok scan`.

## Starting with videos you already have (no old database)

1. Point `library` at your existing folders in `mogul.local.toml`
   (the old `tiktok_cache` layout, one zero-padded ID folder per account,
   is the default here).
2. Add your accounts (a text file with one per line works):
   `archiver.py tiktok add --file accounts.txt --category comedy`
3. `archiver.py tiktok scan` catalogs what's already on disk.
4. Then the usual `update` → `download` → `validate`.

## Actions

| Action | What it does |
|---|---|
| `add @a @b --category x` | Add accounts (`--category aigen,yeti` adds extra tags; `--file` reads a list) |
| `list` | Accounts with counts (`--category`, `--status`, `--dormant`, `--flagged`) |
| `info @a` | Everything about one account |
| `tag` / `untag --name @a --tags x,y` | Change tags (`tag --primary` changes the main category) |
| `check` | Quick "still alive?" for every account; picks up handle changes |
| `remove @a` | Stop archiving (keeps files and catalog; `--undo` to bring it back) |
| `block @a --reason ...` / `unblock` | Block list for `add` |
| `flagged` / `unflag` | Accounts paused after repeated errors |
| `timeout --name @a --add 60` | Longer timeout for slow accounts (`--set`, `--clear`, `--list`) |
| `update` | Fetch video lists (`--new`, `--last 7`, `--resume`, `--full`) |
| `download` | Download new videos (`--limit 50`) |
| `skipped` | Videos download skipped, by reason (`--retry`, `--reason`, `--all-reasons`) |
| `scan` | Catalog files already in the library (`--forget-missing`) |
| `validate` | Check files, repair audio, quarantine broken ones (`--list`, `--recheck`, `--no-repair`) |
| `silent ID ...` | Mark videos as really silent (`--folder` takes IDs from filenames) |
| `import-old --from PATH` | Import the old scripts' accounts, listings and skips (`--dumps`, `--dry-run`) |

## Where things go

```
mogul_json/tiktok/<id>.json      the catalog: one file per account (back this up)
mogul_userdata/tiktok/           private, tied to you
  cookies.txt                    your browser cookies
  blocked.json                   block list
  reports/                       one report per run
  state/                         latest raw listings (gzipped yt-dlp JSON), update queue
mogul_library/tiktok/<id>/       videos, named 2025.02.03-7467300438342290734.mp4
mogul_quarantine/tiktok/<id>/    files validate couldn't fix
```

None of these go to GitHub. `mogul_userdata/` is for anything specific to
you; the TikTok catalog isn't shared either (nobody wants to mirror all of
it).

Settings work the same way: `mogul.toml` is the public copy with safe
defaults, `mogul.local.toml` is yours (paths, anything private) and never
goes to GitHub, and `mogul.local.toml.example` is the template for it.
Media folders are in `.gitignore` too. See `CLAUDE.md` for how it all works.
