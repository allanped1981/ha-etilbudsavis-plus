"""Cleanly implemented, authenticated account endpoints observed in source.

These endpoints are undocumented. The client key is included from a public
client implementation; it is not an account secret. Never log tokens or
one-time codes.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import aiohttp

from .models import Offer

ACCOUNT_BASE_URL = "https://etilbudsavis.dk"
# Public consumer-app client key observed in the current community HA client.
# It is not a user credential; Tjek can rotate or revoke it without notice.
APP_CLIENT_KEY = "152000596c6e45d9983eab0c14afebea"


class AccountAuthenticationError(Exception):
    """Raised when OTP verification fails or the account session expires."""


class AccountApiError(Exception):
    """Raised when an account endpoint fails or returns an unexpected shape."""


class EtilbudsavisAccountClient:
    """Email OTP and shopping-list client with caller-owned HTTP session."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        api_key: str = APP_CLIENT_KEY,
        token: str | None = None,
        base_url: str = ACCOUNT_BASE_URL,
        timeout_seconds: float = 15,
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    @property
    def token(self) -> str | None:
        """Current bearer-like session value for Home Assistant storage."""
        return self._token

    def set_token(self, token: str | None) -> None:
        """Set a persisted session token after restoring or clearing auth."""
        self._token = token

    async def request_otp(self, email: str) -> str:
        """Send a one-time code to the account email and return its challenge id."""
        payload = {"apiKey": self._api_key, "email": email.strip()}
        result = await self._post_json("/api/auth-otp-initialize", payload, authenticated=False)
        otp_id = result.get("otpId") if isinstance(result, dict) else None
        if not isinstance(otp_id, str) or not otp_id:
            raise AccountAuthenticationError("OTP initialization returned no challenge id")
        return otp_id

    async def verify_otp(self, otp_id: str, code: str) -> str:
        """Verify an email code and retain the returned session token."""
        payload = {"apiKey": self._api_key, "otpId": otp_id, "otp": code.strip()}
        result = await self._post_json("/api/auth-otp-finalize", payload, authenticated=False)
        token = result.get("token") if isinstance(result, dict) else None
        if not isinstance(token, str) or not token:
            raise AccountAuthenticationError("OTP verification returned no session token")
        self._token = token
        return token

    async def get_shopping_lists(self) -> list[dict[str, Any]]:
        return await self._rpc_value("shoppingLists", {})

    async def get_shopping_list_items(self, shopping_list_id: int) -> list[dict[str, Any]]:
        return await self._rpc_value(
            "shoppingListItems", {"shoppingListId": shopping_list_id}
        )

    async def add_item(
        self,
        shopping_list_id: int,
        name: str,
        *,
        count: int = 1,
        short_description: str = "",
        business_public_id: str | None = None,
    ) -> dict[str, Any]:
        if not name.strip():
            raise ValueError("Item name must not be empty")
        if count < 1:
            raise ValueError("Item count must be at least one")
        client_id = str(uuid.uuid4())
        item: dict[str, Any] = {"clientId": client_id, "name": name.strip(), "count": count}
        if short_description:
            item["shortDescription"] = short_description
        if business_public_id:
            item["businessPublicId"] = business_public_id
        result = await self._post_json(
            "/api/shopping-list-add-item",
            {"shoppingListId": shopping_list_id, "item": item},
        )
        if isinstance(result, dict):
            result.setdefault("clientId", client_id)
            return result
        return {"clientId": client_id}

    async def add_offer_item(
        self,
        shopping_list_id: int,
        offer: Offer,
        *,
        count: int = 1,
        short_description: str = "",
    ) -> dict[str, Any]:
        """Add a selected offer with its store and offer references.

        This extends the observed plain-item request with the same
        ``businessPublicId`` and ``offer`` fields returned for offer-backed
        list items. Live acceptance must be verified before release.
        """
        if not offer.offer_id:
            raise ValueError("Offer ID is required")
        if not offer.title.strip():
            raise ValueError("Offer title must not be empty")
        if count < 1:
            raise ValueError("Item count must be at least one")
        client_id = str(uuid.uuid4())
        item: dict[str, Any] = {
            "clientId": client_id,
            "name": offer.title.strip(),
            "count": count,
            **offer.shopping_list_reference(),
        }
        if short_description:
            item["shortDescription"] = short_description
        result = await self._post_json(
            "/api/shopping-list-add-item",
            {"shoppingListId": shopping_list_id, "item": item},
        )
        if isinstance(result, dict):
            result.setdefault("clientId", client_id)
            return result
        return {"clientId": client_id}

    async def update_item(
        self,
        shopping_list_id: int,
        client_id: str,
        *,
        ticked: bool,
        count: int | None = None,
        short_description: str | None = None,
        name: str | None = None,
        business_public_id: str | None = None,
    ) -> None:
        item: dict[str, Any] = {
            "clientId": client_id,
            "ticked": ticked,
            "updatedAt": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        }
        if count is not None:
            if count < 1:
                raise ValueError("Item count must be at least one")
            item["count"] = count
        if short_description is not None:
            item["shortDescription"] = short_description
        if name is not None:
            if not name.strip():
                raise ValueError("Item name must not be empty")
            item["name"] = name.strip()
        if business_public_id is not None:
            item["businessPublicId"] = business_public_id or None
        await self._post_json(
            "/api/shopping-list-update-item",
            {"shoppingListId": shopping_list_id, "item": item},
        )

    async def remove_item(self, shopping_list_id: int, item_id: int) -> None:
        await self._post_json(
            "/api/shopping-list-remove-item",
            {"shoppingListId": shopping_list_id, "itemId": item_id},
        )

    async def _rpc_value(self, query_name: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        self._require_token()
        query = base64.b64encode(
            json.dumps([query_name, params], separators=(",", ":")).encode("utf-8")
        ).decode("ascii")
        result = await self._post_json("/", {"data": [query]})
        if isinstance(result, dict):
            result = [result]
        if not isinstance(result, list) or not result:
            return []
        value = result[0].get("value") if isinstance(result[0], dict) else None
        if value is None:
            return []
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise AccountApiError("Shopping-list endpoint returned an unexpected shape")
        return value

    async def _post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        authenticated: bool = True,
    ) -> Any:
        if authenticated:
            self._require_token()
        headers = self._headers()
        try:
            async with self._session.post(
                f"{self._base_url}{path}",
                json=payload,
                headers=headers,
                timeout=self._timeout,
            ) as response:
                if response.status in (401, 403):
                    self._token = None
                    raise AccountAuthenticationError("The account session is invalid or expired")
                if response.status == 429:
                    raise AccountApiError("Tjek rate limit reached")
                if not 200 <= response.status < 300:
                    detail = await self._response_error_detail(response)
                    message = f"Account endpoint returned HTTP {response.status}"
                    if detail:
                        message = f"{message}: {detail}"
                    raise AccountApiError(message)
                return await response.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise AccountApiError("Account request failed") from err

    @staticmethod
    async def _response_error_detail(response: aiohttp.ClientResponse) -> str | None:
        """Extract a bounded validation message without echoing request data."""
        try:
            payload = await response.json(content_type=None)
        except (aiohttp.ClientError, ValueError):
            return None

        if not isinstance(payload, dict):
            return None
        detail = payload.get("detail") or payload.get("errors") or payload.get("message")
        if isinstance(detail, str):
            return detail[:300]
        if isinstance(detail, list):
            messages: list[str] = []
            for issue in detail[:5]:
                if not isinstance(issue, dict) or not isinstance(issue.get("msg"), str):
                    continue
                location = issue.get("loc")
                prefix = ".".join(str(part) for part in location) if isinstance(location, list) else ""
                messages.append(f"{prefix}: {issue['msg']}" if prefix else issue["msg"])
            return "; ".join(messages)[:300] or None
        return None

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": self._base_url,
            "Referer": f"{self._base_url}/indkoebslister/aktiv",
            "x-api-key": self._api_key,
        }
        if self._token:
            cookie = quote(json.dumps({"token": self._token}, separators=(",", ":")))
            headers["Cookie"] = f"tjek-session={cookie}"
        return headers

    def _require_token(self) -> None:
        if not self._token:
            raise AccountAuthenticationError("Complete email verification before using shopping lists")
