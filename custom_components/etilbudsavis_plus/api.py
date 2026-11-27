"""Asynchronous client for the observed public offer-search endpoint.

This endpoint is unofficial and undocumented. Keep calls conservative and
fail clearly when its response schema changes. Account/list methods are
intentionally not guessed; they need separate authenticated verification.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

import aiohttp

from .models import Offer, Store

OFFERS_URL = "https://api.etilbudsavis.dk/v2/offers/search"
OFFER_DETAILS_URL = "https://api.etilbudsavis.dk/v2/offers"
STORES_URL = "https://api.etilbudsavis.dk/v2/dealers"
API_VERSION = "0.3.0"
DEFAULT_LOCALE = "da_DK"
MAX_IMAGE_LOOKUPS = 30
IMAGE_LOOKUP_CONCURRENCY = 4


class EtilbudsavisApiError(Exception):
    """Raised when the upstream API fails or changes shape."""


@dataclass(frozen=True, slots=True)
class SearchOptions:
    """Parameters supported by the observed offer-search endpoint."""

    limit: int = 20
    country_id: str = "DK"
    locale: str = DEFAULT_LOCALE
    latitude: float | None = None
    longitude: float | None = None
    radius_m: int | None = None
    dealer_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if self.radius_m is not None and self.radius_m <= 0:
            raise ValueError("radius_m must be positive")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be supplied together")
        if self.radius_m is not None and self.latitude is None:
            raise ValueError("radius_m requires latitude and longitude")


class EtilbudsavisClient:
    """Small transport client; Home Assistant owns session lifecycle."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        endpoint: str = OFFERS_URL,
        offer_details_endpoint: str = OFFER_DETAILS_URL,
        timeout_seconds: float = 15,
    ) -> None:
        self._session = session
        self._endpoint = endpoint
        self._offer_details_endpoint = offer_details_endpoint.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async def search_offers(
        self,
        query: str,
        options: SearchOptions | None = None,
    ) -> list[Offer]:
        """Search current offers and normalize only fields present upstream."""
        query = query.strip()
        if not query:
            return []
        options = options or SearchOptions()
        params = self._search_params(query, options)
        try:
            async with self._session.get(
                self._endpoint,
                params=params,
                timeout=self._timeout,
                headers={"Accept": "application/json"},
            ) as response:
                if response.status == 429:
                    raise EtilbudsavisApiError("Upstream rate limit reached")
                if response.status != 200:
                    raise EtilbudsavisApiError(f"Upstream returned HTTP {response.status}")
                payload: Any = await response.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise EtilbudsavisApiError("Offer search request failed") from err

        if not isinstance(payload, list):
            raise EtilbudsavisApiError("Offer search returned an unexpected response")
        if any(not isinstance(item, dict) for item in payload):
            raise EtilbudsavisApiError("Offer search contained an invalid offer")
        offers = [Offer.from_api(item) for item in payload]
        return await self._enrich_offer_images(offers)

    async def _enrich_offer_images(self, offers: list[Offer]) -> list[Offer]:
        """Fetch the offer image from the detail endpoint when search omits it.

        The public search response often has no image fields, while the detail
        response exposes the crop used by eTilbudsavis itself. Keep this
        best-effort so a detail lookup failure never hides search results.
        """
        candidates = [
            (index, offer)
            for index, offer in enumerate(offers[:MAX_IMAGE_LOOKUPS])
            if not offer.image_url and offer.offer_id
        ]
        if not candidates:
            return offers

        semaphore = asyncio.Semaphore(IMAGE_LOOKUP_CONCURRENCY)

        async def load_image(offer: Offer) -> Offer | None:
            async with semaphore:
                url = f"{self._offer_details_endpoint}/{quote(offer.offer_id or '', safe='')}"
                try:
                    async with self._session.get(
                        url,
                        params={"api_av": API_VERSION},
                        timeout=self._timeout,
                        headers={"Accept": "application/json"},
                    ) as response:
                        if response.status != 200:
                            return None
                        detail: Any = await response.json()
                except (aiohttp.ClientError, TimeoutError, ValueError):
                    return None
                if not isinstance(detail, dict):
                    return None
                enriched = Offer.from_api({**offer.raw, **detail})
                return enriched if enriched.image_url else None

        results = await asyncio.gather(*(load_image(offer) for _, offer in candidates))
        enriched = list(offers)
        for (index, _), result in zip(candidates, results, strict=True):
            if result is not None:
                enriched[index] = result
        return enriched

    async def list_stores(self, country_id: str = "DK") -> list[Store]:
        """List dealers for the store picker, paging with a hard safety limit."""
        stores: dict[str, Store] = {}
        for page in range(20):
            params = {
                "country_id": country_id,
                "limit": "100",
                "offset": str(page * 100),
            }
            try:
                async with self._session.get(
                    STORES_URL,
                    params=params,
                    timeout=self._timeout,
                    headers={"Accept": "application/json"},
                ) as response:
                    if response.status == 429:
                        raise EtilbudsavisApiError("Upstream rate limit reached")
                    if response.status != 200:
                        raise EtilbudsavisApiError(f"Upstream returned HTTP {response.status}")
                    payload: Any = await response.json()
            except (aiohttp.ClientError, TimeoutError) as err:
                raise EtilbudsavisApiError("Store list request failed") from err
            if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
                raise EtilbudsavisApiError("Store list returned an unexpected response")
            for item in payload:
                store = Store.from_api(item)
                if store.store_id and store.name:
                    stores[store.store_id] = store
            if len(payload) < 100:
                break
        return sorted(stores.values(), key=lambda store: store.name.casefold())

    @staticmethod
    def _search_params(query: str, options: SearchOptions) -> dict[str, str]:
        """Build the documented-by-observation query without hand-built URLs."""
        params = {
            "query": query,
            "country_id": options.country_id,
            "limit": str(options.limit),
            "offset": "0",
            "r_locale": options.locale,
            "api_av": API_VERSION,
        }
        if options.latitude is not None and options.longitude is not None:
            params["r_lat"] = str(options.latitude)
            params["r_lng"] = str(options.longitude)
        if options.radius_m is not None:
            params["r_radius"] = str(options.radius_m)
        if options.dealer_ids:
            params["dealer_ids"] = ",".join(options.dealer_ids)
        return params

    @staticmethod
    def build_url(query: str, options: SearchOptions | None = None) -> str:
        """Return a deterministic URL for diagnostics/tests; do not log it with user data."""
        options = options or SearchOptions()
        return f"{OFFERS_URL}?{urlencode(EtilbudsavisClient._search_params(query, options))}"
