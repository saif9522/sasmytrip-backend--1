"""
Low-level HTTP client for every TBO service.

* Air + Hotel-Book APIs   -> TokenId from SharedData Authenticate (cached for the day)
* Hotel Search / PreBook  -> HTTP Basic Auth with agency API credentials
* Hotel static data       -> HTTP Basic Auth with static-data credentials

All requests are JSON POST with gzip accepted (TBO recommends compression).
In mock mode no network call is made — app.services.tbo.mock answers instead.
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from app.services.tbo import config

log = logging.getLogger("tbo")

IST = timezone(timedelta(hours=5, minutes=30))

# Air/Hotel-book ResponseStatus values
RESPONSE_OK = 1
RESPONSE_INVALID_SESSION = 4


class TBOError(Exception):
    """Raised when TBO returns an error or can't be reached."""

    def __init__(self, message: str, code: Any = None, status_code: int = 502, raw: Any = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.raw = raw


class _TokenCache:
    def __init__(self):
        self.token: Optional[str] = None
        self.issued_on: Optional[str] = None  # IST date string — TBO tokens are valid for that day
        self.agency_id: Optional[int] = None
        self.member_id: Optional[int] = None
        self.lock = asyncio.Lock()

    def valid(self) -> bool:
        return bool(self.token) and self.issued_on == datetime.now(IST).strftime("%Y-%m-%d")

    def clear(self):
        self.token = None
        self.issued_on = None


_token = _TokenCache()


def _http(timeout: Optional[float] = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=timeout or config.settings.timeout,
        headers={"Content-Type": "application/json", "Accept": "application/json", "Accept-Encoding": "gzip, deflate"},
    )


def _save_log(url: str, payload: dict, data: Any, status: Any):
    """TBO_LOG_DIR=logs/tbo -> one JSON file per call (needed for TBO certification)."""
    folder = os.getenv("TBO_LOG_DIR", "").strip()
    if not folder:
        return
    try:
        os.makedirs(folder, exist_ok=True)
        safe = dict(payload)
        for k in ("Password", "TokenId"):
            if k in safe:
                safe[k] = "***"
        method = url.rstrip("/").rsplit("/", 1)[-1]
        name = f"{datetime.now(IST).strftime('%Y%m%d-%H%M%S-%f')}-{method}.json"
        with open(os.path.join(folder, name), "w", encoding="utf-8") as fh:
            json.dump({"url": url, "http_status": status, "request": safe, "response": data}, fh, indent=2, default=str)
    except OSError:
        log.warning("Could not write TBO log file", exc_info=True)


async def _post(url: str, payload: dict, auth: Optional[tuple] = None, timeout: Optional[float] = None) -> Any:
    log.info("TBO POST %s", url)
    try:
        async with _http(timeout) as client:
            resp = await client.post(url, json=payload, auth=auth)
    except httpx.TimeoutException:
        raise TBOError("The supplier took too long to respond. Please try again.", code="timeout", status_code=504)
    except httpx.HTTPError as exc:
        raise TBOError(f"Could not reach the supplier: {exc.__class__.__name__}", code="network", status_code=502)

    if resp.status_code == 401:
        raise TBOError("Supplier rejected the API credentials (401). Check TBO_* settings.", code=401, status_code=502)
    try:
        data = resp.json()
    except ValueError:
        _save_log(url, payload, resp.text[:5000], resp.status_code)
        raise TBOError(f"Supplier returned a non-JSON response (HTTP {resp.status_code}).", code=resp.status_code, status_code=502)
    _save_log(url, payload, data, resp.status_code)
    if resp.status_code >= 500:
        raise TBOError(f"Supplier error (HTTP {resp.status_code}).", code=resp.status_code, status_code=502, raw=data)
    return data


# ---------------------------------------------------------------- Authenticate

async def authenticate(force: bool = False) -> str:
    s = config.settings
    if s.is_mock:
        return "MOCK-TOKEN"
    async with _token.lock:
        if _token.valid() and not force:
            return _token.token
        if not s.username or not s.password:
            raise TBOError("TBO_USERNAME / TBO_PASSWORD are not configured.", code="config", status_code=503)
        data = await _post(
            f"{s.urls['shared']}/Authenticate",
            {"ClientId": s.client_id, "UserName": s.username, "Password": s.password, "EndUserIp": s.server_ip},
        )
        if data.get("Status") != 1 or not data.get("TokenId"):
            err = (data.get("Error") or {}).get("ErrorMessage") or f"Authenticate failed (Status {data.get('Status')})"
            raise TBOError(err, code=(data.get("Error") or {}).get("ErrorCode"), status_code=502, raw=data)
        member = data.get("Member") or {}
        _token.token = data["TokenId"]
        _token.issued_on = datetime.now(IST).strftime("%Y-%m-%d")
        _token.agency_id = member.get("AgencyId")
        _token.member_id = member.get("MemberId")
        log.info("TBO authenticated (agency %s)", _token.agency_id)
        return _token.token


def token_info() -> dict:
    return {"agency_id": _token.agency_id, "member_id": _token.member_id, "token_cached": _token.valid()}


# ---------------------------------------------------------------- Air API

async def air(method: str, payload: dict, end_user_ip: Optional[str] = None) -> dict:
    """Call an Air API method. Returns the inner `Response` object on success."""
    s = config.settings
    body = {"EndUserIp": end_user_ip or s.server_ip, **payload}

    if s.is_mock:
        from app.services.tbo import mock
        data = mock.air(method, body)
    else:
        body["TokenId"] = await authenticate()
        data = await _post(f"{s.urls['air']}/{method}", body)
        if _status(data) == RESPONSE_INVALID_SESSION:
            body["TokenId"] = await authenticate(force=True)
            data = await _post(f"{s.urls['air']}/{method}", body)

    response = data.get("Response", data)
    _raise_air_error(response, method)
    return response


def _status(data: dict) -> Optional[int]:
    inner = data.get("Response", data) if isinstance(data, dict) else {}
    return inner.get("ResponseStatus") if isinstance(inner, dict) else None


def _raise_air_error(response: dict, method: str):
    err = response.get("Error") or {}
    code = err.get("ErrorCode", 0)
    if response.get("ResponseStatus") not in (None, RESPONSE_OK) or (code not in (0, None)):
        msg = err.get("ErrorMessage") or f"{method} failed (ResponseStatus {response.get('ResponseStatus')})"
        raise TBOError(msg, code=code, status_code=422 if code else 502, raw=response)


async def shared(method: str, payload: dict) -> dict:
    """SharedData methods that need TokenId (GetAgencyBalance, Logout)."""
    s = config.settings
    if s.is_mock:
        from app.services.tbo import mock
        return mock.shared(method, payload)
    token = await authenticate()
    body = {
        "ClientId": s.client_id, "EndUserIp": s.server_ip, "TokenId": token,
        "TokenAgencyId": _token.agency_id, "TokenMemberId": _token.member_id, **payload,
    }
    return await _post(f"{s.urls['shared']}/{method}", body)


# ---------------------------------------------------------------- Hotel API V10

async def hotel_search_api(method: str, payload: dict, timeout: Optional[float] = None) -> dict:
    """Search / PreBook — Basic Auth."""
    s = config.settings
    if s.is_mock:
        from app.services.tbo import mock
        return mock.hotel(method, payload)
    if not s.hotel_username:
        raise TBOError("TBO hotel credentials are not configured.", code="config", status_code=503)
    return await _post(f"{s.urls['hotel_search']}/{method}", payload, auth=(s.hotel_username, s.hotel_password), timeout=timeout)


async def hotel_book_api(method: str, payload: dict, result_key: str, end_user_ip: Optional[str] = None) -> dict:
    """Book / Getbookingdetail / SendChangeRequest / GetChangeRequestStatus — TokenId."""
    s = config.settings
    body = {"EndUserIp": end_user_ip or s.server_ip, **payload}
    if s.is_mock:
        from app.services.tbo import mock
        data = mock.hotel(method, body)
    else:
        body["TokenId"] = await authenticate()
        data = await _post(f"{s.urls['hotel_book']}/{method}", body)
        inner = data.get(result_key, data)
        if inner.get("ResponseStatus") == RESPONSE_INVALID_SESSION:
            body["TokenId"] = await authenticate(force=True)
            data = await _post(f"{s.urls['hotel_book']}/{method}", body)
    inner = data.get(result_key, data)
    _raise_air_error(inner, method)  # same ResponseStatus/Error envelope as Air
    return inner


async def hotel_static_api(method: str, payload: dict) -> dict:
    s = config.settings
    if s.is_mock:
        from app.services.tbo import mock
        return mock.static(method, payload)
    if not s.static_username:
        raise TBOError("TBO_STATIC_USERNAME / TBO_STATIC_PASSWORD are not configured.", code="config", status_code=503)
    url = f"{s.urls['hotel_static']}/{method}"
    auth = (s.static_username, s.static_password)
    if method == "CountryList":  # documented as a GET call
        try:
            async with _http() as c:
                resp = await c.get(url, auth=auth)
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TBOError(f"Could not load country list: {exc.__class__.__name__}", code="network")
    return await _post(url, payload, auth=auth)
