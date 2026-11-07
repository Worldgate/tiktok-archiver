"""The TikTok catalog: one JSON file per account.

    mogul_json/tiktok/accounts/<uploader_id>.json
    mogul_json/tiktok/blocked.json

JSON is the source of truth (same rule as MOGUL). Everything about an
account lives in its file: who it is, its run state, and every video
ever seen on it, whether downloaded or not.

IDs (account and video) are always stored as strings: they're 19 digits,
too big for JavaScript numbers.

No file paths are stored. Where a video lives is worked out from
folder_template + filename (see naming.py).
"""

import os
import re

from mogul_core import VERSION, store

SCHEMA = "mogul.tiktok.account"
SCHEMA_VERSION = 1


def clean_name(name):
    """'@Some.User' -> 'some.user', '7399...' -> '7399...'."""
    return name.strip().lstrip("@").lower()


def is_numeric_id(name):
    return re.fullmatch(r"\d+", name.strip().lstrip("@")) is not None


def split_tags(text):
    """'horror, AIGEN' -> ['horror', 'aigen']."""
    if not text:
        return []
    return [t.strip().lower() for t in text.split(",") if t.strip()]


class Account:
    """One account's JSON file."""

    def __init__(self, path, data):
        self.path = path
        self.data = data

    # --- quick access ---
    @property
    def uid(self):
        return self.data["account"]["uploader_id"]

    @property
    def handle(self):
        return self.data["account"].get("handle") or self.uid

    @property
    def info(self):
        return self.data["account"]

    @property
    def state(self):
        return self.data["state"]

    @property
    def videos(self):
        return self.data["videos"]

    @property
    def status(self):
        return self.info.get("status", "active")

    @property
    def category(self):
        return self.info.get("category") or "general"

    @property
    def tags(self):
        return self.info.get("tags", [])

    @property
    def flagged(self):
        return bool(self.state.get("flagged"))

    def label(self):
        return f"@{self.handle} ({self.uid})"

    def names(self):
        """Every name this account answers to: ID, current and past handles."""
        out = {self.uid, clean_name(self.handle)}
        for h in self.info.get("handles", []):
            out.add(clean_name(h["handle"]))
        return out

    def has_tags(self, tags):
        mine = set(self.tags) | {self.category}
        return all(t in mine for t in tags)

    def files(self):
        """(video_id, video) for every video with a file recorded."""
        return [(vid, v) for vid, v in self.videos.items() if v.get("file")]

    # --- changes ---
    def set_handle(self, handle, when):
        """Record a (possibly new) handle. Returns the old one if it changed."""
        if not handle:
            return None
        handle = handle.lstrip("@")
        old = self.info.get("handle")
        history = self.info.setdefault("handles", [])
        if not any(h["handle"].lower() == handle.lower() for h in history):
            history.append({"handle": handle, "first_seen": when})
        if old and old.lower() != handle.lower():
            self.info["handle"] = handle
            return old
        self.info["handle"] = handle
        return None

    def video(self, vid):
        """Get or create the entry for one video."""
        return self.videos.setdefault(str(vid), {})

    def record_error(self, reason, threshold, when):
        """Count an account-level error. Returns True if this one flagged it."""
        st = self.state
        st["error_count"] = st.get("error_count", 0) + 1
        st["error_last"] = reason
        st["error_date"] = when
        if st["error_count"] >= threshold and not st.get("flagged"):
            st["flagged"] = True
            return True
        return False

    def clear_errors(self):
        for key in ("error_count", "error_last", "error_date", "flagged"):
            self.state.pop(key, None)

    def save(self):
        h = self.data["header"]
        h["updated"] = store.now()
        h["mogul_version"] = VERSION
        h["video_count"] = len(self.videos)
        h["file_count"] = sum(1 for v in self.videos.values() if v.get("file"))
        # newest first (TikTok IDs grow over time)
        self.data["videos"] = dict(sorted(self.videos.items(),
                                          key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0,
                                          reverse=True))
        store.save(self.path, self.data)


class Catalog:
    def __init__(self, settings):
        self.settings = settings
        self.dir = os.path.join(settings.catalog_dir, "accounts")
        self.blocked_path = os.path.join(settings.catalog_dir, "blocked.json")
        self._accounts = None

    # --- accounts ---
    def path_for(self, uid):
        return os.path.join(self.dir, f"{uid}.json")

    def all(self):
        if self._accounts is None:
            self._accounts = []
            if os.path.isdir(self.dir):
                for name in sorted(os.listdir(self.dir)):
                    if name.endswith(".json") and not name.startswith("."):
                        path = os.path.join(self.dir, name)
                        try:
                            self._accounts.append(Account(path, store.load(path)))
                        except (OSError, ValueError) as e:
                            print(f"WARNING: can't read {path}: {e}")
        return self._accounts

    def find(self, name):
        """Find an account by ID, current handle or any past handle."""
        key = clean_name(name)
        for acc in self.all():
            if key in acc.names():
                return acc
        return None

    def by_uid(self, uid):
        uid = str(uid).lstrip("0") or "0"
        for acc in self.all():
            if acc.uid == uid:
                return acc
        return None

    def create(self, uid, handle, when, **info):
        uid = str(uid)
        data = {
            "header": {
                "schema": SCHEMA,
                "schema_version": SCHEMA_VERSION,
                "media_type": "tiktok",
                "created": when,
                "updated": when,
            },
            "account": {
                "uploader_id": uid,
                "handle": (handle or uid).lstrip("@"),
                "handles": [],
                "display_name": info.get("display_name"),
                "channel_url": info.get("channel_url"),
                "category": info.get("category") or "general",
                "tags": info.get("tags") or [],
                "status": info.get("status", "active"),
                "notes": info.get("notes"),
                "added": when,
            },
            "state": {},
            "videos": {},
        }
        acc = Account(self.path_for(uid), data)
        if handle and not is_numeric_id(handle):
            acc.set_handle(handle, when)
        self.all().append(acc)
        return acc

    def select(self, name=None, category=None, statuses=("active", "empty"), uids=None):
        """Accounts matching the usual filters, sorted by category then handle.

        name      one account by ID or handle
        category  comma-separated tags; an account must have all of them
        statuses  which statuses to include (None = all)
        uids      only these IDs (keeps this order)
        """
        if name:
            acc = self.find(name)
            return [acc] if acc else []
        accs = self.all()
        if statuses:
            accs = [a for a in accs if a.status in statuses]
        tags = split_tags(category)
        if tags:
            accs = [a for a in accs if a.has_tags(tags)]
        if uids is not None:
            index = {a.uid: a for a in accs}
            return [index[u] for u in uids if u in index]
        return sorted(accs, key=lambda a: (a.category, a.handle.lower()))

    # --- block list ---
    def blocked(self):
        if os.path.isfile(self.blocked_path):
            return store.load(self.blocked_path)
        return {"blocked": []}

    def is_blocked(self, name):
        key = clean_name(name)
        for b in self.blocked()["blocked"]:
            if key in (clean_name(b.get("handle") or ""), b.get("uploader_id")):
                return b
        return None

    def save_blocked(self, data):
        data["blocked"].sort(key=lambda b: (b.get("handle") or b.get("uploader_id") or ""))
        store.save(self.blocked_path, data)
