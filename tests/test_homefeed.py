# -*- coding: utf-8 -*-
"""Unit tests for HomeFeed enums across 5 platforms."""

import pytest


class TestXhsFeedType:
    def test_feed_type_enum(self):
        from media_platform.xhs.field import FeedType
        assert FeedType.RECOMMEND.value == "homefeed_recommend"
        assert FeedType.FASION.value == "homefeed.fashion_v3"
        assert FeedType.FOOD.value == "homefeed.food_v3"
        assert FeedType.COSMETICS.value == "homefeed.cosmetics_v3"
        assert FeedType.MOVIE.value == "homefeed.movie_and_tv_v3"
        assert FeedType.CAREER.value == "homefeed.career_v3"
        assert FeedType.EMOTION.value == "homefeed.love_v3"
        assert FeedType.HOURSE.value == "homefeed.household_product_v3"
        assert FeedType.GAME.value == "homefeed.gaming_v3"
        assert FeedType.TRAVEL.value == "homefeed.travel_v3"
        assert FeedType.FITNESS.value == "homefeed.fitness_v3"

    def test_all_categories(self):
        from media_platform.xhs.field import FeedType
        assert len(list(FeedType)) == 11


class TestDouyinFeedType:
    def test_feed_type_enum(self):
        from media_platform.douyin.field import FeedType
        assert FeedType.RECOMMEND.value == "0"
        assert FeedType.HOT.value == "1"
        assert FeedType.LOCAL.value == "2"

    def test_all_categories(self):
        from media_platform.douyin.field import FeedType
        assert len(list(FeedType)) == 3


class TestBilibiliFeedType:
    def test_feed_type_enum(self):
        from media_platform.bilibili.field import FeedType
        assert FeedType.POPULAR.value == "popular"
        assert FeedType.RECOMMEND.value == "recommend"

    def test_all_categories(self):
        from media_platform.bilibili.field import FeedType
        assert len(list(FeedType)) == 2


class TestWeiboFeedType:
    def test_feed_type_enum(self):
        from media_platform.weibo.field import FeedType
        assert FeedType.HOT.value == "102803"
        assert FeedType.RECOMMEND.value == "102803_ctg1_600059"

    def test_all_categories(self):
        from media_platform.weibo.field import FeedType
        assert len(list(FeedType)) == 2


class TestKuaishouFeedType:
    def test_feed_type_enum(self):
        from media_platform.kuaishou.field import FeedType
        assert FeedType.RECOMMEND.value == "recommend"
        assert FeedType.HOT.value == "hot"
        assert FeedType.FOLLOW.value == "follow"

    def test_all_categories(self):
        from media_platform.kuaishou.field import FeedType
        assert len(list(FeedType)) == 3


class TestAllPlatformsHaveFeedType:
    """Test that all 5 platforms have FeedType enum defined."""

    def test_xhs_has_feed_type(self):
        from media_platform.xhs.field import FeedType
        assert FeedType is not None

    def test_douyin_has_feed_type(self):
        from media_platform.douyin.field import FeedType
        assert FeedType is not None

    def test_bilibili_has_feed_type(self):
        from media_platform.bilibili.field import FeedType
        assert FeedType is not None

    def test_weibo_has_feed_type(self):
        from media_platform.weibo.field import FeedType
        assert FeedType is not None

    def test_kuaishou_has_feed_type(self):
        from media_platform.kuaishou.field import FeedType
        assert FeedType is not None
