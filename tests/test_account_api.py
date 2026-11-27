"""Contract-shape tests for the observed email and shopping-list endpoints."""

from __future__ import annotations

import base64
import json
import unittest
from contextlib import AbstractAsyncContextManager
from typing import Any

from custom_components.etilbudsavis_plus.account_api import (
    AccountApiError,
    AccountAuthenticationError,
    EtilbudsavisAccountClient,
)
from custom_components.etilbudsavis_plus.models import Offer


class FakeResponse(AbstractAsyncContextManager["FakeResponse"]):
    def __init__(self, status: int, payload: Any) -> None:
        self.status = status
        self.payload = payload

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def json(self, *args: Any, **kwargs: Any) -> Any:
        return self.payload


class FakeSession:
    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self.responses.pop(0)


class AccountApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_email_otp_challenge_and_token(self) -> None:
        session = FakeSession(
            FakeResponse(200, {"otpId": "challenge"}),
            FakeResponse(200, {"token": "session-token"}),
        )
        client = EtilbudsavisAccountClient(session, api_key="client-key")

        challenge = await client.request_otp(" user@example.com ")
        token = await client.verify_otp(challenge, " 123456 ")

        self.assertEqual(challenge, "challenge")
        self.assertEqual(token, "session-token")
        self.assertEqual(client.token, "session-token")
        self.assertEqual(session.calls[0]["json"]["email"], "user@example.com")
        self.assertEqual(session.calls[1]["json"]["otp"], "123456")
        self.assertNotIn("Cookie", session.calls[0]["headers"])

    async def test_list_query_is_encoded_and_requires_session(self) -> None:
        session = FakeSession(FakeResponse(200, [{"value": [{"id": 42, "name": "Test"}]}]))
        client = EtilbudsavisAccountClient(session, api_key="client-key", token="session-token")

        lists = await client.get_shopping_lists()

        self.assertEqual(lists, [{"id": 42, "name": "Test"}])
        encoded = session.calls[0]["json"]["data"][0]
        decoded = json.loads(base64.b64decode(encoded))
        self.assertEqual(decoded, ["shoppingLists", {}])
        self.assertIn("tjek-session=", session.calls[0]["headers"]["Cookie"])

    async def test_expired_session_is_cleared(self) -> None:
        client = EtilbudsavisAccountClient(
            FakeSession(FakeResponse(401, {})), api_key="client-key", token="expired"
        )
        with self.assertRaises(AccountAuthenticationError):
            await client.get_shopping_lists()
        self.assertIsNone(client.token)

    async def test_validation_errors_surface_safe_field_messages(self) -> None:
        session = FakeSession(
            FakeResponse(
                422,
                {
                    "detail": [
                        {
                            "loc": ["body", "item", "offer", "price"],
                            "msg": "Input should be a valid number",
                            "input": "secret-or-user-value",
                        }
                    ]
                },
            )
        )
        client = EtilbudsavisAccountClient(session, api_key="client-key", token="token")

        with self.assertRaisesRegex(
            AccountApiError,
            r"HTTP 422: body.item.offer.price: Input should be a valid number",
        ) as raised:
            await client.add_item(4, "Mælk")

        self.assertNotIn("secret-or-user-value", str(raised.exception))

    async def test_list_writes_send_expected_minimal_payloads(self) -> None:
        session = FakeSession(
            FakeResponse(200, {"id": 9}),
            FakeResponse(200, {}),
            FakeResponse(200, {}),
        )
        client = EtilbudsavisAccountClient(session, api_key="client-key", token="session-token")

        result = await client.add_item(4, "Mælk", count=2, short_description="Laktosefri")
        await client.update_item(4, result["clientId"], ticked=True, count=2)
        await client.remove_item(4, 9)

        self.assertEqual(session.calls[0]["json"]["shoppingListId"], 4)
        self.assertEqual(session.calls[0]["json"]["item"]["name"], "Mælk")
        self.assertTrue(session.calls[1]["json"]["item"]["ticked"])
        self.assertEqual(session.calls[2]["json"], {"shoppingListId": 4, "itemId": 9})

    async def test_offer_item_write_includes_offer_and_store_references(self) -> None:
        session = FakeSession(FakeResponse(200, {"id": 10}))
        client = EtilbudsavisAccountClient(session, api_key="client-key", token="session-token")
        offer = Offer.from_api(
            {
                "id": "offer-123",
                "heading": "Example Soda 1.5 L",
                "description": "1.5 liter. Ex. pant",
                "pricing": {"price": 10, "currency": "DKK"},
                "branding": {"id": "store-123", "name": "Example Market"},
                "run_from": "2026-11-21T23:00:00.000Z",
                "run_till": "2026-11-28T23:00:00.000Z",
                "image": "https://example.invalid/offer.webp",
            }
        )

        result = await client.add_offer_item(4, offer, count=2)

        item = session.calls[0]["json"]["item"]
        self.assertEqual(session.calls[0]["json"]["shoppingListId"], 4)
        self.assertEqual(item["name"], "Example Soda 1.5 L")
        self.assertEqual(item["count"], 2)
        self.assertEqual(item["businessPublicId"], "store-123")
        self.assertEqual(item["offer"]["publicOfferId"], "offer-123")
        self.assertEqual(item["offer"]["businessPublicId"], "store-123")
        self.assertEqual(item["offer"]["price"], 10)
        self.assertIsInstance(item["offer"]["price"], int)
        self.assertEqual(item["offer"]["image"], "https://example.invalid/offer.webp")
        self.assertEqual(result["clientId"], item["clientId"])

    def test_public_app_key_is_default_and_lists_require_session(self) -> None:
        client = EtilbudsavisAccountClient(FakeSession())
        self.assertTrue(client._api_key)
        with self.assertRaises(AccountAuthenticationError):
            client._require_token()


if __name__ == "__main__":
    unittest.main()
