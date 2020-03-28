import configparser
import pathlib
from collections import defaultdict, OrderedDict

from loguru import logger


class ConfigSettings:
    def __init__(self, filename):
        self.filename = filename
        self.default_settings = OrderedDict(
            {
                "api_key": pathlib.os.getenv("API_KEY"),
                "api_secret": pathlib.os.getenv("API_SECRET"),
                "access_token_key": pathlib.os.getenv("ACCESS_TOKEN_KEY"),
                "access_token_secret": pathlib.os.getenv("ACCESS_TOKEN_SECRET"),
                "twitter_handle": pathlib.os.getenv("TWITTER_HANDLE"),
                "already_followed_file": self.filename.parent.joinpath(
                    "already_followed.txt"
                ),
                "followers_file": self.filename.parent.joinpath("followers.txt"),
                "follows_file": self.filename.parent.joinpath("following.txt"),
                "non_followers_file": self.filename.parent.joinpath(
                    "non-followers.txt"
                ),
            }
        )
        self.check_if_exists()

    def check_if_exists(self):
        config = configparser.ConfigParser()
        if not pathlib.Path(self.filename).exists():
            if not all(self.default_settings.values()):
                self.create_config()
            config["DEFAULT"] = self.default_settings
            with open(self.filename, "w") as config_file:
                config.write(config_file)
        else:
            config.read(self.filename)
            _default_settings = OrderedDict(config.defaults())
            if _default_settings != self.default_settings:
                # If dictionaries are not the same, merge them.
                self.default_settings = {**self.default_settings, **_default_settings}
            else:
                self.default_settings = _default_settings
        self.check_files_lookup()

    def create_config(self):
        logger.info("Creating the tweeterbot config file.")
        for key in self.default_settings:
            if not isinstance(self.default_settings[key], pathlib.PosixPath):
                value = None
                while not value:
                    value = str(input(f"Enter Twitter {key.lower()}: "))
                self.default_settings[key] = value

    def check_files_lookup(self):
        txt_files = list(self.filename.parent.glob("*.txt"))
        for key in self.default_settings:
            if (
                ".txt" in self.default_settings[key]
                and self.default_settings[key] not in txt_files
            ):
                try:
                    self.default_settings[key].touch()
                except AttributeError:
                    pathlib.Path(self.default_settings[key]).touch()
