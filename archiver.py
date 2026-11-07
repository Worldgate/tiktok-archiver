#!/usr/bin/env python3
"""
TikTok Archiver - a MOGUL-shaped app

Usage:
  archiver.py <media type> <action> [options]

Examples:
  archiver.py tiktok add @someuser --category comedy
  archiver.py tiktok update
  archiver.py tiktok download --dry-run
  archiver.py tiktok validate
  archiver.py tiktok download --help        options for that action

This file works exactly like MOGUL's mogul.py. The TikTok code lives in
modules/tiktok/, and mogul_core/ is a copy of MOGUL's core, so merging
into MOGUL means copying modules/tiktok/ over and adding "tiktok" to
MEDIA_TYPES in mogul.py.
"""

import argparse
import importlib
import sys

if sys.version_info < (3, 11):
    sys.exit("This needs Python 3.11 or newer (you have "
             f"{sys.version_info.major}.{sys.version_info.minor}).")

from mogul_core import VERSION
from mogul_core.config import Config

MEDIA_TYPES = {
    "tiktok": "modules.tiktok",
}


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        print("\nMedia types:", ", ".join(MEDIA_TYPES))
        return 0
    if argv[0] in ("-V", "--version"):
        print(f"TikTok Archiver (MOGUL core {VERSION})")
        return 0

    media_type = argv[0]
    if media_type not in MEDIA_TYPES:
        sys.exit(f"Unknown media type '{media_type}'. Available: {', '.join(MEDIA_TYPES)}")
    module = importlib.import_module(MEDIA_TYPES[media_type])

    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(f"archiver.py {media_type} <action> [options]\n\nActions:")
        for name, text in module.ACTIONS.items():
            print(f"  {name:<10} {text}")
        return 0

    action = argv[1]
    if action not in module.ACTIONS:
        sys.exit(f"{media_type} has no action '{action}'. Actions: {', '.join(module.ACTIONS)}")

    parser = argparse.ArgumentParser(
        prog=f"archiver.py {media_type} {action}",
        description=module.ACTIONS[action],
    )
    parser.add_argument("--config", help="use this mogul.toml instead of the default one")
    module.add_arguments(action, parser)
    args = parser.parse_args(argv[2:])

    config = Config(args.config)
    return module.run(action, args, config) or 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nStopped. Everything finished so far is saved.")
        sys.exit(130)
