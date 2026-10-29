"""python -m li_analytics {probe|refresh|weeks|posts|run}

Settings come from environment variables or a .env file in the working directory (see .env.example).
`run` is what a daily cron calls: posts first (fresh posts get the request budget first), then weeks.
Only a fully successful `run` writes state/last_ok, so a monitor can alert when that date gets old."""
import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from .api import POST_ANALYTICS, ApiError, Client, date_range
from .collect import POSTS_HEAD, WEEKS_HEAD, snapshots, weeks
from .store import CsvStore, SheetsStore


def load_env(path=".env"):
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def make_store():
    if os.environ.get("OUTPUT", "csv") == "sheets":
        return SheetsStore(os.environ["SHEET_ID"], os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"])
    return CsvStore(os.environ.get("CSV_DIR", "data"), os.environ.get("POSTS_FILE", "posts.csv"))


def do_weeks(client, store, since, today):
    have = {r[0] for r in store.rows("weeks") if r}
    rows, paused = weeks(client, since, have, today)
    if rows:
        store.append("weeks", WEEKS_HEAD, rows)
    print(f"weeks written: {len(rows)}" + (" (daily cap reached, the next run continues)" if paused else ""))


def do_posts(client, store, today):
    di = POSTS_HEAD.index("days")
    have = {(r[0], r[di]) for r in store.rows("posts") if len(r) > di}
    rows, paused = snapshots(client, store.posts(), have, today)
    if rows:
        store.append("posts", POSTS_HEAD, rows)
    print(f"post snapshots written: {len(rows)}" + (" (daily cap reached, the next run continues)" if paused else ""))


def main(argv=None):
    load_env()
    ap = argparse.ArgumentParser(prog="li_analytics")
    ap.add_argument("command", choices=["probe", "refresh", "weeks", "posts", "run"])
    ap.add_argument("--since", type=date.fromisoformat, help="first week to backfill (default: env LI_SINCE or 4 weeks ago)")
    a = ap.parse_args(argv)
    today = date.today()
    since = a.since or (date.fromisoformat(os.environ["LI_SINCE"]) if os.environ.get("LI_SINCE")
                        else today - timedelta(weeks=4))
    state = os.environ.get("LI_STATE_DIR", "state")
    client = Client(state, os.environ.get("LI_CLIENT_ID"), os.environ.get("LI_CLIENT_SECRET"),
                    cap=int(os.environ.get("LI_DAILY_CAP", "90")))
    try:
        if a.command == "refresh":
            e = client.refresh()
            print(f"access token until {e['access_until']}, refresh token until {e['refresh_until']}")
            return 0
        client.ensure_fresh()
        if a.command == "probe":
            v = client.get(POST_ANALYTICS, {"q": "me", "queryType": "IMPRESSION", "aggregation": "TOTAL",
                                            "dateRange": date_range(today - timedelta(days=7), today)})
            print(f"impressions, last 7 days: {v}")
            return 0
        store = make_store()
        if a.command in ("posts", "run"):
            do_posts(client, store, today)
        if a.command in ("weeks", "run"):
            do_weeks(client, store, since, today)
        if a.command == "run":
            Path(state, "last_ok").write_text(today.isoformat(), encoding="utf-8")
    except ApiError as e:
        print(f"LinkedIn API error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
