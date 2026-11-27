"""Authenticated WebSocket API shared by the dashboard and MCP tools."""

from __future__ import annotations

from decimal import Decimal
from datetime import datetime
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import aiohttp_client

from .account_api import EtilbudsavisAccountClient
from .api import EtilbudsavisApiError, EtilbudsavisClient, SearchOptions
from .const import (
    CONF_LIST_IDS,
    CONF_PREFERRED_STORE_IDS,
    DOMAIN,
)
from .coordinator import ShoppingListsCoordinator
from .offer_actions import async_add_offer_to_list
from .saved_searches import (
    async_remove_search,
    async_save_search,
    async_setup as async_setup_saved_searches,
    get_saved_searches,
)


async def async_setup(hass: HomeAssistant) -> None:
    """Load saved searches and register the integration's WebSocket commands."""
    await async_setup_saved_searches(hass)
    for command in (
        websocket_search_offers,
        websocket_list_stores,
        websocket_get_lists,
        websocket_get_items,
        websocket_add_item,
        websocket_add_offer,
        websocket_set_item_completed,
        websocket_update_item,
        websocket_remove_item,
        websocket_saved_searches,
        websocket_save_search,
        websocket_remove_saved_search,
    ):
        websocket_api.async_register_command(hass, command)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/search_offers",
        vol.Required("query"): str,
        vol.Optional("limit", default=20): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
        vol.Optional("store_scope", default="preferred"): vol.In(["preferred", "all"]),
    }
)
@websocket_api.async_response
async def websocket_search_offers(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Search current offers, defaulting to the configured preferred stores."""
    entry = _first_entry(hass)
    dealer_ids: tuple[str, ...] = ()
    if entry is not None and msg["store_scope"] == "preferred":
        dealer_ids = tuple(
            str(value)
            for value in entry.options.get(
                CONF_PREFERRED_STORE_IDS,
                entry.data.get(CONF_PREFERRED_STORE_IDS, []),
            )
        )
    latitude = hass.config.latitude
    longitude = hass.config.longitude
    options = SearchOptions(
        limit=msg["limit"],
        latitude=latitude if latitude is not None and longitude is not None else None,
        longitude=longitude if latitude is not None and longitude is not None else None,
        radius_m=25_000 if latitude is not None and longitude is not None else None,
        dealer_ids=dealer_ids,
    )
    client = EtilbudsavisClient(aiohttp_client.async_get_clientsession(hass))
    try:
        offers = await client.search_offers(msg["query"], options)
    except EtilbudsavisApiError as err:
        raise HomeAssistantError("Offer search failed") from err
    connection.send_result(msg["id"], {"offers": [_offer_to_dict(offer) for offer in offers]})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/list_stores"}
)
@websocket_api.async_response
async def websocket_list_stores(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return store options from the offer API."""
    client = EtilbudsavisClient(aiohttp_client.async_get_clientsession(hass))
    try:
        stores = await client.list_stores()
    except EtilbudsavisApiError as err:
        raise HomeAssistantError("Could not load eTilbudsavis stores") from err
    connection.send_result(
        msg["id"],
        {
            "stores": [
                {"id": store.store_id, "name": store.name, "logo_url": store.logo_url}
                for store in stores
            ],
            "preferred_store_ids": sorted(_preferred_store_ids(hass)),
        },
    )


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/get_lists"}
)
@websocket_api.async_response
async def websocket_get_lists(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return only the lists selected by the user in integration setup."""
    coordinator = _coordinator(hass)
    connection.send_result(
        msg["id"],
        {
            "lists": [
                {"id": data.list_id, "name": data.name}
                for data in (coordinator.data or {}).values()
            ]
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_items",
        vol.Required("list_id"): vol.Coerce(int),
    }
)
@websocket_api.async_response
async def websocket_get_items(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Read items from a selected list only."""
    data = _selected_list(hass, msg["list_id"])
    connection.send_result(msg["id"], {"list_id": data.list_id, "items": list(data.items)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/add_item",
        vol.Required("list_id"): vol.Coerce(int),
        vol.Required("name"): vol.All(str, vol.Length(min=1, max=200)),
        vol.Optional("count", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=99)),
        vol.Optional("note", default=""): vol.All(str, vol.Length(max=200)),
        vol.Optional("store_id", default=""): str,
    }
)
@websocket_api.async_response
async def websocket_add_item(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Add a plain-text item to a selected list."""
    _selected_list(hass, msg["list_id"])
    if msg["store_id"] and msg["store_id"] not in _preferred_store_ids(hass):
        raise HomeAssistantError("Only configured preferred stores can be selected")
    result = await _account_client(hass).add_item(
        msg["list_id"],
        msg["name"],
        count=msg["count"],
        short_description=msg["note"],
        business_public_id=msg["store_id"] or None,
    )
    await _coordinator(hass).async_request_refresh()
    connection.send_result(msg["id"], {"item": result})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/add_offer",
        vol.Required("list_id"): vol.Coerce(int),
        vol.Required("query"): vol.All(str, vol.Length(min=1, max=200)),
        vol.Required("offer_id"): vol.All(str, vol.Length(min=1, max=100)),
        vol.Optional("count", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=99)),
        vol.Optional("note", default=""): vol.All(str, vol.Length(max=200)),
        vol.Optional("store_scope", default="preferred"): vol.In(["preferred", "all"]),
    }
)
@websocket_api.async_response
async def websocket_add_offer(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Add a current offer with its store association to a selected list."""
    result = await async_add_offer_to_list(
        hass,
        list_id=msg["list_id"],
        query=msg["query"],
        offer_id=msg["offer_id"],
        count=msg["count"],
        note=msg["note"],
        store_scope=msg["store_scope"],
    )
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_item_completed",
        vol.Required("list_id"): vol.Coerce(int),
        vol.Required("client_id"): str,
        vol.Required("completed"): bool,
    }
)
@websocket_api.async_response
async def websocket_set_item_completed(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Set completion only for an item that exists in the selected list."""
    data = _selected_list(hass, msg["list_id"])
    item = next(
        (item for item in data.items if str(item.get("clientId")) == msg["client_id"]),
        None,
    )
    if item is None:
        raise HomeAssistantError("Item does not belong to the selected list")
    await _account_client(hass).update_item(
        msg["list_id"],
        msg["client_id"],
        ticked=msg["completed"],
        count=int(item.get("count") or 1),
        short_description=str(item.get("shortDescription") or ""),
    )
    await _coordinator(hass).async_request_refresh()
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/update_item",
        vol.Required("list_id"): vol.Coerce(int),
        vol.Required("item_id"): vol.Coerce(int),
        vol.Required("client_id"): str,
        vol.Required("name"): vol.All(str, vol.Length(min=1, max=200)),
        vol.Required("count"): vol.All(vol.Coerce(int), vol.Range(min=1, max=99)),
        vol.Required("note"): vol.All(str, vol.Length(max=200)),
        vol.Optional("store_id"): str,
    }
)
@websocket_api.async_response
async def websocket_update_item(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update editable fields on an item belonging to a selected list."""
    data = _selected_list(hass, msg["list_id"])
    item = next(
        (
            item
            for item in data.items
            if int(item.get("id", -1)) == msg["item_id"]
            and str(item.get("clientId")) == msg["client_id"]
        ),
        None,
    )
    if item is None:
        raise HomeAssistantError("Item does not belong to the selected list")

    store_id = msg.get("store_id")
    if store_id not in (None, "") and store_id not in _preferred_store_ids(hass):
        raise HomeAssistantError("Only configured preferred stores can be selected")

    await _account_client(hass).update_item(
        msg["list_id"],
        msg["client_id"],
        ticked=bool(item.get("ticked", False)),
        count=msg["count"],
        short_description=msg["note"],
        name=msg["name"],
        business_public_id=store_id if store_id is not None else None,
    )
    await _coordinator(hass).async_request_refresh()
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/remove_item",
        vol.Required("list_id"): vol.Coerce(int),
        vol.Required("item_id"): vol.Coerce(int),
    }
)
@websocket_api.async_response
async def websocket_remove_item(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Remove an item only if it belongs to a selected list."""
    data = _selected_list(hass, msg["list_id"])
    if not any(int(item.get("id", -1)) == msg["item_id"] for item in data.items):
        raise HomeAssistantError("Item does not belong to the selected list")
    await _account_client(hass).remove_item(msg["list_id"], msg["item_id"])
    await _coordinator(hass).async_request_refresh()
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/saved_searches/list"}
)
@websocket_api.async_response
async def websocket_saved_searches(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Read persistent user-defined searches."""
    connection.send_result(msg["id"], {"items": get_saved_searches(hass)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/saved_searches/save",
        vol.Optional("search_id"): str,
        vol.Required("name"): vol.All(str, vol.Length(min=1, max=80)),
        vol.Required("query"): vol.All(str, vol.Length(min=1, max=120)),
        vol.Optional("max_price"): vol.All(vol.Coerce(float), vol.Range(min=0)),
    }
)
@websocket_api.async_response
async def websocket_save_search(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create or update a saved search in Home Assistant storage."""
    item = await async_save_search(
        hass,
        search_id=msg.get("search_id"),
        name=msg["name"],
        query=msg["query"],
        max_price=msg.get("max_price"),
    )
    connection.send_result(msg["id"], {"search": item})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/saved_searches/remove",
        vol.Required("search_id"): str,
    }
)
@websocket_api.async_response
async def websocket_remove_saved_search(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Remove one saved search from Home Assistant storage."""
    await async_remove_search(hass, msg["search_id"])
    connection.send_result(msg["id"], {"success": True})


def _first_entry(hass: HomeAssistant) -> Any | None:
    entries = hass.config_entries.async_entries(DOMAIN)
    return entries[0] if entries else None


def _coordinator(hass: HomeAssistant) -> ShoppingListsCoordinator:
    entry = _first_entry(hass)
    if entry is None or entry.entry_id not in hass.data.get(DOMAIN, {}):
        raise HomeAssistantError("eTilbudsavis account is not configured")
    return hass.data[DOMAIN][entry.entry_id]


def _selected_list(hass: HomeAssistant, list_id: int) -> Any:
    coordinator = _coordinator(hass)
    selected = {
        int(value)
        for value in coordinator.config_entry.options.get(
            CONF_LIST_IDS, coordinator.config_entry.data.get(CONF_LIST_IDS, [])
        )
    }
    data = (coordinator.data or {}).get(list_id)
    if list_id not in selected or data is None:
        raise HomeAssistantError("Shopping list is not selected for synchronization")
    return data


def _preferred_store_ids(hass: HomeAssistant) -> set[str]:
    """Return only the configured preferred stores for item assignment."""
    entry = _first_entry(hass)
    if entry is None:
        return set()
    values = entry.options.get(
        CONF_PREFERRED_STORE_IDS,
        entry.data.get(CONF_PREFERRED_STORE_IDS, []),
    )
    return {str(value) for value in values}


def _account_client(hass: HomeAssistant) -> EtilbudsavisAccountClient:
    coordinator = _coordinator(hass)
    entry = coordinator.config_entry
    return EtilbudsavisAccountClient(
        aiohttp_client.async_get_clientsession(hass),
        token=entry.data.get("token"),
    )


def _offer_to_dict(offer: Any) -> dict[str, Any]:
    return {
        "id": offer.offer_id,
        "title": offer.title,
        "description": offer.description,
        "price": _json_value(offer.price),
        "currency": offer.currency,
        "store_id": offer.store_id,
        "store_name": offer.store_name,
        "store_logo_url": offer.store_logo_url,
        "image_url": offer.image_url,
        "valid_from": _json_value(offer.valid_from),
        "valid_until": _json_value(offer.valid_until),
        "quantity": offer.quantity_text,
        "unit_price": _json_value(offer.unit_price),
        "unit_price_unit": offer.unit_price_unit,
    }


def _json_value(value: Any) -> Any:
    if isinstance(value, (Decimal, datetime)):
        return value.isoformat() if isinstance(value, datetime) else str(value)
    return value
