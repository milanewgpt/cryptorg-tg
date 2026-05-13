"""
Bybit V5 REST client — read-only, для мониторинга позиций.
Auth: X-BAPI-API-KEY + X-BAPI-TIMESTAMP + X-BAPI-SIGN (HMAC SHA256).
"""
import hashlib
import hmac
import logging
import os
import time

import aiohttp

logger = logging.getLogger(__name__)

BYBIT_BASE = "https://api.bybit.com"
RECV_WINDOW = "5000"


class BybitClient:
    def __init__(self):
        self._api_key = os.getenv("BYBIT_API_KEY", "")
        self._api_secret = os.getenv("BYBIT_API_SECRET", "")
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    def _sign(self, timestamp: str, query_string: str) -> str:
        payload = timestamp + self._api_key + RECV_WINDOW + query_string
        return hmac.new(
            self._api_secret.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()

    async def _get(self, path: str, params: dict | None = None) -> dict:
        import urllib.parse
        query_string = urllib.parse.urlencode(params) if params else ""
        timestamp = str(int(time.time() * 1000))
        headers = {
            "X-BAPI-API-KEY": self._api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": RECV_WINDOW,
            "X-BAPI-SIGN": self._sign(timestamp, query_string),
        }
        url = f"{BYBIT_BASE}{path}?{query_string}" if query_string else f"{BYBIT_BASE}{path}"
        sess = await self._get_session()
        async with sess.get(url, headers=headers) as resp:
            text = await resp.text()
            try:
                import json as _json
                data = _json.loads(text)
            except Exception as e:
                logger.error("Bybit JSON parse error: %s | status=%s | body=%r", e, resp.status, text[:1000])
                raise
            if data.get("retCode") != 0:
                raise RuntimeError(f"Bybit {path}: {data.get('retMsg')} ({data.get('retCode')})")
            return data

    async def get_positions(self, symbol: str | None = None) -> list[dict]:
        """Get all open linear (USDT perp) positions, optionally filtered by symbol."""
        params: dict = {"category": "linear", "limit": "200"}
        if symbol:
            params["symbol"] = symbol
        else:
            params["settleCoin"] = "USDT"
        data = await self._get("/v5/position/list", params)
        return data.get("result", {}).get("list", [])
