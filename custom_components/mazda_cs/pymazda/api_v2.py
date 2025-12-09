# SPDX-License-Identifier: MIT
# Simplified Mazda Connected Services API client tailored for tests in this repo.
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, cast

import aiohttp

LOGGER = logging.getLogger("custom_components.mazda_cs.pymazda.api_v2")


# ---------- Models & Errors ----------
@dataclass
class AuthTokens:
    access_token: str
    refresh_token: str
    expires_at_epoch: float

    @property
    def is_expired(self) -> bool:
        # give a small safety window
        return time.time() >= (self.expires_at_epoch - 10)


class MazdaApiError(Exception):
    pass


class MazdaTokenExpired(Exception):
    pass


@dataclass
class MazdaVehicle:
    vin: str
    id: str
    nickname: str | None = None
    model_name: str | None = None
    model_year: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class MazdaVehicleStatus:
    vin: str
    battery_percent: float | None = None
    remaining_range_km: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


# ---------- Client ----------
class MazdaApiV2:
    def __init__(
        self,
        email: str,
        password: str,
        region: str,
        session: aiohttp.ClientSession | None = None,
        *,
        api_base_override: str | None = None,
        oauth_host_override: str | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._email = email
        self._password = password
        self._region = region
        self._tokens: AuthTokens | None = None
        self._session = session
        self._owns_session = session is None
        self._own_session = session is None
        self._logger = logger or LOGGER

        # Default hosts for EU (tests use these)
        oauth_host = oauth_host_override or "https://eu.id.mazda.com"
        api_base = api_base_override or "https://hgs2iveu.mazda.com/connectedservices/v2"

        tenant = "432b587f-88ad-40aa-9e5d-e6bcf9429e8d"
        self._oauth_host = oauth_host.rstrip("/")
        self._authorize_url = f"{self._oauth_host}/{tenant}/b2c_1a_signin/oauth2/v2.0/authorize"
        self._token_url = f"{self._oauth_host}/{tenant}/b2c_1a_signin/oauth2/v2.0/token"
        self._self_asserted_base = f"{self._oauth_host}/{tenant}/B2C_1A_signin/SelfAsserted"
        self._confirm_base = f"{self._oauth_host}/{tenant}/api/CombinedSigninAndSignup/confirmed"
        self._api_base = api_base.rstrip("/")

        self._logger.debug(
            "MazdaApiV2 init: region=%s oauth=%s api=%s",
            self._region,
            self._oauth_host,
            self._api_base,
        )

    # ---- Session helpers ----
    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._own_session = True
        return self._session

    async def _close_session(self) -> None:
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()

    # ---- HTTP helpers with logging ----
    async def _safe_get(self, url: str, **kwargs: Any) -> aiohttp.ClientResponse:
        await self._ensure_session()
        resp = await cast(aiohttp.ClientSession, self._session).get(url, **kwargs)
        try:
            body = await resp.text()
        except Exception:
            body = ""
        # Keep INFO format the tests already saw
        if body and resp.status >= 400:
            self._logger.info("HTTP GET %s -> %s; body: %s", url, resp.status, body)
        else:
            self._logger.info("GET %s -> %s", url, resp.status)
        return resp


async def _safe_post(self, url: str, **kwargs: Any) -> aiohttp.ClientResponse:
    await self._ensure_session()

    # Normalize Mazda B2C token POSTs (grant_type + form headers), even if data is str/FormData
    if "oauth2/v2.0/token" in url:
        from urllib.parse import parse_qsl

        data = kwargs.get("data")
        d = None
        if isinstance(data, dict):
            d = dict(data)
        elif isinstance(data, str):
            try:
                d = dict(parse_qsl(data))
            except Exception:
                d = None
        elif hasattr(data, "_fields"):  # aiohttp.FormData (best effort)
            try:
                tmp = {}
                for item in getattr(data, "_fields", []):
                    if isinstance(item, (tuple, list)) and len(item) >= 2:
                        tmp[str(item[0])] = str(item[1])
                d = tmp or None
            except Exception:
                d = None
        if d is None:
            d = {}
        if "grant_type" not in d:
            if "refresh_token" in d:
                d["grant_type"] = "refresh_token"
            elif "code" in d:
                d["grant_type"] = "authorization_code"
        kwargs["data"] = d
        headers = dict(kwargs.get("headers") or {})
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        kwargs["headers"] = headers
        try:
            self._logger.debug("TOKEN POST normalized payload keys=%s", sorted(d.keys()))
        except Exception:
            pass

    resp = await cast(aiohttp.ClientSession, self._session).post(url, **kwargs)
    try:
        body = await resp.text()
    except Exception:
        body = ""
    if body and resp.status >= 400:
        self._logger.info("HTTP POST %s -> %s; body: %s", url, resp.status, body)
    else:
        self._logger.info("POST %s -> %s", url, resp.status)
    return resp
