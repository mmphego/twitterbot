#!/usr/bin/env python

# -*- coding: utf-8 -*-

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
import coloredlogs
import csv
import logging
import os
import random
import sys
import threading
import time

from twitter import Twitter
from twitter import OAuth
from dateutil.parser import parse


# This class could be imported from a utility module
class loggingClass(object):
    @property
    def logger(self):
        super(loggingClass, self).__init__()
        name = ".".join([os.path.basename(sys.argv[0]), self.__class__.__name__])
        logging.basicConfig(format=log_format, level=logging.INFO)
        return logging.getLogger(name)


class TwitterBot(loggingClass):
    """
    Bot that automates several actions on Twitter, such as following users and
    favoriting tweets.
    """

    def __init__(self, config_file="config.txt"):
        # this variable contains the configuration for the bot
        self.BOT_CONFIG = {}
        # this variable contains the authorized connection to the Twitter API
        self.twitter_con = None
        self.bot_setup(config_file)
        # Used for random timers
        random.seed()

    def bot_setup(self, config_file="config.txt"):
        """
        Reads in the bot configuration file and sets up the bot.
        Defaults to config.txt if no configuration file is specified.
        If you want to modify the bot configuration, edit your config.txt.
        """

        with open(config_file, "r") as in_file:
            for line in in_file:
                line = line.split(":")
                parameter = line[0].strip()
                value = line[1].strip()

                if parameter in [
                    "USERS_KEEP_FOLLOWING",
                    "USERS_KEEP_UNMUTED",
                    "USERS_KEEP_MUTED",
                ]:
                    if value != "":
                        self.BOT_CONFIG[parameter] = set(
                            [int(x) for x in value.split(",")]
                        )
                    else:
                        self.BOT_CONFIG[parameter] = set()
                elif parameter in [
                    "FOLLOW_BACKOFF_MIN_SECONDS",
                    "FOLLOW_BACKOFF_MAX_SECONDS",
                ]:
                    self.BOT_CONFIG[parameter] = int(value)
                else:
                    self.BOT_CONFIG[parameter] = value

        # make sure that the config file specifies all required parameters
        required_parameters = [
            "OAUTH_TOKEN",
            "OAUTH_SECRET",
            "CONSUMER_KEY",
            "CONSUMER_SECRET",
            "TWITTER_HANDLE",
            "ALREADY_FOLLOWED_FILE",
            "FOLLOWERS_FILE",
            "NON_FOLLOWERS_FILE",
            "FOLLOWS_FILE",
        ]

        missing_parameters = []

        for required_parameter in required_parameters:
            if (
                required_parameter not in self.BOT_CONFIG
                or self.BOT_CONFIG[required_parameter] == ""
            ):
                missing_parameters.append(required_parameter)

        if len(missing_parameters) > 0:
            self.BOT_CONFIG = {}
            raise Exception(
                "Please edit %s to include the following parameters: %s.\n\n"
                "The bot cannot run unless these parameters are specified."
                % (config_file, ", ".join(missing_parameters))
            )
        # make sure all of the sync files exist locally
        for sync_file in [
            self.BOT_CONFIG["ALREADY_FOLLOWED_FILE"],
            self.BOT_CONFIG["FOLLOWS_FILE"],
            self.BOT_CONFIG["NON_FOLLOWERS_FILE"],
            self.BOT_CONFIG["FOLLOWERS_FILE"],
        ]:
            if not os.path.isfile(sync_file):
                with open(sync_file, "w") as out_file:
                    out_file.write("")

        # check how old the follower sync files are and recommend updating them
        # if they are old
        if (
            time.time() - os.path.getmtime(self.BOT_CONFIG["FOLLOWS_FILE"]) > 86400
            or time.time() - os.path.getmtime(self.BOT_CONFIG["FOLLOWERS_FILE"]) > 86400
        ):
            self.logger.warning(
                "Your Twitter follower sync files are more than a day old. "
                "It is highly recommended that you sync them by calling sync_follows() "
                "before continuing."
            )

        # create an authorized connection to the Twitter API
        self.twitter_con = Twitter(
            auth=OAuth(
                self.BOT_CONFIG["OAUTH_TOKEN"],
                self.BOT_CONFIG["OAUTH_SECRET"],
                self.BOT_CONFIG["CONSUMER_KEY"],
                self.BOT_CONFIG["CONSUMER_SECRET"],
            )
        )

    def wait_to_confuse_twitter(self):
        min_time = 0
        max_time = 0
        if "FOLLOW_BACKOFF_MIN_SECONDS" in self.BOT_CONFIG:
            min_time = int(self.BOT_CONFIG["FOLLOW_BACKOFF_MIN_SECONDS"])

        if "FOLLOW_BACKOFF_MAX_SECONDS" in self.BOT_CONFIG:
            max_time = int(self.BOT_CONFIG["FOLLOW_BACKOFF_MAX_SECONDS"])

        if min_time > max_time:
            temp = min_time
            min_time = max_time
            max_time = temp

        wait_time = random.randint(min_time, max_time)

        if wait_time > 0:
            # self.logger.info("sleeping for %d seconds before action" % wait_time)
            time.sleep(wait_time)

        return wait_time

    @property
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
        followers_status = self.twitter_con.followers.ids(
            screen_name=self.BOT_CONFIG["TWITTER_HANDLE"]
        )
        followers = set(followers_status["ids"])
        next_cursor = followers_status["next_cursor"]

        with open(self.BOT_CONFIG["FOLLOWERS_FILE"], "w") as out_file:
            for follower in followers:
                out_file.write("%s\n" % (follower))

        while next_cursor != 0:
            followers_status = self.twitter_con.followers.ids(
                screen_name=self.BOT_CONFIG["TWITTER_HANDLE"], cursor=next_cursor
            )
            followers = set(followers_status["ids"])
            next_cursor = followers_status["next_cursor"]

            with open(self.BOT_CONFIG["FOLLOWERS_FILE"], "a") as out_file:
                for follower in followers:
                    out_file.write("%s\n" % (follower))

        # sync the user's follows (accounts the user is following)
        following_status = self.twitter_con.friends.ids(
            screen_name=self.BOT_CONFIG["TWITTER_HANDLE"]
        )
        following = set(following_status["ids"])
        next_cursor = following_status["next_cursor"]

        with open(self.BOT_CONFIG["FOLLOWS_FILE"], "w") as out_file:
            for follow in following:
                out_file.write("%s\n" % (follow))

        while next_cursor != 0:
            following_status = self.twitter_con.friends.ids(
                screen_name=self.BOT_CONFIG["TWITTER_HANDLE"], cursor=next_cursor
            )
            following = set(following_status["ids"])
            next_cursor = following_status["next_cursor"]

            with open(self.BOT_CONFIG["FOLLOWS_FILE"], "a") as out_file:
                for follow in following:
                    out_file.write("%s\n" % (follow))
        self.logger.info("Done syncing data with Twitter")

    def follow_user(self, user_id, no_followers=100):
        """
        Allows the user to follow the user specified in the ID parameter.
        Params: int
            The ID of the user to follow.
        Returns: None
        """
        try:
            subquery = self.username_lookup(user_id)
            for user in subquery:
                if user["followers_count"] > no_followers:
                    self.logger.warning(
                        f"User: {user['screen_name']!r} has less than "
                        f"{no_followers} followers, might be spam!"
                    )
                    continue

                if not user["protected"]:
                    self.twitter_con.friendships.create(user_id=user_id)
                    self.logger.info(
                        "Followed @%s [id: %s]" % (user["screen_name"], user["id"])
                    )
                    self.wait_to_confuse_twitter()
        except Exception:
            self.logger.exception("Error occurred investigate")

    def unfollow_user(self, user_id):
        """
        Allows the user to unfollow the user specified in the ID parameter.
        Params: int
            The ID of the user to follow.
        Returns: None
        """
        try:
            self.twitter_con.friendships.destroy(user_id=user_id)
            self.wait_to_confuse_twitter()
            subquery = self.username_lookup(user_id)
            for user in subquery:
                self.logger.info(
                    "Unfollowed @%s [id: %s]" % (user["screen_name"], user["id"])
                )
        except Exception as api_error:
            self.logger.error("Error: %s" % str(api_error))

    def who_am_i(self):
        self.logger.info("Username is %s" % self.BOT_CONFIG["TWITTER_HANDLE"])

    def username_lookup(self, user_id):
        """
        Find username by id
        Params: int
            user id
        Return: dict
            Dict with Users information
        """
        return self.twitter_con.users.lookup(user_id=user_id)

    # ----------------------------------
    def get_do_not_follow_list(self):
        """
        Returns the set of users the bot has already followed in the past.
        """
        self.logger.info("Getting all users I have already followed in the past.")
        dnf_list = []
        with open(self.BOT_CONFIG["ALREADY_FOLLOWED_FILE"], "r") as in_file:
            for line in in_file:
                dnf_list.append(int(line))
        return set(dnf_list)

    def get_followers_list(self):
        """
        Returns the set of users that are currently following the user.
        """
        self.logger.info("Getting all followers.")
        followers_list = []
        with open(self.BOT_CONFIG["FOLLOWERS_FILE"], "r") as in_file:
            for line in in_file:
                followers_list.append(int(line))
        return set(followers_list)

    def get_follows_list(self):
        """
        Returns the set of users that the user is currently following.
        """
        self.logger.info("Getting all users I follow")
        follows_list = []
        with open(self.BOT_CONFIG["FOLLOWS_FILE"], "r") as in_file:
            for line in in_file:
                follows_list.append(int(line))
        return set(follows_list)

    def get_all_nonfollowers(self, get_name=False, auto_sync=False):
        """
        find everyone who hasn't followed you back.
        """
        self.logger.info("Getting everyone who hasn't followed you back.")
        if auto_sync:
            self.sync_follows

        following = self.get_follows_list()
        followers = self.get_followers_list()
        self.logger.info(
            "Followers: %s, Following: %s" % (len(followers), len(following))
        )
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

        with open(self.BOT_CONFIG["NON_FOLLOWERS_FILE"], "w") as out_file:
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
        return self.twitter_con.search.tweets(
            q=phrase, result_type=result_type, count=count
        )

    # ----------------------------------
    def auto_fav_by_hashtag(self, phrase, count=100, result_type="recent"):
        """
        Favourites tweets that match a phrase (hashtag, word, etc.).
        """
        result = self.search_tweets(phrase, count, result_type)
        for tweet in result["statuses"]:
            try:
                # don't favorite your own tweets
                if tweet["user"]["screen_name"] == self.BOT_CONFIG["TWITTER_HANDLE"]:
                    continue
                self.wait_to_confuse_twitter()
                result = self.twitter_con.favorites.create(_id=tweet["id"])
                self.logger.info("Favourite: %s" % (result["text"].encode("utf-8")))
            # when you have already favorited a tweet, this error is thrown
            except Exception as api_error:
                # quit on rate limit errors
                self.logger.error("%s" % str(api_error))

    def auto_rt_by_hashtag(self, phrase, count=100, result_type="recent"):
        """
        Retweets tweets that match a phrase (hashtag, word, etc.).
        """

        result = self.search_tweets(phrase, count, result_type)
        for tweet in result["statuses"]:
            try:
                # don't retweet your own tweets
                if tweet["user"]["screen_name"] == self.BOT_CONFIG["TWITTER_HANDLE"]:
                    continue
                self.wait_to_confuse_twitter()
                result = self.twitter_con.statuses.retweet(id=tweet["id"])
                self.logger.info("Retweeted: %s" % (result["text"].encode("utf-8")))
            # when you have already retweeted a tweet, this error is thrown
            except Exception as api_error:
                # quit on rate limit errors
                self.logger.error("Error: %s" % (str(api_error)))

    def auto_follow_by_hashtag(
        self, phrase, count=200, auto_sync=False, result_type="recent"
    ):
        """
        Follows anyone who tweets about a phrase (hashtag, word, etc.).
        """
        if auto_sync:
            self.sync_follows
        result = self.search_tweets(phrase, count, result_type)
        statuses = [
            i
            for i in result["statuses"]
            if i["user"]["screen_name"] != self.BOT_CONFIG.get("TWITTER_HANDLE")
            and not i["user"]["following"]
            and not i["user"]["protected"]
            and i["user"]["profile_image_url"]
            and i["user"]["friends_count"] > 300
        ]
        random.shuffle(statuses)
        following = self.get_follows_list()
        self.logger.info(f"Following {len(statuses)} users.")
        for tweet in statuses:
            try:
                self.follow_user(tweet["user"]["id"])
                following.update(set([tweet["user"]["id"]]))
            except Exception:
                # quit on rate limit errors
                self.logger.error("Error: %s" % (str(api_error)))

    def auto_follow_followers(self, auto_sync=False):
        """
        Follows back everyone who's followed you.
        """
        if auto_sync:
            self.sync_follows
        following = self.get_follows_list()
        followers = self.get_followers_list()
        already_followed = self.get_do_not_follow_list()
        not_following_back = list(followers - following - already_followed)
        self.logger.info(f"Following {len(not_following_back)} users.")
        for i in range(0, len(not_following_back), 99):
            for user_id in not_following_back[i : i + 99]:
                self.follow_user(user_id)

    def auto_follow_followers_of_user(self, user_twitter_handle):
        """
        Follows the followers of a specified user.
        """
        followers_of_user = set(
            self.twitter_con.followers.ids(screen_name=user_twitter_handle)["ids"]
        )
        followers_of_user = list(followers_of_user)
        for i in range(0, len(followers_of_user), 99):
            for user_id in followers_of_user[i : i + 99]:
                self.follow_user(user_id)

    def auto_unfollow_nonfollowers(self, auto_sync=False):
        """
        Unfollows everyone who hasn't followed you back.
        """
        if auto_sync:
            self.sync_follows
        following = self.get_follows_list()
        followers = self.get_followers_list()

        not_following_back = list(following - followers)
        print(len(not_following_back))
        # update the "already followed" file with users who didn't follow back
        already_followed = set(not_following_back)
        already_followed_list = []
        with open(self.BOT_CONFIG["ALREADY_FOLLOWED_FILE"], "r") as in_file:
            for line in in_file:
                already_followed_list.append(int(line))

        already_followed.update(set(already_followed_list))

        with open(self.BOT_CONFIG["ALREADY_FOLLOWED_FILE"], "w") as out_file:
            for val in already_followed:
                out_file.write(str(val) + "\n")

        for user_id in not_following_back:
            if user_id not in self.BOT_CONFIG["USERS_KEEP_FOLLOWING"]:
                self.unfollow_user(user_id)

    def auto_mute_following(self):
        """
        Mutes everyone that you are following.
        """
        following = self.get_follows_list()
        muted = set(
            self.twitter_con.mutes.users.ids(
                screen_name=self.BOT_CONFIG["TWITTER_HANDLE"]
            )["ids"]
        )

        not_muted = following - muted

        for user_id in not_muted:
            if user_id not in self.BOT_CONFIG["USERS_KEEP_UNMUTED"]:
                self.twitter_con.mutes.users.create(user_id=user_id)
                self.logger.info("Muted %d" % (user_id))

    def auto_unmute(self):
        """
        Unmutes everyone that you have muted.
        """
        muted = set(
            self.twitter_con.mutes.users.ids(
                screen_name=self.BOT_CONFIG["TWITTER_HANDLE"]
            )["ids"]
        )

        for user_id in muted:
            if user_id not in self.BOT_CONFIG["USERS_KEEP_MUTED"]:
                self.twitter_con.mutes.users.destroy(user_id=user_id)
                self.logger.info("Unmuted %d" % (user_id))

    # ----------------------------------
    def unfollow_list_of_users(self, users=[]):
        """
        Unfollows a list of users
        Params: list
            users: List of users to be unfollowed
        """
        try:
            assert users
            unfollow_users = users
        except Exception as err_msg:
            self.logger.exception("Failed to parse list of users, will read from file")
            with open(self.BOT_CONFIG["NON_FOLLOWERS_FILE"]) as in_file:
                unfollow_users = [l.strip() for l in in_file.readlines() if l.strip()]

        for user_id in unfollow_users:
            self.unfollow_user(user_id)
            user_id.pop(0)

    # ----------------------------------
    def send_tweet(self, message):
        """
        Posts a tweet.
        """
        return self.twitter_con.statuses.update(status=message)

    def auto_add_to_list(self, phrase, list_slug, count=100, result_type="recent"):
        """
        Add users to list slug that are tweeting phrase.
        """
        result = self.search_tweets(phrase, count, result_type)
        for tweet in result["statuses"]:
            try:
                if tweet["user"]["screen_name"] == self.BOT_CONFIG["TWITTER_HANDLE"]:
                    continue
                result = self.twitter_con.lists.members.create(
                    owner_screen_name=self.BOT_CONFIG["TWITTER_HANDLE"],
                    slug=list_slug,
                    screen_name=tweet["user"]["screen_name"],
                )
                self.logger.info(
                    "User %s added to the list %s"
                    % (tweet["user"]["screen_name"], list_slug)
                )
            except Exception as api_error:
                self.logger.error("%s" % str(api_error))

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
                    self.wait_to_confuse_twitter()
                    _state = self.twitter_con.statuses.destroy(id=tweet_id)
                    row = row.get("text", "").replace("\n", "")
                    self.logger.info(f"Deleted tweet: {tweet_timestamp}: {row}")
                    deleted_tweets.append(_state)
                except Exception as err:
                    self.logger.error("%s" % (str(err.response_data)))

        if deleted_tweets:
            self.logger.info(f"Number of deleted tweets: {count}"))


if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description=(
            "A Python bot that automates several actions on "
            "Twitter, such as following and unfollowing users."
        )
    )
    parser.add_argument(
        "-c",
        "--config",
        default="config.txt",
        required=True,
        type=str,
        help="Config file which contains all required info.",
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
    log_level = None
    log_format = "%(asctime)s - %(name)s - %(levelname)s : %(lineno)d - %(message)s"

    if args.get("loglevel", "INFO"):
        log_level = args.get("loglevel", "INFO").upper()
        try:
            logging.basicConfig(level=getattr(logging, log_level), format=log_format)
            logger = logging.getLogger(os.path.basename(sys.argv[0]))
        except AttributeError:
            raise RuntimeError("No such log level: %s" % log_level)
        else:
            if log_level == "DEBUG":
                coloredlogs.install(level=log_level, fmt=log_format)
            else:
                coloredlogs.install(level=log_level)

    if not args.get("config"):
        sys.exit(1)
    my_bot = TwitterBot(args.get("config"))

    if args.get("sync"):
        my_bot.sync_follows

    if args.get("follow_by_hashtag"):
        my_bot.auto_follow_by_hashtag(
            phrase=args.get("follow_by_hashtag"), auto_sync=True
        )

    if args.get("follow_back"):
        my_bot.auto_follow_followers(auto_sync=True)

    if args.get("unfollow"):
        my_bot.auto_unfollow_nonfollowers(auto_sync=True)

    if args.get("nuke_old_tweets"):
        date = input("Enter date to start deleting tweets from!!!\n[YYYY-MM-DD] >> ")
        my_bot.nuke_old_tweets(
            to_date=date, tweets_csv_file=args.get("nuke_old_tweets")
        )
