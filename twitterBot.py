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
import os
import random
import sys
import time
import pathlib

import tweepy

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


class TwitterBot:
    """
    Bot that automates several actions on Twitter, such as following users and favoriting tweets.
    """

    def __init__(self, logger=_loguru_logger):
        self.logger = logger
        # this variable contains the configuration for the bot
        self.default_settings = self.initialize_bot()
        # this variable contains the authorized connection to the Twitter API
        self._twitter = None

    @property
    def twitter(self) -> object:
        """Reads in the bot configuration file and sets up the bot."""
        # check how old the follower sync files are and recommend updating them
        # if they are old
        if (
            time.time() - os.path.getmtime(self.default_settings["follows_file"])
            > 86400
            or time.time() - os.path.getmtime(self.default_settings["followers_file"])
            > 86400
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

    def initialize_bot(self, config_dir=".tweeterbot") -> dict:
        self.logger.info("Initializing TweeterBot...")
        config_path = pathlib.Path.home().joinpath(config_dir)
        if not config_path.exists():
            config_path.mkdir()
        filename = config_path.joinpath("config.ini")
        settings = ConfigSettings(filename)

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
        self.logger.info("Sync the user's followers (accounts following the user).")
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
        followers_follow_ratio: int = 5,
    ) -> None:
        """Allows the user to follow the user specified in the ID parameter."""
        ff_ratio = user_obj.user.friends_count / float(user_obj.user.followers_count)
        try:
            if user_obj.user.followers_count < n_followers:
                self.logger.warning(
                    f"User: {user_obj.user.screen_name!r} has less than "
                    f"{n_followers} followers, might be spam!"
                )
                return
            elif ff_ratio >= followers_follow_ratio:
                self.logger.warning(
                    f"Non-follow back user: {self.user_stats(user_obj)}"
                )
                return
            if not (user_obj.user.protected and user_obj.user.following):
                self.logger.info(
                    f"Followed @{user_obj.user.screen_name}, followers:{user_obj.user.followers_count}, "
                    f"following:{user_obj.user.friends_count}, ratio:{ff_ratio}"
                )
                self.wait()
                result = self.twitter.create_friendship(user_id=user_obj.user.id)
        except Exception:
            self.logger.exception("Error occurred investigate")
        else:
            return result

    @staticmethod
    def user_stats(user: object):
        result = ""
        if hasattr(user, "screen_name"):
            result += f"{user.screen_name}, "
        if hasattr(user, "followers_count"):
            result += f"Followers: {user.followers_count}, "
        if hasattr(user, "friends_count"):
            result += f"Following: {user.friends_count}, "
        if hasattr(user, "friends_count") and hasattr(user, "followers_count"):
            ff_ratio = user.friends_count / float(user.followers_count)
            result += f"FF_Ratio: {ff_ratio}, "
        if hasattr(user, "id"):
            result += f"[id: {user.id}]"

        return result

    def unfollow_user(self, user_id: int, unfollow_verified: bool = False):
        """Allows the user to unfollow the user specified in the ID parameter."""
        try:
            results = self.username_lookup(user_id)
            for result in results:
                if result.verified != unfollow_verified:
                    self.logger.warning(
                        f"@{result.screen_name} is verified, therefore will not unfollow."
                    )
                    return

            self.wait()
            result = self.twitter.destroy_friendship(user_id=user_id)
            self.logger.info(f"Unfollowed @{self.user_stats(result)}")
        except Exception:
            self.logger.exception("Error occurred, investigate")

    def who_am_i(self):
        self.logger.info("Username is %s" % self.default_settings["twitter_handle"])
        return self.default_settings["twitter_handle"]

    def username_lookup(self, user_id):
        """
        Find username by id
        Params: int
            user id
        Return: dict
            Dict with Users information
        """
        return self.twitter.lookup_users(
            user_ids=user_id if isinstance(user_id, list) else [user_id]
        )

    # ----------------------------------
    def get_do_not_follow_list(self) -> set:
        """Returns the set of users the bot has already followed in the past."""
        self.logger.info("Getting all users I have already followed in the past.")
        dnf_list = set()
        with open(self.default_settings["already_followed_file"], "r") as in_file:
            dnf_list.update(int(line) for line in in_file)
        return dnf_list

    def get_followers_list(self) -> set:
        """Returns the set of users that are currently following the user."""
        self.logger.info("Getting all followers.")
        followers_list = set()
        with open(self.default_settings["followers_file"], "r") as in_file:
            followers_list.update(int(line) for line in in_file)
        return followers_list

    def get_follows_list(self) -> set:
        """Returns the set of users that the user is currently following."""
        self.logger.info("Getting all users I follow")
        follows_list = set()
        with open(self.default_settings["follows_file"], "r") as in_file:
            follows_list.update(int(line) for line in in_file)
        return follows_list

    def get_all_nonfollowers(self, get_name=False, auto_sync=False):
        """
        find everyone who hasn't followed you back.
        """
        self.logger.info("Getting everyone who hasn't followed you back.")
        if auto_sync:
            self.sync_follows()

        following = self.get_follows_list()
        followers = self.get_followers_list()
        self.logger.info(f"Followers: {len(followers)}, Following: {len(following)}")
        not_following_back = list(following - followers)
        non_followers = []
        _non_followers = []
        for n in range(0, len(not_following_back), 99):
            ids = not_following_back[n : n + 99]
            _non_followers.append(ids)
            if get_name:
                subquery = self.username_lookup(ids)
                for user in subquery:
                    non_followers.append(
                        "[%s] @%s [id: %s]"
                        % (
                            "*" if user["verified"] else " ",
                            user["screen_name"],
                            user["id"],
                        )
                    )

        with open(self.default_settings["non_followers_file"], "w") as out_file:
            if non_followers:
                for val in non_followers:
                    out_file.write(str(val) + "\n")
            else:
                for val in _non_followers:
                    out_file.write(str(val) + "\n")

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
        ]

        self.logger.info(f"Following {len(statuses)} users.")
        for tweet in statuses:
            try:
                self.follow_user(tweet)
            except Exception as exc:
                # quit on rate limit errors
                self.logger.error(f"Error: {str(exc)}")

    def auto_follow_followers(self, auto_sync=False):
        """Follows back everyone who's followed you."""
        if auto_sync:
            self.sync_follows()
        following = self.get_follows_list()
        followers = self.get_followers_list()
        already_followed = self.get_do_not_follow_list()
        not_following_back = list(followers - following - already_followed)
        self.logger.info(f"Following {len(not_following_back)} users.")
        for i in range(0, len(not_following_back), 99):
            for user_id in not_following_back[i : i + 99]:
                self.follow_user(user_id)

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
        if auto_sync:
            self.sync_follows()
        following = self.get_follows_list()
        followers = self.get_followers_list()

        not_following_back = list(following - followers)
        # update the "already followed" file with users who didn't follow back
        already_followed = set(not_following_back)
        already_followed_list = []
        with open(self.default_settings["already_followed_file"], "r") as in_file:
            for line in in_file:
                already_followed_list.append(int(line))

        already_followed.update(set(already_followed_list))

        with open(self.default_settings["already_followed_file"], "w") as out_file:
            for val in already_followed:
                out_file.write(f"{val}\n")

        for user_id in sorted(not_following_back):
            self.unfollow_user(user_id, unfollow_verified)

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
        return self.twitter.statuses.update(status=message)

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
                    _state = self.twitter.statuses.destroy(id=tweet_id)
                    row = row.get("text", "").replace("\n", "")
                    self.logger.info(f"Deleted tweet: {tweet_timestamp}: {row}")
                    deleted_tweets.append(_state)
                except Exception as err:
                    self.logger.error("%s" % (str(err.response_data)))

        if deleted_tweets:
            self.logger.info(f"Number of deleted tweets: {count}")


if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description=(
            "A Python bot that automates several actions on "
            "Twitter, such as following and unfollowing users."
        )
    )

    parser.add_argument(
        "--sync",
        action="store_true",
        default=False,
        help=(
            "Syncing your Twitter following locally. Due to Twitter API rate limiting, "
            "the bot must maintain a local cache of all of your followers so it doesn't "
            "use all of your API time looking up your followers. "
            "It is highly recommended to sync the bot's local cache daily"
        ),
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
            "Note: You need to download your Twitter archive csv file, "
            "which can be downloaded here: https://twitter.com/settings/account "
            "follow the instructions to download."
        ),
    )
    parser.add_argument(
        "--loglevel",
        default="INFO",
        type=str,
        help="log level to use, default INFO, options INFO, DEBUG, ERROR",
    )

    args = vars(parser.parse_args())

    log = logger(args.get("loglevel", "INFO").upper())
    tweeter_bot = TwitterBot(logger=log)

    if args.get("sync"):
        tweeter_bot.sync_follows()

    if args.get("follow_by_hashtag"):
        tweeter_bot.auto_follow_by_hashtag(
            phrase=args.get("follow_by_hashtag"), auto_sync=True
        )

    if args.get("follow_back"):
        tweeter_bot.auto_follow_followers(auto_sync=True)

    if args.get("unfollow"):
        tweeter_bot.auto_unfollow_nonfollowers(auto_sync=True, unfollow_verified=False)

    if args.get("nuke_old_tweets"):
        date = input("Enter date to start deleting tweets from!!!\n[YYYY-MM-DD] >> ")
        tweeter_bot.nuke_old_tweets(
            to_date=date, tweets_csv_file=args.get("nuke_old_tweets")
        )
