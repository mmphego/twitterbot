#!/usr/bin/env python

"""
Copyright 2016 Randal S. Olson

This file is part of the Twitter Bot library.

The Twitter Bot library is free software: you can redistribute it and/or
modify it under the terms of the GNU General Public License as published by the
Free Software Foundation, either version 3 of the License, or (at your option)
any later version.

The Twitter Bot library is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with
the Twitter Bot library. If not, see http://www.gnu.org/licenses/.
"""

import argparse
import csv
import random
import sys
import time
import pathlib

import tweepy

from argparse import RawTextHelpFormatter
from collections import defaultdict
from dateutil.parser import parse

from loguru import logger as _loguru_logger

from settings import ConfigSettings

# Used for random timers
random.seed()


def logger(loglevel):
    LOG_LEVELS = [
        {"name": "DEBUG", "no": 10},
        {"name": "INFO", "no": 20},
        {"name": "SUCCESS", "no": 25},
        {"name": "WARNING", "no": 30},
        {"name": "ERROR", "no": 40},
        {"name": "CRITICAL", "no": 50},
    ]

    LOG_HANDLER = {"sink": sys.stdout, "level": loglevel}

    try:
        _loguru_logger.remove()
        _loguru_logger.configure(handlers=[LOG_HANDLER], levels=LOG_LEVELS)
    except Exception:
        raise RuntimeError("No such log level: %s" % log_level)
    else:
        return _loguru_logger


def file_last_mod(file: str) -> int:
    return pathlib.os.path.getmtime(file)


def divide_chunks(l: list, n: int) -> list:
    # looping till length l
    for i in range(0, len(l), n):
        yield l[i : i + n]


class TwitterBot:
    """
    Bot that automates several actions on Twitter, such as following users and favoriting tweets.
    """

    def __init__(self, logger=_loguru_logger, user=""):
        self.logger = logger
        # this variable contains the configuration for the bot
        self.default_settings = self.initialize_bot(user=user)
        # this variable contains the authorized connection to the Twitter API
        self._twitter = None

    @property
    def twitter(self) -> object:
        """Reads in the bot configuration file and sets up the bot."""
        # check how old the follower sync files are and recommend updating them
        # if they are old
        cur_time = time.time()
        if (
            cur_time - file_last_mod(self.default_settings["follows_file"]) > 86400
            or cur_time - file_last_mod(self.default_settings["followers_file"]) > 86400
        ):
            self.logger.warning(
                "Your Twitter follower sync files are more than a day old. "
                "It is highly recommended that you sync them by calling sync_follows() "
                "before continuing."
            )

        # create an authorized connection to the Twitter API
        if not self._twitter:
            authentication = tweepy.OAuthHandler(
                self.default_settings["api_key"], self.default_settings["api_secret"],
            )
            authentication.set_access_token(
                self.default_settings["access_token_key"],
                self.default_settings["access_token_secret"],
            )
            self._twitter = tweepy.API(authentication)

        return self._twitter

    def wait(self, min_time: int = 1, max_time: int = 10):
        wait_time = random.randint(min_time, max_time)
        if wait_time > 0:
            self.logger.debug(f"sleeping for {wait_time} seconds before action.")
            time.sleep(wait_time)
        return wait_time

    def initialize_bot(self, config_dir=".tweeterbot", user=None) -> dict:
        self.logger.debug("Initializing TweeterBot...")
        config_path = pathlib.Path.home().joinpath(config_dir)
        if not config_path.exists():
            config_path.mkdir()
        filename = config_path.joinpath("config.ini")
        settings = ConfigSettings(filename=filename, user=user, _logger=self.logger)
        return settings.default_settings

    def sync_follows(self):
        """
        Syncs the user's followers and follows locally so it isn't necessary
        to repeatedly look them up via the Twitter API.

        It is important to run this method at least daily so the bot is working
        with a relatively up-to-date version of the user's follows.

        Do not run this method too often, however, or it will quickly cause your
        bot to get rate limited by the Twitter API.
        """
        self.logger.info(
            f"Syncing {self.default_settings['twitter_handle']!r} "
            "account followers and followings."
        )
        followers_ids = self.twitter.followers_ids()
        with open(self.default_settings["followers_file"], "w") as out_file:
            self.logger.debug(
                f"Writing followers to file: {self.default_settings['followers_file']}"
            )
            for follower in followers_ids:
                out_file.write(f"{follower}\n")
        self.wait()

        # sync the user's follows (accounts the user is following)
        followings_ids = self.twitter.friends_ids()
        with open(self.default_settings["follows_file"], "w") as out_file:
            self.logger.debug(
                f"Writing followers to file: {self.default_settings['follows_file']}"
            )
            for follow in followings_ids:
                out_file.write(f"{follow}\n")
        self.logger.info("Done syncing data with Twitter to file")

    def follow_user(
        self,
        user_obj: object,
        n_followers: int = 100,
        followers_follow_ratio: tuple = (0.6, 1.4),
        n_tweets: int = 100,
    ) -> None:
        """Allows the user to follow the user specified in the ID parameter."""
        if not hasattr(user_obj, "screen_name"):
            user_obj = user_obj.user

        if self.ignore_user(
            user_obj, check_user=True
        ) or user_obj.screen_name == self.default_settings.get("TWITTER_HANDLE"):
            return

        try:
            ff_ratio = user_obj.followers_count / user_obj.friends_count

            if not (followers_follow_ratio[0] <= ff_ratio <= followers_follow_ratio[1]):
                self.logger.warning(
                    f"Non-follow back user: {self.user_stats(user_obj)}"
                )
                self.ignore_user(user_obj)
                return
        except Exception:
            return

        try:
            if user_obj.followers_count < n_followers:
                self.logger.warning(
                    f"User: {user_obj.screen_name!r} has less than "
                    f"{n_followers} followers, might be spam!"
                )
                self.ignore_user(user_obj)
                return

            elif user_obj.statuses_count < n_tweets:
                self.logger.warning(f"Ghost user: {self.user_stats(user_obj)}")
                self.ignore_user(user_obj)
                return

            elif user_obj.protected:
                self.logger.warning(f"Protected user: {self.user_stats(user_obj)}")
                self.ignore_user(user_obj)
                return

            elif user_obj.following:
                self.logger.warning(f"Already following {self.user_stats(user_obj)}")
                self.ignore_user(user_obj)
                return

            else:
                self.logger.info(f"Followed @{self.user_stats(user_obj)}")
                self.wait()
                result = self.twitter.create_friendship(user_id=user_obj.id)
        except Exception as error:
            self.ignore_user(user_obj)
            self.logger.error(str(error))
            if "You are unable to follow more people at this time." in str(error):
                raise RuntimeError(str(error))
        else:
            return result

    @staticmethod
    def user_stats(user: object):
        """String formatter."""
        result = ""
        if hasattr(user, "screen_name"):
            result += f"{user.screen_name}, "
        if hasattr(user, "followers_count"):
            result += f"Followers: {user.followers_count}, "
        if hasattr(user, "friends_count"):
            result += f"Following: {user.friends_count}, "
        if hasattr(user, "friends_count") and hasattr(user, "followers_count"):
            try:
                ff_ratio = user.followers_count / user.friends_count
            except ZeroDivisionError:
                ff_ratio = 0
            result += f"FF_Ratio: {ff_ratio:.2f}, "
        if hasattr(user, "id"):
            result += f"[id: {user.id}]"

        return result

    def ignore_user(self, user_obj: object, check_user: bool = False):
        """Write all users to file, that are likely spammers, protected, ghost users."""
        filename = self.default_settings["non_following_file"]
        if check_user:
            with open(filename) as out_file:
                ids = [i.strip() for i in out_file.readlines()]
            return str(user_obj.id) in ids

        with open(filename, "a") as out_file:
            out_file.write(f"{user_obj.id}\n")

    def unfollow_user(
        self,
        user_obj: object,
        unfollow_verified: bool = False,
        unfollow_protected: bool = False,
    ):
        """Allows the user to unfollow the user specified in the ID parameter."""
        try:
            if user_obj.verified != unfollow_verified:
                self.logger.warning(
                    f"@{user_obj.screen_name} is verified, therefore will not unfollow."
                )
                self.ignore_user(user_obj)
                return
            elif user_obj.protected != unfollow_protected:
                self.ignore_user(user_obj)
                return
            elif not user_obj.following:
                self.ignore_user(user_obj)
                return
            else:
                self.wait()
                result = self.twitter.destroy_friendship(user_id=user_obj.id)
                self.logger.info(f"Unfollowed @{self.user_stats(result)}")
        except Exception as error:
            self.logger.error(str(error))

    def username_lookup(self, user_id):
        """Find username by id."""
        return self.twitter.lookup_users(
            user_ids=user_id if isinstance(user_id, list) else [user_id]
        )

    # ----------------------------------
    def get_do_not_follow_list(self) -> set:
        """Returns the set of users the bot has already followed in the past."""
        self.logger.debug("Getting all users I have already followed in the past.")
        dnf_list = set()
        with open(self.default_settings["already_followed_file"], "r") as in_file:
            dnf_list.update(int(line) for line in in_file)

        with open(self.default_settings["non_following_file"], "r") as in_file:
            dnf_list.update(int(line) for line in in_file)

        return dnf_list

    def get_followers_list(self) -> set:
        """Returns the set of users that are currently following the user."""
        self.logger.debug("Getting all followers.")
        followers_list = set()
        with open(self.default_settings["followers_file"], "r") as in_file:
            followers_list.update(int(line) for line in in_file)
        return followers_list

    def get_follows_list(self) -> set:
        """Returns the set of users that the user is currently following."""
        self.logger.debug("Getting all users I follow")
        follows_list = set()
        with open(self.default_settings["follows_file"], "r") as in_file:
            follows_list.update(int(line) for line in in_file)
        return follows_list

    # ----------------------------------
    def search_tweets(self, phrase, count=100, result_type="recent"):
        """
        Returns a list of tweets matching a phrase (hashtag, word, etc.).
        """
        return self.twitter.search(q=phrase, result_type=result_type, count=count)

    def auto_follow_by_hashtag(
        self,
        phrase: str,
        friends_count: int = 300,
        count: int = 200,
        auto_sync: bool = False,
        result_type: str = "recent",
    ):
        """Follows anyone who tweets about a phrase (hashtag, word, etc.)."""
        if auto_sync:
            self.sync_follows()
        results = self.search_tweets(phrase, count, result_type)

        screen_names_set = set(i.user.screen_name for i in results)

        users_dict = defaultdict(list)
        for result in results:
            if result.user.screen_name in screen_names_set:
                users_dict[result.user.screen_name] = result

        statuses = [
            i
            for i in users_dict.values()
            if i.user.screen_name != self.default_settings.get("TWITTER_HANDLE")
            and not i.user.protected
            and not i.user.following
            and i.user.profile_image_url
            and i.user.friends_count > friends_count
            and i.user.statuses_count > count
        ]

        self.logger.info(f"Following {len(statuses)} users.")
        for tweet in statuses:
            if not self.ignore_user(tweet, check_user=True):
                self.follow_user(tweet)

    def auto_follow_followers(self, auto_sync=False):
        """Follows back everyone who's followed you."""
        if auto_sync:
            self.sync_follows()
        following = self.get_follows_list()
        followers = self.get_followers_list()
        already_followed = self.get_do_not_follow_list()
        not_following_back = list(followers - following - already_followed)

        if not not_following_back:
            self.logger.warning("No-one to follow.")
            return

        not_following_back = self.username_lookup(not_following_back)
        self.logger.info(f"Following {len(not_following_back)} users.")
        for i in range(0, len(not_following_back), 99):
            for user_obj in not_following_back[i : i + 99]:
                self.follow_user(user_obj)

    def auto_follow_followers_of_user(self, user_twitter_handle):
        """Follows the followers of a specified user."""
        followers_of_user = set(
            self.twitter.followers_ids(screen_name=user_twitter_handle)
        )
        followers_of_user = list(followers_of_user)
        for i in range(0, len(followers_of_user), 99):
            for user_id in followers_of_user[i : i + 99]:
                self.follow_user(user_id)

    def auto_unfollow_nonfollowers(
        self, auto_sync: bool, unfollow_verified: bool,
    ):
        """Unfollows everyone who hasn't followed you back."""
        # if auto_sync:
        # self.sync_follows()
        following = self.get_follows_list()
        followers = self.get_followers_list()
        already_followed_list = self.get_do_not_follow_list()
        not_following_back = list(following - followers - already_followed_list)
        if not not_following_back:
            return

        # update the "already followed" file with users who didn't follow back
        with open(self.default_settings["already_followed_file"], "w") as out_file:
            for val in not_following_back:
                out_file.write(f"{val}\n")

        non_followers = list(divide_chunks(not_following_back, 99))
        _non_followers = [self.username_lookup(i) for i in non_followers]
        flat_list = [item for sublist in _non_followers for item in sublist]
        self.logger.info(f"Un-following {len(flat_list)} users.")
        for user_obj in flat_list:
            self.unfollow_user(user_obj, unfollow_verified)

    # ----------------------------------
    def unfollow_list_of_users(self, users=[]):
        """Unfollows a list of users"""
        try:
            assert isinstance(users, list)
            unfollow_users = users
        except Exception as err_msg:
            self.logger.exception("Failed to parse list of users, will read from file")
            with open(self.default_settings["non_followers_file"]) as in_file:
                unfollow_users = [l.strip() for l in in_file.readlines() if l.strip()]

        for user_id in unfollow_users:
            self.unfollow_user(user_id)
            user_id.pop(0)

    # ----------------------------------
    def send_tweet(self, message: str) -> object:
        """Posts a tweet."""
        try:
            resp = self.twitter.update_status(status=message)
            assert time.time() - resp.created_at.timestamp() > 2
            print("Tweeted successfully!")
        except Exception:
            print("Failed to send tweet!")

    def send_tweet_with_image(self, image_path: str, message: str) -> object:
        """posts a tweet with an image."""
        try:
            resp = self.twitter.update_with_media(filename=image_path, status=message)
            assert time.time() - resp.created_at.timestamp() < 2
            print("Tweeted successfully!")
        except Exception:
            print("Failed to send tweet!")

    def nuke_old_tweets(self, to_date="2000-01-01", tweets_csv_file=None):
        """
        Open browser and go to https://twitter.com/settings/account
        Click: get your Your Twitter archive
        ---wait for file then download and extract to directory---

        to_date: str
            date to delete from!
            format: YYYY-MM-DD
        tweet_csv_file: csv
            location where the file is stored
        """
        global count
        self.logger.info(f"Deleting old tweets from {to_date}!!!")
        _deleted = False
        if tweets_csv_file is None:
            self.logger.error("Need a CSV file to continue")

        try:
            time.strptime(to_date, "%Y-%m-%d")
        except Exception:
            self.logger.error(
                "Date must be in correct format [expected format: YYYY-MM-DD]!!"
            )
            return

        try:
            input_file = csv.DictReader(open(tweets_csv_file))
        except Exception:
            self.logger.error("File corrupted: retry")
            return

        deleted_tweets = []
        for count, row in enumerate(input_file, 1):
            tweet_timestamp = parse(
                row.get("timestamp", "1999-01-01"), ignoretz=True
            ).date()
            tweet_id = int(row.get("tweet_id", 0))
            if to_date != "" and tweet_timestamp < parse(to_date).date():
                try:
                    self.wait()
                    _state = self.twitter.destroy_status(id=tweet_id)
                    row = row.get("text", "").replace("\n", "")
                    self.logger.info(f"Deleted tweet: {tweet_timestamp}: {row}")
                    deleted_tweets.append(_state)
                except Exception as err:
                    self.logger.error("%s" % (str(err)))

        if deleted_tweets:
            self.logger.info(f"Number of deleted tweets: {count}")


if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description=(
            "A Python bot that automates several actions on Twitter, such as following \n"
            "and unfollowing users."
        ),
        formatter_class=RawTextHelpFormatter,
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        default=False,
        help=(
            "Syncing your Twitter following locally. Due to Twitter API rate limiting, \n"
            "the bot must maintain a local cache of all of your followers so it doesn't\n"
            "use all of your API time looking up your followers.\n"
            "It is highly recommended to sync the bot's local cache daily\n"
        ),
    )
    parser.add_argument(
        "--no-sync", action="store_false", default=True, help="Do not resync."
    )
    parser.add_argument(
        "--tweet", "-t", nargs="+", type=str, action="store", help="message to post."
    )
    parser.add_argument(
        "--tweet-image",
        "-i",
        nargs="+",
        type=str,
        action="store",
        help="message to post with image path. \n\tUsage: '`image path`' '`message`'",
    )
    parser.add_argument(
        "--username",
        "-u",
        type=str,
        required=True,
        action="store",
        help="Twitter username.",
    )
    parser.add_argument(
        "--follow-by-hashtag", action="store", help="Follow users by hashtag.",
    )
    parser.add_argument(
        "--follow-back",
        action="store_true",
        default=False,
        help="Follows back everyone who's followed you.",
    )
    parser.add_argument(
        "--unfollow",
        action="store_true",
        default=False,
        help=" Unfollow everyone who hasn't followed you back.",
    )
    parser.add_argument(
        "--nuke-old-tweets",
        action="store",
        help=(
            "Delete old tweets, you will be prompted for a date of which tweets will be "
            "deleted from. Add your csv path as argument.\n"
            "Note: \tYou need to download your Twitter archive csv file, \n"
            "\twhich can be downloaded here: https://twitter.com/settings/account \n"
            "\tfollow the instructions to download.\n"
        ),
    )
    parser.add_argument(
        "--loglevel",
        default="INFO",
        type=str,
        help="log level to use, default INFO, options INFO, DEBUG, ERROR",
    )
    if len(sys.argv) < 2:
        parser.print_help()
        sys.exit(1)

    parsed_args = parser.parse_args()
    args = vars(parsed_args)

    log = logger(args.get("loglevel", "INFO").upper())
    tweeter_bot = TwitterBot(logger=log, user=args.get("username"))

    if args.get("sync"):
        tweeter_bot.sync_follows()

    if args.get("tweet") or args.get("tweet_image"):
        if args.get("tweet_image"):
            tweet_image = args.get("tweet_image")
            image_path = "".join(
                i for i in tweet_image if any([".jpeg" in i, ".png" in i, ".jpg" in i,])
            )
            if pathlib.Path(image_path).is_file():
                tweet_image.remove(image_path)
                image_path = pathlib.Path(image_path).absolute().as_posix()

            msg = " ".join(tweet_image)
            if "day" in msg.lower():
                msg += "\n\n#100DaysOfCode #Code"
            tweeter_bot.send_tweet_with_image(image_path, msg)
        else:
            msg = " ".join(args.get("tweet"))
            if "day" in msg.lower():
                msg += "\n\n#100DaysOfCode #Code"
            tweeter_bot.send_tweet(msg)

    if args.get("follow_by_hashtag"):
        tweeter_bot.auto_follow_by_hashtag(
            phrase=args.get("follow_by_hashtag"), auto_sync=args.get("no_sync")
        )

    if args.get("follow_back"):
        tweeter_bot.auto_follow_followers(auto_sync=args.get("no_sync"))

    if args.get("unfollow"):
        tweeter_bot.auto_unfollow_nonfollowers(
            auto_sync=args.get("no_sync"), unfollow_verified=False
        )

    if args.get("nuke_old_tweets"):
        date = input("Enter date to start deleting tweets from!!!\n[YYYY-MM-DD] >> ")
        tweeter_bot.nuke_old_tweets(
            to_date=date, tweets_csv_file=args.get("nuke_old_tweets")
        )
