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
from __future__ import print_function
import os
import sys
import time
import random
import threading
import logging

from twitter import Twitter
from twitter import OAuth

log_format = '%(asctime)s - %(name)s - %(levelname)s : %(lineno)d - %(message)s'

# This class could be imported from a utility module
class loggingClass(object):
    @property
    def logger(self):
        super(loggingClass, self).__init__()
        name = '.'.join(
            [os.path.basename(sys.argv[0]), self.__class__.__name__])
        logging.basicConfig(format=log_format, level=logging.INFO)
        return logging.getLogger(name)


class TwitterBot(loggingClass):

    """
        Bot that automates several actions on Twitter, such as following users
        and favoriting tweets.
    """

    def __init__(self, config_file="config.txt"):
        # this variable contains the configuration for the bot
        self.BOT_CONFIG = {}
        # this variable contains the authorized connection to the Twitter API
        self.TWITTER_CONNECTION = None
        self.bot_setup(config_file)

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

                if parameter in ["USERS_KEEP_FOLLOWING", "USERS_KEEP_UNMUTED", "USERS_KEEP_MUTED"]:
                    if value != "":
                        self.BOT_CONFIG[parameter] = set([int(x) for x in value.split(",")])
                    else:
                        self.BOT_CONFIG[parameter] = set()
                elif parameter in ["FOLLOW_BACKOFF_MIN_SECONDS", "FOLLOW_BACKOFF_MAX_SECONDS"]:
                    self.BOT_CONFIG[parameter] = int(value)
                else:
                    self.BOT_CONFIG[parameter] = value

        # make sure that the config file specifies all required parameters
        required_parameters = ["OAUTH_TOKEN", "OAUTH_SECRET", "CONSUMER_KEY", "CONSUMER_SECRET",
                               "TWITTER_HANDLE", "ALREADY_FOLLOWED_FILE", "FOLLOWERS_FILE",
                               "NON_FOLLOWERS_FILE", "FOLLOWS_FILE"]

        missing_parameters = []

        for required_parameter in required_parameters:
            if (required_parameter not in self.BOT_CONFIG or self.BOT_CONFIG[required_parameter] == ""):
                missing_parameters.append(required_parameter)

        if len(missing_parameters) > 0:
            self.BOT_CONFIG = {}
            raise Exception("Please edit %s to include the following parameters: %s.\n\n"
                            "The bot cannot run unless these parameters are specified."
                            % (config_file, ", ".join(missing_parameters)))
        # make sure all of the sync files exist locally
        for sync_file in [self.BOT_CONFIG["ALREADY_FOLLOWED_FILE"],
                          self.BOT_CONFIG["FOLLOWS_FILE"],
                          self.BOT_CONFIG["NON_FOLLOWERS_FILE"],
                          self.BOT_CONFIG["FOLLOWERS_FILE"]]:
            if not os.path.isfile(sync_file):
                with open(sync_file, "w") as out_file:
                    out_file.write("")

        # check how old the follower sync files are and recommend updating them
        # if they are old
        if (time.time() - os.path.getmtime(self.BOT_CONFIG["FOLLOWS_FILE"]) > 86400 or
                time.time() - os.path.getmtime(self.BOT_CONFIG["FOLLOWERS_FILE"]) > 86400):
            self.logger.info("Warning: Your Twitter follower sync files are more than a day old. "
                  "It is highly recommended that you sync them by calling sync_follows() "
                  "before continuing.")

        # create an authorized connection to the Twitter API
        self.TWITTER_CONNECTION = Twitter(auth=OAuth(self.BOT_CONFIG["OAUTH_TOKEN"],
                                                     self.BOT_CONFIG["OAUTH_SECRET"],
                                                     self.BOT_CONFIG["CONSUMER_KEY"],
                                                     self.BOT_CONFIG["CONSUMER_SECRET"]))

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
        followers_status = self.TWITTER_CONNECTION.followers.ids(
            screen_name=self.BOT_CONFIG["TWITTER_HANDLE"])
        followers = set(followers_status["ids"])
        next_cursor = followers_status["next_cursor"]

        with open(self.BOT_CONFIG["FOLLOWERS_FILE"], "w") as out_file:
            for follower in followers:
                out_file.write("%s\n" % (follower))

        while next_cursor != 0:
            followers_status = self.TWITTER_CONNECTION.followers.ids(
                screen_name=self.BOT_CONFIG["TWITTER_HANDLE"], cursor=next_cursor)
            followers = set(followers_status["ids"])
            next_cursor = followers_status["next_cursor"]

            with open(self.BOT_CONFIG["FOLLOWERS_FILE"], "a") as out_file:
                for follower in followers:
                    out_file.write("%s\n" % (follower))

        # sync the user's follows (accounts the user is following)
        following_status = self.TWITTER_CONNECTION.friends.ids(
            screen_name=self.BOT_CONFIG["TWITTER_HANDLE"])
        following = set(following_status["ids"])
        next_cursor = following_status["next_cursor"]

        with open(self.BOT_CONFIG["FOLLOWS_FILE"], "w") as out_file:
            for follow in following:
                out_file.write("%s\n" % (follow))

        while next_cursor != 0:
            following_status = self.TWITTER_CONNECTION.friends.ids(
                screen_name=self.BOT_CONFIG["TWITTER_HANDLE"], cursor=next_cursor)
            following = set(following_status["ids"])
            next_cursor = following_status["next_cursor"]

            with open(self.BOT_CONFIG["FOLLOWS_FILE"], "a") as out_file:
                for follow in following:
                    out_file.write("%s\n" % (follow))
        self.logger.info('Done syncing data with Twitter')

    def follow_user(self, user_id, _follow=False):
        '''
        Allows the user to follow the user specified in the ID parameter.
        Params: int
            The ID of the user to follow.
        Returns: None
        '''
        try:
            self.TWITTER_CONNECTION.friendships.create(user_id=user_id, follow=_follow)
            time.sleep(int(self.BOT_CONFIG['WAIT_TIME']))
            subquery = self.username_lookup(user_id)
            for user in subquery:
                if not user['protected']:
                    self.logger.info("followed @%s [id: %s]" % (user["screen_name"], user["id"]))
                else:
                    self.logger.info("User @%s Protected and will not follow" % user["screen_name"])
        except Exception as api_error:
            self.logger.error("Error: %s" % str(api_error))

    def unfollow_user(self, user_id):
        '''
        Allows the user to unfollow the user specified in the ID parameter.
        Params: int
            The ID of the user to follow.
        Returns: None
        '''
        try:
            self.TWITTER_CONNECTION.friendships.destroy(user_id=user_id)
            time.sleep(int(self.BOT_CONFIG['WAIT_TIME']))
            subquery = self.username_lookup(user_id)
            for user in subquery:
                self.logger.info("Unfollowed @%s [id: %s]" % (user["screen_name"], user["id"]))
        except Exception as api_error:
            self.logger.error("Error: %s" % str(api_error))

    def username_lookup(self, ids):
        """
        Find username by id
        Params: int
            user id
        Return: dict
            Dict with Users information
        """
        return self.TWITTER_CONNECTION.users.lookup(user_id=ids)
    # ----------------------------------
    def get_do_not_follow_list(self):
        """
            Returns the set of users the bot has already followed in the past.
        """
        dnf_list = []
        with open(self.BOT_CONFIG["ALREADY_FOLLOWED_FILE"], "r") as in_file:
            for line in in_file:
                dnf_list.append(int(line))
        return set(dnf_list)

    def get_followers_list(self):
        """
            Returns the set of users that are currently following the user.
        """
        followers_list = []
        with open(self.BOT_CONFIG["FOLLOWERS_FILE"], "r") as in_file:
            for line in in_file:
                followers_list.append(int(line))
        return set(followers_list)

    def get_follows_list(self):
        """
            Returns the set of users that the user is currently following.
        """
        follows_list = []
        with open(self.BOT_CONFIG["FOLLOWS_FILE"], "r") as in_file:
            for line in in_file:
                follows_list.append(int(line))
        return set(follows_list)

    def get_all_nonfollowers(self, auto_sync=False):
        """
        find everyone who hasn't followed you back.
        """
        if auto_sync:
            self.sync_follows

        following = self.get_follows_list()
        followers = self.get_followers_list()

        not_following_back = list(following - followers)
        non_followers = []
        for n in range(0, len(not_following_back), 99):
            ids = not_following_back[n: n + 99]
            subquery = self.username_lookup(ids)
            for user in subquery:
                non_followers.append("[%s] @%s [id: %s]" % (
                    "*" if user["verified"] else " ", user["screen_name"], user["id"]))

        with open(self.BOT_CONFIG["NON_FOLLOWERS_FILE"], 'w') as out_file:
            for val in non_followers:
                out_file.write(str(val) + '\n')
    # ----------------------------------
    def search_tweets(self, phrase, count=100, result_type="recent"):
        """
        Returns a list of tweets matching a phrase (hashtag, word, etc.).
        """
        return self.TWITTER_CONNECTION.search.tweets(q=phrase, result_type=result_type, count=count)
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
                time.sleep(int(self.BOT_CONFIG['WAIT_TIME']))
                result = self.TWITTER_CONNECTION.favorites.create(_id=tweet["id"])
                self.logger.info("Favourite: %s" % (result["text"].encode("utf-8")))
            # when you have already favorited a tweet, this error is thrown
            except Exception as api_error:
                # quit on rate limit errors
                self.logger.error('%s' % str(api_error))

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
                time.sleep(int(self.BOT_CONFIG['WAIT_TIME']))
                result = self.TWITTER_CONNECTION.statuses.retweet(id=tweet["id"])
                self.logger.info("Retweeted: %s" % (result["text"].encode("utf-8")))
            # when you have already retweeted a tweet, this error is thrown
            except Exception as api_error:
                # quit on rate limit errors
                self.logger.error("Error: %s" % (str(api_error)))

    def auto_follow_by_hashtag(self, phrase, count=100, auto_sync=False,result_type="recent"):
        """
            Follows anyone who tweets about a phrase (hashtag, word, etc.).
        """
        if auto_sync:
            self.sync_follows
        result = self.search_tweets(phrase, count, result_type)
        following = self.get_follows_list()
        for tweet in result["statuses"]:
            try:
                if (tweet["user"]["screen_name"] != self.BOT_CONFIG["TWITTER_HANDLE"] and
                        tweet["user"]["id"] not in following):
                    self.follow_user(tweet["user"]["id"])
                    following.update(set([tweet["user"]["id"]]))
            except Exception as api_error:
                # quit on rate limit errors
                self.logger.error("Error: %s" % (str(api_error)))

    def auto_follow_followers(self, count=None, auto_sync=False):
        """
            Follows back everyone who's followed you.
        """
        if auto_sync:
            self.sync_follows
        following = self.get_follows_list()
        followers = self.get_followers_list()

        not_following_back = followers - following
        not_following_back = list(not_following_back)[:count]

        for user_id in not_following_back:
            followed = self.follow_user(user_id, True)

    def auto_follow_followers_of_user(self, user_twitter_handle, count=100):
        """
            Follows the followers of a specified user.
        """
        followers_of_user = set(self.TWITTER_CONNECTION.followers.ids(
            screen_name=user_twitter_handle)["ids"][:count])

        for user_id in followers_of_user:
            self.follow_user(user_id, True)

    def auto_unfollow_nonfollowers(self, count=None, auto_sync=False):
        """
            Unfollows everyone who hasn't followed you back.
        """
        if auto_sync:
            self.sync_follows
        following = self.get_follows_list()
        followers = self.get_followers_list()

        not_following_back = following - followers
        not_following_back = list(not_following_back)[:count]
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
        muted = set(self.TWITTER_CONNECTION.mutes.users.ids(
            screen_name=self.BOT_CONFIG["TWITTER_HANDLE"])["ids"])

        not_muted = following - muted

        for user_id in not_muted:
            if user_id not in self.BOT_CONFIG["USERS_KEEP_UNMUTED"]:
                self.TWITTER_CONNECTION.mutes.users.create(user_id=user_id)
                self.logger.info("Muted %d" % (user_id))

    def auto_unmute(self):
        """
            Unmutes everyone that you have muted.
        """
        muted = set(self.TWITTER_CONNECTION.mutes.users.ids(
            screen_name=self.BOT_CONFIG["TWITTER_HANDLE"])["ids"])

        for user_id in muted:
            if user_id not in self.BOT_CONFIG["USERS_KEEP_MUTED"]:
                self.TWITTER_CONNECTION.mutes.users.destroy(user_id=user_id)
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
            self.logger.exception('Failed to parse list of users, will read from file')
            with open(self.BOT_CONFIG['NON_FOLLOWERS_FILE']) as in_file:
                unfollow_users = [l.strip() for l in in_file.readlines() if l.strip()]

        for user_id in unfollow_users:
            self.unfollow_user(user_id)
    # ----------------------------------
    def send_tweet(self, message):
        """
            Posts a tweet.
        """
        return self.TWITTER_CONNECTION.statuses.update(status=message)

    def auto_add_to_list(self, phrase, list_slug, count=100, result_type="recent"):
        """
            Add users to list slug that are tweeting phrase.
        """
        result = self.search_tweets(phrase, count, result_type)
        for tweet in result["statuses"]:
            try:
                if tweet["user"]["screen_name"] == self.BOT_CONFIG["TWITTER_HANDLE"]:
                    continue
                result = self.TWITTER_CONNECTION.lists.members.create(
                    owner_screen_name=self.BOT_CONFIG["TWITTER_HANDLE"],
                    slug=list_slug, screen_name=tweet["user"]["screen_name"])
                self.logger.info("User %s added to the list %s" % (
                    tweet["user"]["screen_name"], list_slug))
            except Exception as api_error:
                self.logger.error('%s' % str(api_error))


