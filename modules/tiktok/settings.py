"""TikTok settings from the [tiktok] section of mogul.toml, with defaults."""

import os

DEFAULTS = {
    "library": "mogul_library/tiktok",
    "quarantine": "mogul_quarantine/tiktok",
    "state": "mogul_state/tiktok",
    "cookies": "cookies.txt",
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
    def reports_dir(self):
        return self.config.reports

    @property
    def library_dir(self):
        return self.config.resolve(self.data["library"])

    @property
    def quarantine_dir(self):
        return self.config.resolve(self.data["quarantine"])

    @property
    def state_dir(self):
        return self.config.resolve(self.data["state"])

    @property
    def cookies_path(self):
        return self.config.resolve(self.data["cookies"])

    @property
    def hashes(self):
        return self.config.hashes

    @property
    def ext_set(self):
        return {"." + e.lower().lstrip(".") for e in self.data["extensions"]}
