"""Kaggle APIソース: コンペのnotebooks/kernelsのURLを取得する.

~/.kaggle/kaggle.json が必要。なければスキップ。
"""

from __future__ import annotations

import json
import logging
import os
from typing import List
from urllib.request import Request, urlopen
from urllib.error import URLError
import base64

logger = logging.getLogger(__name__)

KAGGLE_API_BASE = "https://www.kaggle.com/api/v1"
KAGGLE_CREDS_PATH = os.path.expanduser("~/.kaggle/kaggle.json")


class KaggleSource:
    """Kaggle APIからnotebooks/kernelsのURLを発見する。"""

    def __init__(self):
        self._creds = self._load_credentials()

    def _load_credentials(self) -> dict | None:
        """~/.kaggle/kaggle.json から認証情報を読み込む。"""
        if not os.path.exists(KAGGLE_CREDS_PATH):
            return None
        try:
            with open(KAGGLE_CREDS_PATH, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load Kaggle credentials: %s", e)
            return None

    def _make_auth_header(self) -> str | None:
        """Basic認証ヘッダーを生成する。"""
        if not self._creds:
            return None
        username = self._creds.get("username", "")
        key = self._creds.get("key", "")
        token = base64.b64encode(f"{username}:{key}".encode()).decode()
        return f"Basic {token}"

    def list_urls(self, limit: int = 20) -> List[str]:
        """Kaggle APIからnotebook/kernelのURLを取得する。"""
        if not self._creds:
            logger.info(
                "Kaggle credentials not found at %s. "
                "Skipping Kaggle source. "
                "Get your API token from https://www.kaggle.com/settings",
                KAGGLE_CREDS_PATH,
            )
            return []

        urls: list[str] = []

        # 1. 人気のnotebooks（most votes）を取得
        try:
            kernels = self._api_get(
                "/kernels/list",
                params={
                    "sortBy": "voteCount",
                    "pageSize": str(min(limit, 20)),
                    "language": "python",
                },
            )
            for k in kernels:
                ref = k.get("ref", "")
                if ref:
                    url = f"https://www.kaggle.com/code/{ref}"
                    urls.append(url)
        except Exception as e:
            logger.warning("Failed to list Kaggle kernels: %s", e)

        return urls[:limit]

    def _api_get(self, endpoint: str, params: dict = None) -> list:
        """Kaggle APIにGETリクエストを送る。"""
        url = KAGGLE_API_BASE + endpoint
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{url}?{query}"

        auth = self._make_auth_header()
        headers = {"User-Agent": "ae-harvest/0.1"}
        if auth:
            headers["Authorization"] = auth

        req = Request(url, headers=headers)
        try:
            with urlopen(req, timeout=15) as resp:
                data = resp.read().decode("utf-8")
                return json.loads(data)
        except (URLError, OSError, json.JSONDecodeError) as e:
            raise RuntimeError(f"Kaggle API request failed: {e}") from e
