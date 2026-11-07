"""TikTok settings from the [tiktok] section of mogul.toml, with defaults."""

import os

DEFAULTS = {
    "library": "mogul_library/tiktok",
    "quarantine": "mogul_quarantine/tiktok",
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

    @property
    def library_dir(self):
        return self.config.resolve(self.data["library"])

    @property
    def quarantine_dir(self):
        return self.config.resolve(self.data["quarantine"])

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
