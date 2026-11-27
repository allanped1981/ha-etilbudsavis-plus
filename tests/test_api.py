"""Tests for the offer API client using only deterministic fake responses."""

from __future__ import annotations

import unittest
from contextlib import AbstractAsyncContextManager
from typing import Any

from custom_components.etilbudsavis_plus.api import (
    EtilbudsavisApiError,
    EtilbudsavisClient,
    SearchOptions,
)


class FakeResponse(AbstractAsyncContextManager["FakeResponse"]):
    def __init__(self, status: int, payload: Any) -> None:
        self.status = status
        self._payload = payload

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def json(self) -> Any:
        return self._payload


class FakeSession:
    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self.responses.pop(0)


class OfferApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_normalizes_offer_and_passes_filters(self) -> None:
        session = FakeSession(
            FakeResponse(
                200,
                [
                    {
                        "id": 123,
                        "heading": "Havremælk",
                        "pricing": {"price": 12.5, "currency": "DKK"},
                        "branding": {"id": 7, "name": "Netto"},
                        "quantity": {
                            "size": {"from": 1},
                            "pieces": {"from": 1},
                            "unit": {"symbol": "l"},
                        },
                        "run_from": "2026-11-24T00:00:00+01:00",
                    }
                ],
            ),
            FakeResponse(
                200,
                {
                    "id": "123",
                    "images": {
                        "thumb": "https://example.invalid/thumb.webp",
                        "view": "https://example.invalid/view.webp",
                    },
                },
            ),
        )
        client = EtilbudsavisClient(
            session,
            endpoint="https://example.test/search",
            offer_details_endpoint="https://example.test/offers",
        )

        offers = await client.search_offers(
            "  havremælk ",
            SearchOptions(
                latitude=55.47,
                longitude=8.45,
                radius_m=25000,
                dealer_ids=("netto-id", "rema-id"),
            ),
        )

        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].offer_id, "123")
        self.assertEqual(offers[0].store_name, "Netto")
        self.assertEqual(str(offers[0].price), "12.5")
        self.assertEqual(offers[0].quantity_text, "1 l")
        self.assertEqual(str(offers[0].unit_price), "12.50")
        self.assertEqual(offers[0].unit_price_unit, "kr/l")
        self.assertEqual(offers[0].image_url, "https://example.invalid/thumb.webp")
        query = session.calls[0]["params"]
        self.assertEqual(query["query"], "havremælk")
        self.assertEqual(query["dealer_ids"], "netto-id,rema-id")
        self.assertEqual(query["r_lat"], "55.47")
        self.assertEqual(session.calls[1]["url"], "https://example.test/offers/123")

    async def test_empty_query_makes_no_request(self) -> None:
        session = FakeSession(FakeResponse(200, []))
        offers = await EtilbudsavisClient(session).search_offers("  ")
        self.assertEqual(offers, [])
        self.assertEqual(session.calls, [])

    async def test_rate_limit_is_reported(self) -> None:
        client = EtilbudsavisClient(FakeSession(FakeResponse(429, {})))
        with self.assertRaisesRegex(EtilbudsavisApiError, "rate limit"):
            await client.search_offers("kaffe")

    async def test_unexpected_response_is_reported(self) -> None:
        client = EtilbudsavisClient(FakeSession(FakeResponse(200, {"offers": []})))
        with self.assertRaisesRegex(EtilbudsavisApiError, "unexpected response"):
            await client.search_offers("kaffe")

    def test_invalid_search_options_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            SearchOptions(latitude=55.47)
        with self.assertRaises(ValueError):
            SearchOptions(limit=0)
        with self.assertRaises(ValueError):
            SearchOptions(radius_m=25_000)

    async def test_store_list_normalizes_and_deduplicates_dealers(self) -> None:
        session = FakeSession(
            FakeResponse(
                200,
                [
                    {"id": "1", "name": "Market A", "country": {"id": "DK"}},
                    {"id": "2", "name": "Example Market", "country": {"id": "DK"}},
                ],
            )
        )
        client = EtilbudsavisClient(session)

        stores = await client.list_stores()

        self.assertEqual([store.name for store in stores], ["Market A", "Example Market"])
        self.assertEqual(stores[0].country_id, "DK")


if __name__ == "__main__":
    unittest.main()
