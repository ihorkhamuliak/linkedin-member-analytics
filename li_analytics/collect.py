"""What to fetch and how to turn it into rows. No I/O here except through the client."""
import urllib.parse
from datetime import date, timedelta

from .api import FOLLOWERS, METRICS, POST_ANALYTICS, POST_ONLY, Budget, date_range

WEEK_METRICS = [m for m in METRICS if m[0] not in POST_ONLY]
WEEKS_HEAD = (["week_start", "week_end"] + [m[1] for m in WEEK_METRICS]
              + ["new_followers", "followers_total", "fetched_on"])
TAGS = ["rubric", "format", "hook"]
POSTS_HEAD = ["id", "posted_on", "post_url"] + TAGS + [m[1] for m in METRICS] + ["days", "fetched_on"]
# 2 = publication day + the next one (the API counts calendar days, so a post at 3 pm gets ~33 hours), 7 = one week
SNAPSHOTS = (2, 7)


def _metrics(client, base, start, end, which):
    out = []
    for name, _ in which:
        v = client.get(POST_ANALYTICS, {**base, "queryType": name, "aggregation": "TOTAL",
                                        "dateRange": date_range(start, end)})
        out.append("" if v is None else v)
    return out


def entity(post_url: str) -> str:
    """https://www.linkedin.com/feed/update/urn:li:share:123 -> (share:urn%3Ali%3Ashare%3A123)"""
    urn = post_url.rstrip("/").rsplit("/", 1)[-1]
    kind = urn.split(":")[2]  # share | ugcPost
    if kind not in ("share", "ugcPost"):
        raise ValueError(f"post analytics accept share or ugcPost URNs, got {urn}")
    return f"({kind}:{urllib.parse.quote(urn, safe='')})"


def weeks(client, since: date, have: set, today: date):
    """Rows for full Monday-Sunday weeks from `since` up to last week, skipping weeks already stored.
    Returns (rows, paused). On the daily cap the rows fetched so far are kept and the rest waits."""
    start = since - timedelta(days=since.weekday())
    this_monday = today - timedelta(days=today.weekday())
    rows = []
    try:
        while start < this_monday:
            end = start + timedelta(days=7)
            if start.isoformat() not in have:
                days = client.get(FOLLOWERS, {"q": "dateRange", "dateRange": date_range(start, end)}, None)
                new = sum(d.get("memberFollowersCount", 0) for d in days) if days else ""
                # the total is "right now", so it only belongs to the week that just ended
                total = client.get(FOLLOWERS, {"q": "me"}, "memberFollowersCount") if end == this_monday else ""
                rows.append([start.isoformat(), (end - timedelta(days=1)).isoformat()]
                            + _metrics(client, {"q": "me"}, start, end, WEEK_METRICS)
                            + [new, "" if total is None else total, today.isoformat()])
            start = end
    except Budget:
        return rows, True
    return rows, False


def snapshots(client, posts, have: set, today: date):
    """Rows for every post whose 2-day or 7-day window has closed and is not stored yet.
    `posts`: dicts with id, posted_on (YYYY-MM-DD), post_url and optional rubric/format/hook.
    `have`: {(id, days)} already stored."""
    rows = []
    try:
        for p in posts:
            if not p.get("post_url") or not p.get("posted_on"):
                continue
            day = date.fromisoformat(p["posted_on"][:10])
            for n in SNAPSHOTS:
                end = day + timedelta(days=n)
                if (p["id"], str(n)) in have or today < end:  # stored, or the window is still open
                    continue
                rows.append([p["id"], day.isoformat(), p["post_url"]] + [p.get(t, "") for t in TAGS]
                            + _metrics(client, {"q": "entity", "entity": entity(p["post_url"])}, day, end, METRICS)
                            + [n, today.isoformat()])
    except Budget:
        return rows, True
    return rows, False
