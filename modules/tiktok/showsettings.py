"""settings: show which settings files were loaded and where everything goes.

For checking a setup: which mogul.toml / mogul.local.toml were read, and
the folder each category's accounts end up in.
"""

import os

from .common import setup


def run(args, config):
    s, cat = setup(config)

    def where(path):
        return f"{path}" + ("" if os.path.exists(path) else "   (doesn't exist yet)")

    print("Settings files")
    print(f"  mogul.toml        : {config.path}")
    print(f"  mogul.local.toml  : {config.local_path or 'NOT FOUND (expected ' + os.path.join(config.base, 'mogul.local.toml') + ')'}")
    raw = config.section("tiktok")
    print("\nFolders")
    print(f"  catalog           : {where(s.catalog_dir)}")
    print(f"  userdata          : {where(s.userdata_dir)}")
    print(f"  cookies           : {s.cookies_path}"
          + ("   (found, will be used)" if os.path.isfile(s.cookies_path) else "   (none)"))
    print(f"  quarantine        : {where(s.quarantine_dir)}")
    print(f"  library (default) : {where(s.library_dir)}")

    print("\n[tiktok.drives]")
    if s.drives:
        for name, path in sorted(s.drives.items()):
            print(f"  {name:<17} : {where(path)}")
    else:
        print("  (none set: every category uses the default library)")
        from .settings import DEFAULTS
        stray = [k for k, v in raw.items() if isinstance(v, str) and k not in DEFAULTS]
        if stray:
            print(f"  Note: [tiktok] has settings it doesn't know: {', '.join(stray)}. "
                  "Did they belong under [tiktok.drives]?")
    if isinstance(raw.get("drives"), dict):
        odd = [k for k, v in raw["drives"].items() if not isinstance(v, str)]
        if odd:
            print(f"  Note: these under [tiktok.drives] aren't paths: {', '.join(odd)}")

    print(f"\nfolder_template     : {s.folder_template}")
    print(f"blocked_folder      : {s.data.get('blocked_folder')}")

    cats = {}
    for acc in cat.all():
        cats.setdefault(acc.category, 0)
        cats[acc.category] += 1
    wanted = [args.category.lower()] if args.category else sorted(set(cats) | set(s.drives))
    if wanted:
        print("\nWhere each category's accounts go")
        for c in wanted:
            n = cats.get(c, 0)
            print(f"  {c:<17} : {s.library_for(c)}"
                  + (f"   ({n} account(s))" if n else "")
                  + ("" if c in s.drives else "   [default library]"))
    if args.name:
        acc = cat.find(args.name)
        if acc:
            from . import naming
            print(f"\n@{acc.handle} ({acc.uid}), category {acc.category}"
                  + (", blocked" if acc.blocked else "")
                  + f"\n  folder: {naming.account_folder(s, acc)}")
        else:
            print(f"\n{args.name}: not in the catalog")


def add_arguments(p):
    p.add_argument("--category", help="show just this category")
    p.add_argument("--name", help="also show one account's folder")
