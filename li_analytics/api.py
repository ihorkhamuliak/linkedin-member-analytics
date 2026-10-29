"""LinkedIn Community Management API client for one member's own analytics.

Tokens live in files inside the state directory (created with 0600 permissions):
  token         access token (60 days)
  refresh       refresh token (about 365 days)
  expiry.json   {"access_until": ..., "refresh_until": ...}, written by refresh()
  calls.json    requests made today, so a run never goes over the daily limit
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

API = "https://api.linkedin.com/rest"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
POST_ANALYTICS = "memberCreatorPostAnalytics"   # r_member_postAnalytics
FOLLOWERS = "memberFollowersCount"              # r_member_profileAnalytics

METRICS = [
    ("IMPRESSION", "impressions"), ("MEMBERS_REACHED", "members_reached"), ("REACTION", "reactions"),
    ("COMMENT", "comments"), ("RESHARE", "reshares"), ("POST_SAVE", "saves"), ("POST_SEND", "sends"),
    ("LINK_CLICKS", "link_clicks"), ("FOLLOWER_GAINED_FROM_CONTENT", "followers_from_post"),
    ("PROFILE_VIEW_FROM_CONTENT", "profile_views_from_post"),
]
# Documented for both finders, but q=me returns 500 for these two on any date range (checked Oct 2026).
# They work per post (q=entity), so weekly totals skip them and use memberFollowersCount instead.
POST_ONLY = {"FOLLOWER_GAINED_FROM_CONTENT", "PROFILE_VIEW_FROM_CONTENT"}


class Budget(Exception):
    """Daily request cap reached. Not an error: the next run continues."""


class ApiError(Exception):
    pass


def date_range(start: date, end: date) -> str:
    """Rest.li dateRange, start inclusive, end exclusive."""
    return (f"(start:(day:{start.day},month:{start.month},year:{start.year}),"
            f"end:(day:{end.day},month:{end.month},year:{end.year}))")


class Client:
    def __init__(self, state_dir, client_id=None, client_secret=None, cap=90,
                 versions=("202610", "202609", "202608"), opener=urllib.request.urlopen,
                 sleep=time.sleep, today=date.today):
        self.dir = Path(state_dir)
        self.client_id, self.client_secret = client_id, client_secret
        self.cap, self.versions = cap, list(versions)
        self.open, self.sleep, self.today = opener, sleep, today

    def _read(self, name):
        return (self.dir / name).read_text(encoding="utf-8").strip()

    def _write(self, name, text):
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / name
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)

    def _count_call(self):
        day = self.today().isoformat()
        try:
            used = json.loads(self._read("calls.json"))
        except (OSError, ValueError):
            used = {}
        if used.get(day, 0) >= self.cap:
            raise Budget(f"daily cap of {self.cap} requests reached")
        self._write("calls.json", json.dumps({day: used.get(day, 0) + 1}))

    def get(self, resource, params, field="count"):
        """One GET. Returns the field of the first element, None when LinkedIn sends no elements
        (written as an empty cell, never as 0), or all elements when field is None."""
        url = f"{API}/{resource}?" + "&".join(f"{k}={v}" for k, v in params.items())
        for ver in self.versions:
            for attempt in (1, 2):  # a 500 is sometimes one-off: one retry, then it is a real error
                self._count_call()
                req = urllib.request.Request(url, headers={
                    "Authorization": "Bearer " + self._read("token"),
                    "LinkedIn-Version": ver, "X-Restli-Protocol-Version": "2.0.0"})
                try:
                    with self.open(req, timeout=30) as r:
                        elements = json.load(r).get("elements", [])
                except urllib.error.HTTPError as e:
                    body = e.read().decode(errors="replace")[:300]
                    if e.code == 426:
                        break  # version no longer served: go straight to an older one
                    if e.code >= 500 and attempt == 1:
                        self.sleep(5)
                        continue
                    raise ApiError(f"{e.code} {params.get('queryType', resource)}: {body}") from None
                if field is None:
                    return elements
                return elements[0].get(field) if elements else None
        raise ApiError(f"no API version answered {resource} (tried {', '.join(self.versions)})")

    def refresh(self):
        """Exchange the refresh token for a new access token and record both expiry dates."""
        body = urllib.parse.urlencode({
            "grant_type": "refresh_token", "refresh_token": self._read("refresh"),
            "client_id": self.client_id, "client_secret": self.client_secret}).encode()
        try:
            with self.open(urllib.request.Request(TOKEN_URL, data=body), timeout=30) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:
            raise ApiError(f"refresh {e.code}: {e.read().decode(errors='replace')[:300]}") from None
        now = datetime.combine(self.today(), datetime.min.time())
        self._write("token", data["access_token"])
        if data.get("refresh_token"):
            self._write("refresh", data["refresh_token"])
        expiry = {"access_until": (now + timedelta(seconds=data["expires_in"])).date().isoformat(),
                  "refresh_until": (now + timedelta(seconds=data["refresh_token_expires_in"])).date().isoformat()
                  if data.get("refresh_token_expires_in") else None}
        self._write("expiry.json", json.dumps(expiry))
        return expiry

    def ensure_fresh(self, days=7):
        """Refresh the access token when it ends in less than `days`. Without expiry.json (before the
        first refresh) the current token is used as is."""
        try:
            until = date.fromisoformat(json.loads(self._read("expiry.json"))["access_until"])
        except (OSError, ValueError, KeyError):
            return None
        if until - self.today() < timedelta(days=days):
            return self.refresh()
        return None
