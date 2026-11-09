# tiktok-archiver

A tool I use to mirror TikTok accounts until it breaks. Built in the same
shape as my [MOGUL](https://github.com/Worldgate/mogul) media cataloger so
it can be merged into it later.

```
./mogul.py tiktok <action> [options]
```

Same command as MOGUL itself, so nothing changes when this merges in.

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
mogul.py tiktok update        # get each account's video list
mogul.py tiktok download      # download what's new
mogul.py tiktok validate      # check files, repair missing audio
```

Most actions take `--name @handle` (or ID) for one account,
`--category horror` for one category, and `--dry-run`.
`mogul.py tiktok <action> --help` lists everything.

## Coming from the old scripts

```bash
mogul.py tiktok import-old --from /path/to/tiktok_metadata
```

Brings in your accounts (handles, categories/tags, notes, block list,
timeout overrides) from `accounts.db`, every old listing from `flatdumps/`
and `flatdump_archive/`, and the skip lists and silent/repaired marks from
`validate/`. Nothing in the old folder is changed. Older dumps kept
somewhere else? Add `--dumps /path/to/folder` (as many as you like).
Videos that were deleted long ago stay in the catalog with the dates they
were seen. Running it again only adds what's missing.

Then get the videos in. Put each account's files in
`mogul_incoming/tiktok/<account id>/` on whichever drive they're on now
(see "Drives" below), and per category:

```bash
mogul.py tiktok import-old --from /path/to/tiktok_metadata --category aigen
mogul.py tiktok move --category aigen
mogul.py tiktok scan --category aigen
```

`move` checks every drive's `mogul_incoming/tiktok/` for each account and
moves the files into that account's library folder on the drive set for
its category. Same drive: an instant rename. Another drive: copied,
checked, then the original removed. Folders named with the plain ID or the
zero-padded one both work. Try `--dry-run` first. Files somewhere else
entirely? Add `--from /that/folder`.

Have more than one old setup? Run `import-old` once for each; the second
run adds to the first.

### Just the account list

Have the old scripts' account list saved as text? `tools/list_to_ids.py`
turns it into one file of account IDs per category (IDs, because handles
change), ready for `add`:

```bash
python tools/list_to_ids.py old_list.txt --out ids
python mogul.py tiktok add --file ids/aigen.txt --category aigen --yes
```

## Starting with videos you already have (no old database)

1. Put them in `mogul_incoming/tiktok/<account id>/` on their drive.
2. Add your accounts (a text file with one per line works):
   `mogul.py tiktok add --file accounts.txt --category comedy`
3. `mogul.py tiktok move`, then `mogul.py tiktok scan`.
4. Then the usual `update` → `download` → `validate`.

## Drives

Each category lives under a **base folder** that holds the usual MOGUL
folders:

```
/mnt/STORAGE2/tiktok-archiver/
  mogul_incoming/tiktok/<id>/     drop files here to be moved in
  mogul_library/tiktok/<id>/      the archive
  mogul_blocked/tiktok/<id>/      blocked accounts, to hand-sort
  mogul_quarantine/tiktok/<id>/   files validate couldn't fix
```

Set them in `mogul.local.toml`:

```toml
[tiktok]
base = "/mnt/STORAGE1/tiktok-archiver"      # every category not listed below

[tiktok.drives]
aigen = "/mnt/STORAGE2/tiktok-archiver"
horror = "/mnt/STORAGE2/tiktok-archiver"
```

Keep other `[tiktok]` settings above the `[tiktok.drives]` line: everything
after a header belongs to it. Check it with `mogul.py tiktok settings`.
To move a category to another drive later, change its line and run
`mogul.py tiktok move`. If the old drive is no longer in the settings,
tell move where to look: `move --from /mnt/OLD/tiktok-archiver/mogul_library/tiktok`.
Nothing is ever overwritten.

## Blocking accounts

When an account turns into product ads (or anything you don't want):

```bash
mogul.py tiktok block @someone --reason "selling sweaters now"
```

It goes on the block list, stops being archived, and its folder moves to
`mogul_blocked/tiktok/` on the same drive (instant). Delete whatever you
don't want to keep from there; the next `scan` marks those videos as
discarded, so they're never downloaded again. `unblock` moves what's
left back and starts archiving it again. Accounts the old scripts had
blocked land in `mogul_blocked` when you migrate with `move`.

## Actions

| Action | What it does |
|---|---|
| `add @a @b --category x` | Add accounts (`--category aigen,yeti` adds extra tags; `--file` reads a list) |
| `list` | Accounts with counts (`--category`, `--status`, `--dormant`, `--flagged`) |
| `info @a` | Everything about one account |
| `tag` / `untag --name @a --tags x,y` | Change tags (`tag --primary` changes the main category) |
| `check` | Quick "still alive?" for every account; picks up handle changes |
| `remove @a` | Stop archiving (keeps files and catalog; `--undo` to bring it back) |
| `block @a --reason ...` / `unblock` | Block an account: stop archiving, move its folder to the blocked folder (`--keep-files`) |
| `flagged` / `unflag` | Accounts paused after repeated errors |
| `timeout --name @a --add 60` | Longer timeout for slow accounts (`--set`, `--clear`, `--list`) |
| `update` | Fetch video lists (`--new`, `--last 1`, `--errors`, `--resume`, `--full`) |
| `download` | Download new videos (`--limit 50`) |
| `skipped` | Videos download skipped, by reason (`--retry`, `--reason`, `--all-reasons`) |
| `scan` | Catalog files already in the library (`--forget-missing`) |
| `validate` | Check files, repair audio, quarantine broken ones (`--list`, `--recheck`, `--no-repair`) |
| `silent ID ...` | Mark videos as really silent (`--folder` takes IDs from filenames) |
| `settings` | Show which settings files were read and where each category's files go (`--name`) |
| `move` | Move files in from every drive's incoming folder, or to a new drive after a settings change (`--from`, `--dry-run`) |
| `import-old --from PATH` | Import the old scripts' accounts, listings and skips (`--category`, `--dumps`, `--dry-run`) |

## Where things go

```
mogul_json/tiktok/<id>.json      the catalog: one file per account (back this up)
mogul_userdata/tiktok/           private, tied to you
  cookies.txt                    your browser cookies
  blocked.json                   block list
  reports/                       one report per run
  state/                         latest raw listings (gzipped yt-dlp JSON), update queue
<base>/mogul_library/tiktok/<id>/       videos, named 2025.02.03-7467300438342290734.mp4
<base>/mogul_incoming/tiktok/<id>/      files waiting for move
<base>/mogul_blocked/tiktok/<id>/       blocked accounts
<base>/mogul_quarantine/tiktok/<id>/    files validate couldn't fix
```

None of these go to GitHub. `mogul_userdata/` is for anything specific to
you; the TikTok catalog isn't shared either (nobody wants to mirror all of
it).

Settings work the same way: `mogul.toml` is the public copy with safe
defaults, `mogul.local.toml` is yours (paths, anything private) and never
goes to GitHub, and `mogul.local.toml.example` is the template for it.
Media folders are in `.gitignore` too. See `CLAUDE.md` for how it all works.
