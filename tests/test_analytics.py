"""All data here is made up. The fake opener plays LinkedIn: it answers by queryType / resource."""
import io
import json
import os
import urllib.error
import urllib.parse
from datetime import date

import pytest

from li_analytics import collect
from li_analytics.api import POST_ONLY, ApiError, Client

TODAY = date(2026, 11, 4)  # a Wednesday


class Fake:
    def __init__(self, answers=None, errors=None):
        self.answers = answers or {}   # key -> elements list
        self.errors = errors or {}     # key -> list of HTTP codes to raise before answering
        self.calls = []

    @staticmethod
    def key(url):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        return q.get("queryType") or urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1] + ":" + q.get("q", "")

    def __call__(self, req, timeout=None):
        if req.full_url.startswith("https://www.linkedin.com/oauth"):
            return io.BytesIO(json.dumps({"access_token": "new-access", "expires_in": 60 * 86400,
                                          "refresh_token": "new-refresh",
                                          "refresh_token_expires_in": 365 * 86400}).encode())
        k = self.key(req.full_url)
        self.calls.append((k, req.headers.get("Linkedin-version")))
        if self.errors.get(k):
            code = self.errors[k].pop(0)
            raise urllib.error.HTTPError(req.full_url, code, "err", {}, io.BytesIO(b'{"status":%d}' % code))
        return io.BytesIO(json.dumps({"elements": self.answers.get(k, [{"count": 7}])}).encode())


def client(tmp_path, fake, cap=90):
    (tmp_path / "token").write_text("fake-access")
    (tmp_path / "refresh").write_text("fake-refresh")
    return Client(tmp_path, "client-id", "client-secret", cap=cap, opener=fake, sleep=lambda s: None,
                  today=lambda: TODAY)


def test_empty_answer_is_an_empty_cell_not_zero(tmp_path):
    fake = Fake({"POST_SAVE": []})
    rows, _ = collect.weeks(client(tmp_path, fake), date(2026, 10, 26), set(), TODAY)
    saves = collect.WEEKS_HEAD.index("saves")
    assert rows[0][saves] == "" and rows[0][collect.WEEKS_HEAD.index("impressions")] == 7


def test_one_500_is_retried_two_in_a_row_fail(tmp_path):
    fake = Fake(errors={"IMPRESSION": [500]})
    assert client(tmp_path, fake).get("memberCreatorPostAnalytics", {"q": "me", "queryType": "IMPRESSION"}) == 7
    fake = Fake(errors={"IMPRESSION": [500, 500]})
    with pytest.raises(ApiError, match="500"):
        client(tmp_path, fake).get("memberCreatorPostAnalytics", {"q": "me", "queryType": "IMPRESSION"})


def test_retired_version_goes_straight_to_older(tmp_path):
    fake = Fake(errors={"IMPRESSION": [426]})
    assert client(tmp_path, fake).get("memberCreatorPostAnalytics", {"q": "me", "queryType": "IMPRESSION"}) == 7
    assert [v for _, v in fake.calls] == ["202610", "202609"]   # no second try on the retired version
    fake = Fake(errors={"IMPRESSION": [426, 426, 426]})
    with pytest.raises(ApiError, match="no API version"):
        client(tmp_path, fake).get("memberCreatorPostAnalytics", {"q": "me", "queryType": "IMPRESSION"})


def test_daily_cap_keeps_fetched_rows_and_pauses(tmp_path):
    per_week = len(collect.WEEK_METRICS) + 1          # metrics + daily followers
    c = client(tmp_path, Fake(), cap=per_week + 3)     # one full week fits, the next does not
    rows, paused = collect.weeks(c, date(2026, 10, 19), set(), TODAY)
    assert paused and len(rows) == 1 and rows[0][0] == "2026-10-19"


def test_weeks_skip_stored_and_never_ask_post_only_metrics(tmp_path):
    fake = Fake({"memberFollowersCount:dateRange": [{"memberFollowersCount": 2}, {"memberFollowersCount": 3}],
                 "memberFollowersCount:me": [{"memberFollowersCount": 500}]})
    rows, paused = collect.weeks(client(tmp_path, fake), date(2026, 10, 19), {"2026-10-19"}, TODAY)
    assert not paused and [r[0] for r in rows] == ["2026-10-26"]   # current week (from 2.11) not complete
    asked = {k for k, _ in fake.calls}
    assert not asked & POST_ONLY
    assert rows[0][-3:] == [5, 500, "2026-11-04"]                   # new followers summed, total on last week


def test_followers_total_only_on_the_week_that_just_ended(tmp_path):
    fake = Fake({"memberFollowersCount:me": [{"memberFollowersCount": 500}]})
    rows, _ = collect.weeks(client(tmp_path, fake), date(2026, 10, 19), set(), TODAY)
    total = collect.WEEKS_HEAD.index("followers_total")
    assert [r[total] for r in rows] == ["", 500]   # "now" is not the total of an older week


POST = {"id": "p1", "posted_on": "2026-10-30", "post_url": "https://www.linkedin.com/feed/update/urn:li:share:111",
        "rubric": "3-mistakes", "format": "screenshot", "hook": "story"}


def test_snapshot_waits_for_its_window_and_is_taken_once(tmp_path):
    c = client(tmp_path, Fake())
    rows, _ = collect.snapshots(c, [POST], set(), date(2026, 11, 1))          # day 2 window closes on 1.11
    assert [r[collect.POSTS_HEAD.index("days")] for r in rows] == [2]
    rows, _ = collect.snapshots(c, [POST], {("p1", "2")}, date(2026, 11, 5))  # 7-day window still open
    assert rows == []
    rows, _ = collect.snapshots(c, [POST], {("p1", "2")}, date(2026, 11, 6))
    assert [r[collect.POSTS_HEAD.index("days")] for r in rows] == [7]
    assert rows[0][3:6] == ["3-mistakes", "screenshot", "story"]


def test_posts_without_url_are_skipped_and_post_only_metrics_asked_per_post(tmp_path):
    fake = Fake()
    rows, _ = collect.snapshots(client(tmp_path, fake), [{**POST, "post_url": ""}, POST], set(), TODAY)
    assert len(rows) == 1
    assert POST_ONLY <= {k for k, _ in fake.calls}


def test_entity_encoding():
    assert collect.entity("https://www.linkedin.com/feed/update/urn:li:share:123/") == "(share:urn%3Ali%3Ashare%3A123)"
    assert collect.entity("urn:li:ugcPost:9") == "(ugcPost:urn%3Ali%3AugcPost%3A9)"
    with pytest.raises(ValueError):
        collect.entity("https://www.linkedin.com/feed/update/urn:li:activity:5/")  # activity URNs are not accepted


def test_refresh_writes_new_tokens_and_expiry(tmp_path):
    c = client(tmp_path, Fake())
    e = c.refresh()
    assert e == {"access_until": "2027-01-03", "refresh_until": "2027-11-04"}
    assert (tmp_path / "token").read_text() == "new-access" and (tmp_path / "refresh").read_text() == "new-refresh"
    if os.name != "nt":
        assert oct((tmp_path / "token").stat().st_mode)[-3:] == "600"


def test_ensure_fresh_refreshes_only_close_to_expiry(tmp_path):
    c = client(tmp_path, Fake())
    (tmp_path / "expiry.json").write_text(json.dumps({"access_until": "2026-12-20"}))
    assert c.ensure_fresh() is None
    (tmp_path / "expiry.json").write_text(json.dumps({"access_until": "2026-11-08"}))
    assert c.ensure_fresh()["access_until"] == "2027-01-03"
