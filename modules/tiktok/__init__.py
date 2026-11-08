"""TikTok module: mirror TikTok accounts.

Same interface as every MOGUL module (ACTIONS, add_arguments, run), so it
can be dropped into MOGUL's modules/ folder as-is.

Usual flow:
  add (once per account) → update → download → validate
Coming from the old scripts:
  import-old → scan → update → download → validate
Starting fresh with videos already on disk:
  add the accounts → scan → update → download → validate
"""

ACTIONS = {
    # accounts
    "add": "Add accounts by @handle or ID (needs --category)",
    "list": "List accounts with video and file counts",
    "info": "Everything about one account",
    "tag": "Add tags to an account",
    "untag": "Remove tags from an account",
    "check": "Quick check that accounts are alive; picks up handle changes",
    "remove": "Stop archiving an account (keeps its files and catalog)",
    "block": "Block an account: stop archiving it, move its folder to the blocked folder",
    "unblock": "Unblock: move what's left back to the library and archive it again",
    "flagged": "List accounts flagged after repeated errors",
    "unflag": "Clear an account's error flag",
    "timeout": "Give a slow account a longer timeout",
    # the main loop
    "update": "Fetch each account's video list from TikTok into the catalog",
    "download": "Download listed videos that don't have a file yet",
    "skipped": "Show videos download skipped, or clear them to retry",
    "scan": "Catalog videos already in the library (moves nothing)",
    "validate": "Check downloaded files; repair missing audio; quarantine broken ones",
    "silent": "Mark videos as really silent and bring them back from quarantine",
    "move": "Move account folders to where the settings say (e.g. another drive)",
    # bringing in the old scripts' data
    "import-old": "Import accounts, old listings and skips from the old tiktok_metadata folder",
}

ACCOUNT_ACTIONS = ("add", "list", "info", "tag", "untag", "check", "remove", "block",
                   "unblock", "flagged", "unflag", "timeout")


def run(action, args, config):
    if action in ACCOUNT_ACTIONS:
        from . import accounts
        return accounts.run(action, args, config)
    if action == "update":
        from . import update
        return update.run(args, config)
    if action == "download":
        from . import download
        return download.run(args, config)
    if action == "skipped":
        from . import download
        return download.skipped(args, config)
    if action == "scan":
        from . import scan
        return scan.run(args, config)
    if action == "validate":
        from . import validate
        return validate.run(args, config)
    if action == "silent":
        from . import validate
        return validate.silent(args, config)
    if action == "import-old":
        from . import legacy
        return legacy.run(args, config)
    if action == "move":
        from . import move
        return move.run(args, config)
    raise SystemExit(f"tiktok has no action '{action}'. Actions: {', '.join(ACTIONS)}")


def add_arguments(action, parser):
    if action in ACCOUNT_ACTIONS:
        from . import accounts
        accounts.add_arguments(action, parser)
    elif action == "update":
        from . import update
        update.add_arguments(parser)
    elif action in ("download", "skipped"):
        from . import download
        download.add_arguments(action, parser)
    elif action == "scan":
        from . import scan
        scan.add_arguments(parser)
    elif action in ("validate", "silent"):
        from . import validate
        validate.add_arguments(action, parser)
    elif action == "import-old":
        from . import legacy
        legacy.add_arguments(parser)
    elif action == "move":
        from . import move
        move.add_arguments(parser)
