"""TikTok settings from the [tiktok] section of mogul.toml, with defaults."""

import os

DEFAULTS = {
    # A drive base holds the usual MOGUL folders. "" = the folder mogul.toml
    # is in. Categories listed in [tiktok.drives] use that base instead.
    "base": "",
    "library_folder": "mogul_library/tiktok",
    "incoming_folder": "mogul_incoming/tiktok",
    "blocked_folder": "mogul_blocked/tiktok",
    "quarantine_folder": "mogul_quarantine/tiktok",
    # Empty = inside mogul_userdata/tiktok/, the private folder for
    # anything tied to this user (never goes to GitHub).
    "state": "",
    "reports": "",
    "cookies": "",
    "folder_template": "{uid19}",
    "filename_template": "{yyyy}.{mm}.{dd}-{id}",
    "extensions": ["mp4", "webm", "mkv", "mov", "m4a", "mp3", "aac"],
    "impersonate": "Chrome-131:Android-14",
    "timeout": 120,
    "timeout_per_video": 0.15,
    "timeout_max": 1800,
    "rate_min": 2,
    "rate_max": 6,
    "video_delay_min": 0.5,
    "video_delay_max": 1.5,
    "warn_over": 1000,
    "large_channel": 1000,
    "error_threshold": 3,
    "dormant_peek": 5,
    "dormant_threshold": 3,
    "rename_audio_only": True,
}


class Settings:
    def __init__(self, config):
        self.config = config
        data = dict(DEFAULTS)
        data.update(config.section("tiktok"))
        self.data = data

    def __getattr__(self, name):
        try:
            return self.data[name]
        except KeyError:
            raise AttributeError(name)

    # --- folders ---
    @property
    def catalog_dir(self):
        """mogul_json/tiktok: one JSON file per account."""
        return os.path.join(self.config.json_store, "tiktok")

    @property
    def userdata_dir(self):
        """mogul_userdata/tiktok: private, user-specific files ([core] userdata)."""
        return os.path.join(self.config.folder("userdata", "mogul_userdata"), "tiktok")

    @property
    def blocked_path(self):
        return os.path.join(self.userdata_dir, "blocked.json")

    def _private(self, key, default_name):
        value = self.data.get(key)
        if value:
            return self.config.resolve(value)
        return os.path.join(self.userdata_dir, default_name)

    @property
    def reports_dir(self):
        return self._private("reports", "reports")

    # --- drive bases ---
    # Each category lives under a base folder (its [tiktok.drives] entry, or
    # the default base), with the usual MOGUL folders inside:
    #   <base>/mogul_library/tiktok/<id>/      the archive
    #   <base>/mogul_incoming/tiktok/<id>/     files waiting to be moved in
    #   <base>/mogul_blocked/tiktok/<id>/      blocked accounts, for hand-sorting
    #   <base>/mogul_quarantine/tiktok/<id>/   files validate couldn't fix

    @property
    def default_base(self):
        return self.config.resolve(self.data.get("base") or ".")

    @property
    def drives(self):
        """{category: base folder} from [tiktok.drives], paths resolved."""
        raw = self.data.get("drives") or {}
        return {str(k).lower().strip(): self.config.resolve(v)
                for k, v in raw.items() if isinstance(v, str) and v}

    def base_for(self, category):
        return self.drives.get((category or "").lower().strip()) or self.default_base

    def _under(self, category, key):
        sub = self.data.get(key) or DEFAULTS[key]
        if os.path.isabs(os.path.expanduser(sub)):
            return self.config.resolve(sub)  # one folder for every drive
        return os.path.normpath(os.path.join(self.base_for(category), sub))

    def library_for(self, category):
        return self._under(category, "library_folder")

    def incoming_for(self, category):
        return self._under(category, "incoming_folder")

    def blocked_for(self, category):
        return self._under(category, "blocked_folder")

    def quarantine_for(self, category):
        return self._under(category, "quarantine_folder")

    def _roots(self, fn):
        out = []
        for cat in [None] + list(self.drives):
            path = fn(cat)
            if path not in out:
                out.append(path)
        return out

    @property
    def library_dir(self):
        """The default library (categories not in [tiktok.drives])."""
        return self.library_for(None)

    @property
    def quarantine_dir(self):
        return self.quarantine_for(None)

    @property
    def library_roots(self):
        return self._roots(self.library_for)

    @property
    def blocked_roots(self):
        return self._roots(self.blocked_for)

    @property
    def incoming_roots(self):
        return self._roots(self.incoming_for)

    @property
    def quarantine_roots(self):
        return self._roots(self.quarantine_for)

    @property
    def state_dir(self):
        return self._private("state", "state")

    @property
    def cookies_path(self):
        return self._private("cookies", "cookies.txt")

    @property
    def hashes(self):
        return self.config.hashes

    @property
    def ext_set(self):
        return {"." + e.lower().lstrip(".") for e in self.data["extensions"]}
