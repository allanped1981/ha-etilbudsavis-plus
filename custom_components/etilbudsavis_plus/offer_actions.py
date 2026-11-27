"""Shared offer-to-shopping-list operations for MCP and the Lovelace card."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import aiohttp_client

from .account_api import AccountApiError, EtilbudsavisAccountClient
from .api import EtilbudsavisApiError, EtilbudsavisClient, SearchOptions
from .const import CONF_LIST_IDS, CONF_PREFERRED_STORE_IDS, DOMAIN
from .coordinator import ShoppingListsCoordinator
from .models import Offer


def _coordinator(hass: HomeAssistant) -> ShoppingListsCoordinator:
    data = hass.data.get(DOMAIN, {})
    coordinator = next(
        (value for value in data.values() if isinstance(value, ShoppingListsCoordinator)),
        None,
    )
    if coordinator is None:
        raise HomeAssistantError("eTilbudsavis account is not configured")
    return coordinator


async def _find_offer(
    hass: HomeAssistant,
    *,
    query: str,
    offer_id: str,
    store_scope: str = "preferred",
) -> Offer:
    """Resolve an offer ID against a fresh search response before writing."""
    query = query.strip()
    offer_id = offer_id.strip()
    if not query or not offer_id:
        raise HomeAssistantError("A search query and offer ID are required")

    coordinator = _coordinator(hass)
    entry = coordinator.config_entry
    selected_stores = entry.options.get(
        CONF_PREFERRED_STORE_IDS,
        entry.data.get(CONF_PREFERRED_STORE_IDS, []),
    )
    dealer_ids = tuple(str(value) for value in selected_stores) if store_scope == "preferred" else ()
    latitude = hass.config.latitude
    longitude = hass.config.longitude
    has_location = latitude is not None and longitude is not None
    client = EtilbudsavisClient(aiohttp_client.async_get_clientsession(hass))
    try:
        offers = await client.search_offers(
            query,
            SearchOptions(
                limit=100,
                latitude=latitude if has_location else None,
                longitude=longitude if has_location else None,
                radius_m=25_000 if has_location else None,
                dealer_ids=dealer_ids,
            ),
        )
    except EtilbudsavisApiError as err:
        raise HomeAssistantError("Offer lookup failed before adding to the list") from err

    offer = next((item for item in offers if item.offer_id == offer_id), None)
    if offer is None:
        raise HomeAssistantError("That offer is no longer in the search results; search again")
    return offer


async def async_add_offer_to_list(
    hass: HomeAssistant,
    *,
    list_id: int,
    query: str,
    offer_id: str,
    count: int = 1,
    note: str = "",
    store_scope: str = "preferred",
) -> dict[str, Any]:
    """Add one currently searchable offer and verify its linked metadata."""
    coordinator = _coordinator(hass)
    selected = {
        int(value)
        for value in coordinator.config_entry.options.get(
            CONF_LIST_IDS, coordinator.config_entry.data.get(CONF_LIST_IDS, [])
        )
    }
    if list_id not in selected or list_id not in (coordinator.data or {}):
        raise HomeAssistantError("Shopping list is not selected for synchronization")
    if not 1 <= count <= 99:
        raise HomeAssistantError("Quantity must be between 1 and 99")

    offer = await _find_offer(
        hass, query=query, offer_id=offer_id, store_scope=store_scope
    )
    entry = coordinator.config_entry
    account = EtilbudsavisAccountClient(
        aiohttp_client.async_get_clientsession(hass),
        token=entry.data.get("token"),
    )
    try:
        created = await account.add_offer_item(
            list_id, offer, count=count, **({"short_description": note} if note else {})
        )
    except AccountApiError as err:
        raise HomeAssistantError(str(err)) from err
    await coordinator.async_request_refresh()

    def find_created_item() -> dict[str, Any] | None:
        refreshed = (coordinator.data or {}).get(list_id)
        return next(
            (
                row
                for row in (refreshed.items if refreshed else ())
                if row.get("clientId") == created["clientId"]
            ),
            None,
        )

    item = find_created_item()
    if note and (item or {}).get("shortDescription") != note:
        # The add endpoint can drop notes even when it accepts the item.
        try:
            await account.update_item(
                list_id,
                created["clientId"],
                ticked=bool((item or {}).get("ticked", False)),
                short_description=note,
            )
        except AccountApiError:
            pass
        else:
            await coordinator.async_request_refresh()
            item = find_created_item() or item

    attached = bool(
        item
        and str(item.get("businessPublicId")) == str(offer.store_id)
        and isinstance(item.get("offer"), dict)
        and str(
            item["offer"].get("publicOfferId") or item["offer"].get("publicId")
        ) == str(offer.offer_id)
    )
    return {
        "item": item or created,
        "offer_metadata_attached": attached,
        **({"note_saved": (item or {}).get("shortDescription") == note} if note else {}),
        "offer_id": offer.offer_id,
        "store_id": offer.store_id,
        "store_name": offer.store_name,
    }
