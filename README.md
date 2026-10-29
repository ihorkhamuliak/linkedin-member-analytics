# linkedin-member-analytics

**English** · [Українська](README.uk.md)

Analytics for your **own personal LinkedIn profile**, pulled every day through the official API:
weekly totals and a snapshot of every post after its first day and after a week, written to CSV or Google Sheets.

Many people (me included, until recently) believe LinkedIn gives no API access to personal profile statistics.
It does: the Community Management API has member analytics since 2025. Getting access takes a review,
and a few things work differently from the documentation. Both are written down below.

## What it does

| Command | Result |
|---|---|
| `run` | posts first, then weeks; what a daily cron calls |
| `posts` | for every post in your list: one row after 2 days and one after 7 days |
| `weeks` | one row per Monday-Sunday week, backfills from `LI_SINCE` |
| `refresh` | new access token from the refresh token, records both expiry dates |
| `probe` | one request: impressions for the last 7 days |

Per post: impressions, members reached, reactions, comments, reshares, saves, sends, link clicks,
**profile views from the post, followers from the post**. Optional tags (`rubric`, `format`, `hook`) are copied
from your post list, so you can compare medians by type of post.

Per week: the same totals (minus the two per-post-only metrics, see below), new followers, total followers.

## How I checked the numbers before trusting them

A new data source is wrong until it matches a number you already know.

- My dashboard screenshot showed **938 impressions** for 14 days, taken at 13:35 on the last day.
  The API for the same 13 full days gave **908**; the last day was partial in the screenshot (~30 by then). Same number.
- The dashboard showed **-54%** against the previous 14 days. The API shows the same drop.
- An old post that went viral (about 19 000 impressions by hand) shows up as a 21 000 week in the API.

## Things that differ from the docs (October 2026)

- `FOLLOWER_GAINED_FROM_CONTENT` and `PROFILE_VIEW_FROM_CONTENT` are documented for both finders,
  but `q=me` returns **500 on any date range**. Per post (`q=entity`) they work. Weekly rows use
  `memberFollowersCount` for followers instead.
- The Token Generator gives a **refresh token** too (about 365 days), so the access token can renew itself.
- Access and refresh tokens look the same (both start with `AQ`, same length). Copy the right one:
  a refresh token used as an access token gives `401 INVALID_ACCESS_TOKEN` everywhere.
- No endpoint for total profile views, search appearances, out-of-network share or audience demographics.
  Those stay in a monthly screenshot.
- `dateRange` end is exclusive. The dashboard's "last N days" includes today, so the API is slightly higher
  for the same label once the day is complete.

## Getting API access (what worked without a registered company)

1. A **LinkedIn Company Page** that you admin (a one-person practice page is enough).
2. A **business email on your own domain**. Free option: Cloudflare Email Routing forwarding to your inbox.
3. A **privacy policy page** on your site.
4. A **new app** in the Developer Portal with **only** the Community Management API. With any other product
   added, the request button stays grey. No "Linked" or "In" in the app name.
5. App **Settings → verify** with your Company Page.
6. **Products → Community Management API → Request access** and fill the access form. Describe the real use:
   read-only analytics of your own posts, one member, no data of other members.
7. Wait. Status shows "Access Form Review"; mine was approved after **14 business days** (Development Tier).
8. **Auth** tab: add `https://www.linkedin.com/developers/tools/oauth/redirect` as a redirect URL.
   Then the **OAuth Token Generator**: pick your app, `r_member_postAnalytics` and `r_member_profileAnalytics`,
   copy the access token and the refresh token.

Development Tier limits: 100 requests per member per day. The tool counts its own requests and stops at
`LI_DAILY_CAP` (90 by default); the next run continues where it stopped.

## Setup

```bash
pip install -r requirements.txt        # only needed for OUTPUT=sheets
cp .env.example .env                   # client id and secret from the Auth tab
mkdir -p state && umask 077
# paste the tokens without leaving them in your shell history or chat:
read -r T && printf %s "$T" > state/token     # access token
read -r T && printf %s "$T" > state/refresh   # refresh token
python -m li_analytics refresh         # proves refresh works, writes the expiry dates
python -m li_analytics probe
cp posts.example.csv posts.csv         # your posts: id, posted_on, post_url, optional tags
python -m li_analytics run
```

`post_url` needs the `share` or `ugcPost` URN, the one the publishing API returns
(`https://www.linkedin.com/feed/update/urn:li:share:...`). The `urn:li:activity` link you copy from the
browser is not accepted by the analytics endpoint.

Daily cron, plus a monitor that alerts when `state/last_ok` is older than 3 days
(it is written only after a fully successful `run`):

```cron
30 6 * * * cd /path/to/linkedin-member-analytics && python3 -m li_analytics run >> run.log 2>&1
```

## Design choices

- **An empty answer is an empty cell, never 0.** A fake zero looks like a bad week and hides a broken call.
- **One retry on 500, then a loud error.** A retired API version (426) goes straight to an older one.
- **Daily cap is a pause, not a failure.** Rows fetched before the cap are saved.
- **Snapshots wait until their window has closed**, so a 7-day row always means 7 full days.
- Tokens are files with `0600` permissions; nothing secret goes to logs or output.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

The tests use a fake LinkedIn and made-up data. Each of them was checked against a deliberately broken copy
of the code (empty answer turned into 0, retry on a retired version, snapshot before its window closes,
weekly request of per-post-only metrics): every break turns a test red.

## License

MIT
