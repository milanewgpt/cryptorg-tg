"""
Cryptorg api3 client.

Auth: JWT cookie `yaronby`, obtained after web login + trading password.
Token lifetime: ~3 hours. Auto-refreshes on 401.
"""
import logging
import os
import re
import time

import aiohttp

logger = logging.getLogger(__name__)

WEB_BASE = "https://cryptorg.net"
API_BASE = "https://api3.cryptorg.net"
HEADERS = {
    "Origin": WEB_BASE,
    "Referer": f"{WEB_BASE}/en/futures",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0",
}


class CryptorgError(Exception):
    pass


JWT_CACHE_FILE = os.path.join(os.path.dirname(__file__), ".jwt_cache")


class CryptorgClient:
    def __init__(self):
        self._email = os.getenv("CRYPTORG_EMAIL", "")
        self._password = os.getenv("CRYPTORG_PASSWORD", "")
        self._trade_password = os.getenv("CRYPTORG_TRADE_PASSWORD", "")
        self._jwt: str = ""
        self._jwt_exp: float = 0.0
        self._session: aiohttp.ClientSession | None = None
        self._load_jwt_cache()

    def _load_jwt_cache(self):
        try:
            import json as _json
            with open(JWT_CACHE_FILE) as f:
                data = _json.load(f)
            self._jwt = data.get("jwt", "")
            self._jwt_exp = float(data.get("exp", 0))
            if self._is_token_valid():
                logger.info("Cryptorg: reusing cached JWT, expires at %s",
                            time.strftime("%H:%M:%S", time.localtime(self._jwt_exp)))
        except Exception:
            pass

    def _save_jwt_cache(self):
        try:
            import json as _json
            with open(JWT_CACHE_FILE, "w") as f:
                _json.dump({"jwt": self._jwt, "exp": self._jwt_exp}, f)
        except Exception as e:
            logger.warning("Failed to save JWT cache: %s", e)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    @staticmethod
    def _get_csrf(html: str) -> str:
        m = re.search(r'name="_csrf-frontend" value="([^"]+)"', html)
        if not m:
            raise CryptorgError("CSRF token not found")
        return m.group(1)

    def _is_token_valid(self) -> bool:
        # Refresh 5 minutes before expiry
        return bool(self._jwt) and time.time() < (self._jwt_exp - 300)

    def _auth_headers(self) -> dict:
        return {**HEADERS, "Cookie": f"yaronby={self._jwt}"}

    async def login(self):
        """
        Full login: email+password → trading password → extract yaronby JWT.
        """
        sess = await self._get_session()
        jar = aiohttp.CookieJar(unsafe=True)
        web_sess = aiohttp.ClientSession(cookie_jar=jar)

        try:
            # 1. Load login page
            resp = await web_sess.get(f"{WEB_BASE}/en/login")
            csrf = self._get_csrf(await resp.text())

            # 2. Submit credentials
            resp = await web_sess.post(
                f"{WEB_BASE}/en/login",
                data={
                    "_csrf-frontend": csrf,
                    "LoginForm[username]": self._email,
                    "LoginForm[password]": self._password,
                },
                allow_redirects=False,
            )

            loc = resp.headers.get("Location", "")
            body = await resp.text()
            if not loc:
                if "Too many" in body:
                    raise CryptorgError("Rate limited by Cryptorg. Try again in 5 minutes.")
                raise CryptorgError("Login failed: no redirect")

            # 3. Follow redirect to trading password page
            redirect_url = loc if loc.startswith("http") else f"{WEB_BASE}{loc}"
            resp = await web_sess.get(redirect_url, allow_redirects=True)
            html = await resp.text()
            url = str(resp.url)

            # 4. Submit trading password if required
            if "verify-pincode" in url or "two-factor" in url:
                csrf2 = self._get_csrf(html)
                resp = await web_sess.post(
                    f"{WEB_BASE}/en/site/verify-pincode",
                    data={
                        "_csrf-frontend": csrf2,
                        "VerifyPincodeForm[pincode]": self._trade_password,
                    },
                    allow_redirects=True,
                )
                url = str(resp.url)
                if "verify-pincode" in url or "two-factor" in url or "login" in url:
                    raise CryptorgError("Trading password incorrect")

            # 5. Extract yaronby JWT from cookies
            cookies = jar.filter_cookies(WEB_BASE)
            jwt_cookie = cookies.get("yaronby")
            if not jwt_cookie:
                # Also check api3 domain
                cookies3 = jar.filter_cookies(API_BASE)
                jwt_cookie = cookies3.get("yaronby")

            if not jwt_cookie:
                raise CryptorgError("yaronby JWT cookie not found after login")

            self._jwt = jwt_cookie.value
            # Decode expiry from JWT payload (no verification needed)
            import base64, json as _json
            payload_b64 = self._jwt.split(".")[1]
            payload_b64 += "=" * (-len(payload_b64) % 4)  # pad
            payload = _json.loads(base64.b64decode(payload_b64))
            self._jwt_exp = float(payload.get("exp", time.time() + 3600))

            logger.info("Cryptorg: logged in, JWT expires at %s",
                        time.strftime("%H:%M:%S", time.localtime(self._jwt_exp)))
            self._save_jwt_cache()
        finally:
            await web_sess.close()

    async def _ensure_auth(self):
        if not self._is_token_valid():
            await self.login()

    async def _request(self, method: str, path: str,
                       params: dict | None = None,
                       json: dict | None = None) -> dict | list:
        await self._ensure_auth()
        sess = await self._get_session()
        url = API_BASE + path
        kwargs: dict = {"headers": self._auth_headers()}
        if params:
            kwargs["params"] = params
        if json is not None:
            kwargs["json"] = json

        resp = await sess.request(method, url, **kwargs)

        if resp.status == 401:
            logger.info("JWT expired, refreshing")
            self._jwt = ""
            await self._ensure_auth()
            kwargs["headers"] = self._auth_headers()
            resp = await sess.request(method, url, **kwargs)

        if resp.status >= 400:
            text = await resp.text()
            raise CryptorgError(f"{method} {path} → {resp.status}: {text[:300]}")

        return await resp.json(content_type=None)

    # ── Bots ─────────────────────────────────────────────────────────────────

    async def get_bots(self, symbol: str | None = None) -> list[dict]:
        """List all bots. status=0 → inactive (template), status=4 → active."""
        params = {"symbol": symbol.upper()} if symbol else None
        result = await self._request("GET", "/crazy/api/bots", params=params)
        data = result.get("data", result) if isinstance(result, dict) else result
        return data if isinstance(data, list) else []

    async def get_bot(self, bot_id: int) -> dict:
        result = await self._request("GET", f"/crazy/api/bots/{bot_id}")
        return result.get("data", result) if isinstance(result, dict) else result

    # ── Deals ─────────────────────────────────────────────────────────────────

    async def get_deals(self, bot_id: int | None = None, active: bool = True) -> list[dict]:
        params: dict = {}
        if bot_id is not None:
            params["bot"] = bot_id
        if active:
            params["active"] = "true"
        result = await self._request("GET", "/crazy/api/deals", params=params)
        data = result.get("data", result) if isinstance(result, dict) else result
        return data if isinstance(data, list) else []

    # ── Bot actions ───────────────────────────────────────────────────────────

    async def update_bot(self, bot_id: int, payload: dict) -> dict:
        """Full bot config update via PUT."""
        return await self._request("PUT", f"/crazy/api/bots/{bot_id}", json=payload)

    @staticmethod
    def _remap_pair_keys(obj: dict, old_pair: str, new_pair: str) -> dict:
        """Rename pair-specific keys inside nested config dicts (levels, cooldown)."""
        result = {}
        for k, v in obj.items():
            new_k = new_pair if k == old_pair else k
            result[new_k] = CryptorgClient._remap_pair_keys(v, old_pair, new_pair) if isinstance(v, dict) else v
        return result

    async def set_bot_pair(self, bot_id: int, new_pair: str) -> dict:
        """Change bot trading pair, fixing all nested pair-keyed structures."""
        config = await self.get_bot(bot_id)
        old_pairs = config.get("pairs", [])
        old_pair = old_pairs[0] if old_pairs else ""

        payload = {k: v for k, v in config.items()
                   if k not in ("id", "hash", "created", "updated", "cycles", "status")}
        payload["pairs"] = [new_pair]

        if old_pair and old_pair != new_pair:
            payload["parameters"] = self._remap_pair_keys(
                payload.get("parameters", {}), old_pair, new_pair
            )

        return await self.update_bot(bot_id, payload)

    async def clone_bot(self, template_id: int, new_pair: str,
                        title: str | None = None,
                        overrides: dict | None = None) -> dict:
        """Create a new bot by copying a template with a different pair. Returns new bot data."""
        config = await self.get_bot(template_id)
        old_pair = (config.get("pairs") or [""])[0]

        payload = {k: v for k, v in config.items()
                   if k not in ("id", "hash", "created", "updated", "cycles", "status")}
        payload["pairs"] = [new_pair]
        payload["title"] = title or f"{config.get('title', 'Bot')} {new_pair}"

        if old_pair and old_pair != new_pair:
            payload["parameters"] = self._remap_pair_keys(
                payload.get("parameters", {}), old_pair, new_pair
            )

        if overrides:
            self._apply_overrides(payload, overrides)

        result = await self._request("POST", "/crazy/api/bots", json=payload)
        return result.get("data", result) if isinstance(result, dict) else result

    @staticmethod
    def _apply_overrides(payload: dict, overrides: dict) -> None:
        """Apply flat overrides dict to bot payload in-place.

        Keys: strategy, tp, volume, so_step, vol_mult, step_mult, cycles
        """
        params = payload.setdefault("parameters", {})

        if "strategy" in overrides:
            payload["strategy"] = overrides["strategy"]

        if "tp" in overrides:
            params.setdefault("close", {})["tp_value"] = str(overrides["tp"])

        if "volume" in overrides:
            params.setdefault("open", {})["order_volume"] = str(overrides["volume"])
            params.setdefault("dca", {})["so_volume"] = str(overrides["volume"])

        if "so_step" in overrides:
            params.setdefault("dca", {})["so_percent"] = str(overrides["so_step"])

        if "vol_mult" in overrides:
            params.setdefault("dca", {})["so_multiplier_volume"] = str(overrides["vol_mult"])

        if "step_mult" in overrides:
            params.setdefault("dca", {})["so_multiplier_price"] = str(overrides["step_mult"])

        if "cycles" in overrides:
            open_p = params.setdefault("open", {})
            restr = open_p.setdefault("self_opening_restrictions", {})
            restr.setdefault("cycles", {}).update({
                "is_active": True,
                "limit": int(overrides["cycles"]),
            })

    async def delete_bot(self, bot_id: int) -> dict:
        return await self._request("DELETE", f"/crazy/api/bots/{bot_id}")

    async def start_bot(self, bot_id: int) -> dict:
        return await self._request("PATCH", f"/crazy/api/bots/{bot_id}", json={"action": "start"})

    async def force_open_bot(self, bot_id: int) -> dict:
        return await self._request("PATCH", f"/crazy/api/bots/{bot_id}", json={"action": "force_open"})

    async def stop_bot(self, bot_id: int) -> dict:
        return await self._request("PATCH", f"/crazy/api/bots/{bot_id}", json={"action": "stop"})

    # ── Deal actions ──────────────────────────────────────────────────────────

    async def kill_deal(self, deal_id: int) -> dict:
        """Force close position at market price."""
        return await self._request("PATCH", f"/crazy/api/deals/{deal_id}", json={"action": "kill"})

    async def cancel_deal(self, deal_id: int) -> dict:
        """Cancel deal without market close."""
        return await self._request("PATCH", f"/crazy/api/deals/{deal_id}", json={"action": "cancel"})
