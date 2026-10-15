"""Talks to EA's unofficial Pro Clubs API.

EA sits behind Akamai. A request without browser-like headers gets HTTP 403.
The header set below was confirmed working in testing.

Nothing here raises on a bad response. Every call returns an ApiResult so the
collector can log the failure and carry on.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

BASE_URL = "https://proclubs.ea.com/api/fc"

BROWSER_HEADERS = {
    "accept": "application/json",
    "accept-language": "en-US,en;q=0.9",
    "sec-ch-ua": '"Chromium";v="126", "Not-A.Brand";v="24", "Google Chrome";v="126"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "referer": "https://proclubs.ea.com/",
    "x-requested-with": "XMLHttpRequest",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
}


@dataclass
class ApiResult:
    url: str
    status: int
    body_text: str
    data: Any | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == 200 and self.data is not None


class EaClient:
    def __init__(self, timeout: int = 30, max_retries: int = 4) -> None:
        self.timeout = timeout
        self.max_retries = max_retries

    def get(self, path: str, params: dict[str, Any]) -> ApiResult:
        url = f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}"
        last: ApiResult | None = None

        for attempt in range(self.max_retries):
            if attempt:
                time.sleep(min(2 ** attempt, 30))
            last = self._get_once(url)
            if last.ok:
                return last
            # 4xx other than 403/429 means we asked for something wrong.
            # Retrying will not help.
            if 400 <= last.status < 500 and last.status not in (403, 429):
                return last

        return last if last else ApiResult(url, 0, "", None, "no attempt made")

    def _get_once(self, url: str) -> ApiResult:
        request = urllib.request.Request(url, headers=BROWSER_HEADERS)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status = response.status
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return ApiResult(url, exc.code, body, None, f"HTTP {exc.code}")
        except Exception as exc:  # network down, DNS, timeout
            return ApiResult(url, 0, "", None, f"{type(exc).__name__}: {exc}")

        try:
            return ApiResult(url, status, body, json.loads(body))
        except json.JSONDecodeError:
            # EA returns plain text for bad params, e.g. "Invalid query parameter".
            return ApiResult(url, status, body, None, "response was not JSON")

    # Convenience wrappers -------------------------------------------------

    def club_matches(self, platform: str, club_id: str, match_type: str,
                     max_result_count: int) -> ApiResult:
        return self.get("/clubs/matches", {
            "platform": platform,
            "clubIds": club_id,
            "matchType": match_type,
            "maxResultCount": max_result_count,
        })

    def club_overall_stats(self, platform: str, club_id: str) -> ApiResult:
        return self.get("/clubs/overallStats", {
            "platform": platform,
            "clubIds": club_id,
        })

    def club_info(self, platform: str, club_id: str) -> ApiResult:
        return self.get("/clubs/info", {"platform": platform, "clubIds": club_id})

    def members_stats(self, platform: str, club_id: str) -> ApiResult:
        return self.get("/members/stats", {"platform": platform, "clubId": club_id})
