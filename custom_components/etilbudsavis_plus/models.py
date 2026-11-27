"""Typed, source-preserving models for offer data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any


def _datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class Offer:
    """Normalized offer fields; raw data is retained for later schema additions."""

    offer_id: str | None
    title: str
    description: str | None
    price: Decimal | None
    currency: str | None
    store_id: str | None
    store_name: str | None
    store_logo_url: str | None
    image_url: str | None
    valid_from: datetime | None
    valid_until: datetime | None
    quantity_text: str | None
    unit_price: Decimal | None
    unit_price_unit: str | None
    raw: dict[str, Any]

    @classmethod
    def from_api(cls, item: dict[str, Any]) -> Offer:
        pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
        branding = item.get("branding") if isinstance(item.get("branding"), dict) else {}
        dealer = item.get("dealer") if isinstance(item.get("dealer"), dict) else {}
        business = item.get("business") if isinstance(item.get("business"), dict) else {}
        nested_offer = item.get("offer") if isinstance(item.get("offer"), dict) else {}
        images = item.get("images") if isinstance(item.get("images"), dict) else {}
        quantity = item.get("quantity") if isinstance(item.get("quantity"), dict) else {}
        unit = quantity.get("unit") if isinstance(quantity.get("unit"), dict) else {}
        size = quantity.get("size") if isinstance(quantity.get("size"), dict) else {}

        store_name = branding.get("name") or dealer.get("name") or business.get("name")
        store_id = (
            branding.get("id")
            or dealer.get("id")
            or business.get("publicId")
            or item.get("businessPublicId")
        )
        store_logo_url = (
            branding.get("logo")
            or branding.get("positiveLogoImage")
            or business.get("positiveLogoImage")
        )
        image_url = (
            item.get("image")
            or item.get("image_url")
            or item.get("imageLarge")
            or item.get("image_large")
            or images.get("thumb")
            or images.get("view")
            or images.get("zoom")
            or nested_offer.get("image")
            or item.get("publicationCoverImage")
        )
        price = _decimal(
            pricing.get("price")
            if pricing.get("price") is not None
            else item.get("price", nested_offer.get("price"))
        )
        unit_price, unit_price_unit = _unit_price(price, quantity)

        return cls(
            offer_id=(
                str(item.get("id") or item.get("publicId") or nested_offer.get("publicId"))
                if item.get("id") or item.get("publicId") or nested_offer.get("publicId")
                else None
            ),
            title=str(item.get("heading") or item.get("name") or nested_offer.get("name") or ""),
            description=_optional_str(item.get("description") or nested_offer.get("description")),
            price=price,
            currency=_optional_str(
                pricing.get("currency") or item.get("currencyCode") or nested_offer.get("currencyCode")
            ),
            store_id=str(store_id) if store_id is not None else None,
            store_name=_optional_str(store_name),
            store_logo_url=_optional_str(store_logo_url),
            image_url=_optional_str(image_url),
            valid_from=_datetime(item.get("run_from") or item.get("validFrom")),
            valid_until=_datetime(item.get("run_till") or item.get("validUntil")),
            quantity_text=_quantity_text(size, unit),
            unit_price=unit_price,
            unit_price_unit=unit_price_unit,
            raw=dict(item),
        )

    def shopping_list_reference(self) -> dict[str, Any]:
        """Build the offer/store reference used by an eTilbudsavis list item.

        The write contract is undocumented. Preserve only fields observed in
        offer-search responses and use the field names required by the live
        write-side validation response.
        """
        raw = self.raw
        result: dict[str, Any] = {}
        if self.store_id:
            result["businessPublicId"] = self.store_id

        nested: dict[str, Any] = {}
        price_value: int | float | None = None
        if self.price is not None:
            price_value = (
                int(self.price)
                if self.price == self.price.to_integral_value()
                else float(self.price)
            )
        values = {
            # The write endpoint's schema uses different ID names than the
            # account-list read response (`publicId`).
            "publicOfferId": self.offer_id,
            "businessPublicId": self.store_id,
            "name": self.title,
            "description": self.description,
            "price": price_value,
            "currencyCode": self.currency,
            "validFrom": raw.get("run_from") or raw.get("validFrom"),
            "validUntil": raw.get("run_till") or raw.get("validUntil"),
            "image": self.image_url,
        }
        nested.update({key: value for key, value in values.items() if value is not None})

        # These fields occur in account-list offer records. Carry them across
        # only when the search response actually supplies them.
        for source, target in (
            ("publicationPublicId", "publicationPublicId"),
            ("publicationCoverImage", "publicationCoverImage"),
            ("visibleFrom", "visibleFrom"),
            ("departmentSlug", "departmentSlug"),
        ):
            if raw.get(source) is not None:
                nested[target] = raw[source]
        result["offer"] = nested
        return result


@dataclass(frozen=True, slots=True)
class Store:
    """Store/dealer as returned by the offer API."""

    store_id: str
    name: str
    country_id: str | None
    logo_url: str | None
    raw: dict[str, Any]

    @classmethod
    def from_api(cls, item: dict[str, Any]) -> Store:
        country = item.get("country") if isinstance(item.get("country"), dict) else {}
        store_id = item.get("id")
        return cls(
            store_id=str(store_id) if store_id is not None else "",
            name=str(item.get("name") or ""),
            country_id=_optional_str(country.get("id")),
            logo_url=_optional_str(item.get("logo")),
            raw=dict(item),
        )


def _optional_str(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _quantity_text(size: dict[str, Any], unit: dict[str, Any]) -> str | None:
    amount = size.get("from")
    end = size.get("to")
    symbol = unit.get("symbol")
    if amount is None or not symbol:
        return None
    if end is not None and end != amount:
        amount = f"{amount}–{end}"
    return f"{amount} {symbol}"


def _exact_number(value: dict[str, Any]) -> Decimal | None:
    """Return a quantity only when upstream supplies one exact value."""
    start = _decimal(value.get("from"))
    end = _decimal(value.get("to"))
    if start is None or (end is not None and start != end):
        return None
    return start


def _unit_price(
    price: Decimal | None,
    quantity: dict[str, Any],
) -> tuple[Decimal | None, str | None]:
    """Calculate price per litre/kg only from exact, supported quantities."""
    if price is None:
        return None, None
    size = quantity.get("size") if isinstance(quantity.get("size"), dict) else {}
    pieces = quantity.get("pieces") if isinstance(quantity.get("pieces"), dict) else {}
    unit = quantity.get("unit") if isinstance(quantity.get("unit"), dict) else {}
    amount = _exact_number(size)
    count = _exact_number(pieces)
    if count is None:
        count = Decimal("1")
    symbol = str(unit.get("symbol") or "").strip().lower()
    if amount is None or amount <= 0 or count <= 0:
        return None, None

    factors = {
        "l": (Decimal("1"), "kr/l"),
        "dl": (Decimal("0.1"), "kr/l"),
        "cl": (Decimal("0.01"), "kr/l"),
        "ml": (Decimal("0.001"), "kr/l"),
        "kg": (Decimal("1"), "kr/kg"),
        "hg": (Decimal("0.1"), "kr/kg"),
        "g": (Decimal("0.001"), "kr/kg"),
    }
    factor = factors.get(symbol)
    if factor is None:
        return None, None
    base_quantity = amount * count * factor[0]
    if base_quantity <= 0:
        return None, None
    return (price / base_quantity).quantize(Decimal("0.01")), factor[1]
