"""Where rows go: CSV files (default, nothing to set up) or a Google Sheet (service account)."""
import csv
import json
import urllib.parse
import urllib.request
from pathlib import Path


class CsvStore:
    """weeks.csv and posts.csv in `out_dir`; posts to measure come from `posts_file`."""

    def __init__(self, out_dir, posts_file):
        self.dir, self.posts_file = Path(out_dir), Path(posts_file)

    def rows(self, name):
        path = self.dir / f"{name}.csv"
        if not path.exists():
            return []
        with path.open(newline="", encoding="utf-8") as f:
            return list(csv.reader(f))[1:]

    def append(self, name, head, rows):
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / f"{name}.csv"
        new = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(head)
            w.writerows(rows)

    def posts(self):
        with self.posts_file.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))


class SheetsStore:
    """Tabs `weeks` and `posts` (created with a header when missing); posts to measure come from tab
    `posts_input` with the same columns as posts.example.csv. Share the sheet with the service account."""

    SCOPE = "https://www.googleapis.com/auth/spreadsheets"

    def __init__(self, sheet_id, service_account_file, input_tab="posts_input"):
        from google.oauth2 import service_account          # optional dependency, only for this store
        from google.auth.transport.requests import Request
        creds = service_account.Credentials.from_service_account_file(service_account_file, scopes=[self.SCOPE])
        creds.refresh(Request())
        self.token, self.sheet, self.input_tab = creds.token, sheet_id, input_tab

    def _api(self, method, path, data=None):
        req = urllib.request.Request(
            f"https://sheets.googleapis.com/v4/spreadsheets/{self.sheet}{path}",
            data=json.dumps(data).encode() if data is not None else None, method=method,
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)

    def _values(self, tab):
        return self._api("GET", "/values/" + urllib.parse.quote(f"{tab}!A1:Z10000")).get("values", [])

    def _ensure(self, tab, head):
        titles = [s["properties"]["title"] for s in self._api("GET", "?fields=sheets.properties.title")["sheets"]]
        if tab not in titles:
            self._api("POST", ":batchUpdate", {"requests": [{"addSheet": {"properties": {"title": tab}}}]})
            self._api("PUT", "/values/" + urllib.parse.quote(f"{tab}!A1") + "?valueInputOption=RAW",
                      {"values": [head]})

    def rows(self, name):
        return self._values(name)[1:]

    def append(self, name, head, rows):
        self._ensure(name, head)
        self._api("POST", "/values/" + urllib.parse.quote(f"{name}!A1")
                  + ":append?valueInputOption=RAW&insertDataOption=INSERT_ROWS", {"values": rows})

    def posts(self):
        v = self._values(self.input_tab)
        return [dict(zip(v[0], r)) for r in v[1:]] if v else []
