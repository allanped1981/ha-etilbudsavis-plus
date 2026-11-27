"""Tests for defensive upstream offer parsing."""

from __future__ import annotations

import unittest
from decimal import Decimal

from custom_components.etilbudsavis_plus.models import Offer


class OfferModelTests(unittest.TestCase):
    def test_missing_or_malformed_values_are_not_invented(self) -> None:
        offer = Offer.from_api(
            {
                "heading": "Tomater",
                "pricing": {"price": "not-a-price"},
                "run_till": "unknown",
            }
        )
        self.assertEqual(offer.title, "Tomater")
        self.assertIsNone(offer.price)
        self.assertIsNone(offer.valid_until)
        self.assertIsNone(offer.store_name)

    def test_price_and_expiry_are_parsed(self) -> None:
        offer = Offer.from_api(
            {
                "id": "offer-1",
                "heading": "Tomater",
                "pricing": {"price": 9.95, "currency": "DKK"},
                "run_till": "2026-11-30T23:59:59Z",
            }
        )
        self.assertEqual(offer.price, Decimal("9.95"))
        self.assertEqual(offer.offer_id, "offer-1")
        self.assertIsNotNone(offer.valid_until)

    def test_newer_offer_shape_supplies_offer_and_store_images(self) -> None:
        offer = Offer.from_api(
            {
                "publicId": "offer-v3",
                "name": "Example Soda",
                "price": 10,
                "imageLarge": "https://example.invalid/offer-large.webp",
                "businessPublicId": "store-1",
                "business": {
                    "name": "Example Market",
                    "publicId": "store-1",
                    "positiveLogoImage": "https://example.invalid/rema.webp",
                },
            }
        )
        self.assertEqual(offer.title, "Example Soda")
        self.assertEqual(offer.store_name, "Example Market")
        self.assertEqual(offer.store_logo_url, "https://example.invalid/rema.webp")
        self.assertEqual(offer.image_url, "https://example.invalid/offer-large.webp")

    def test_publication_cover_is_used_when_offer_image_is_absent(self) -> None:
        offer = Offer.from_api(
            {
                "heading": "Example Beverage",
                "publicationCoverImage": "https://example.invalid/flyer.webp",
            }
        )
        self.assertEqual(offer.image_url, "https://example.invalid/flyer.webp")

    def test_unit_price_is_not_computed_from_a_range(self) -> None:
        offer = Offer.from_api(
            {
                "heading": "Juice",
                "pricing": {"price": 20},
                "quantity": {
                    "size": {"from": 1, "to": 2},
                    "unit": {"symbol": "l"},
                },
            }
        )
        self.assertEqual(offer.quantity_text, "1–2 l")
        self.assertIsNone(offer.unit_price)
        self.assertIsNone(offer.unit_price_unit)


if __name__ == "__main__":
    unittest.main()
