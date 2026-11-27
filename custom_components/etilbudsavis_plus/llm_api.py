"""A narrowly scoped Home Assistant LLM/MCP API for eTilbudsavis."""

from __future__ import annotations

from typing import Any, override

import probatio
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import aiohttp_client, config_validation as cv, llm

from .account_api import EtilbudsavisAccountClient
from .api import EtilbudsavisApiError, EtilbudsavisClient, SearchOptions
from .const import CONF_LIST_IDS, CONF_PREFERRED_STORE_IDS, DOMAIN
from .coordinator import ShoppingListsCoordinator
from .saved_searches import (
    async_remove_search,
    async_save_search,
    get_saved_searches,
)
from .offer_actions import async_add_offer_to_list
from .websocket_api import _offer_to_dict


class EtilbudsavisAPI(llm.API):
    """Expose only offer search and selected shopping-list operations."""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass=hass,
            id=DOMAIN,
            name="eTilbudsavis Plus",
            requires_admin=True,
        )

    @override
    async def async_get_api_instance(self, llm_context: llm.LLMContext) -> llm.APIInstance:
        return llm.APIInstance(
            api=self,
            api_prompt=(
                "Use only the selected eTilbudsavis lists returned by these tools. "
                "For a specific search result, use add_offer_to_shopping_list with "
                "the exact query and offer ID from search_offers. Use "
                "add_shopping_list_item only for ordinary text items. Never claim "
                "offer metadata was attached unless the add tool confirms it. Never invent price, "
                "quantity, store, or validity details that are absent from the result."
            ),
            llm_context=llm_context,
            tools=[
                SearchOffersTool(),
                GetSavedSearchesTool(),
                SaveSearchTool(),
                RemoveSavedSearchTool(),
                GetListsTool(),
                GetItemsTool(),
                AddItemTool(),
                AddOfferTool(),
                SetCompletedTool(),
                RemoveItemTool(),
            ],
        )


class SearchOffersTool(llm.Tool):
    """Search current offer results."""

    name = f"{DOMAIN}__search_offers"
    title = "Search eTilbudsavis offers"
    description = "Search current Danish offers, preferring configured stores by default."
    integration = DOMAIN
    annotations = llm.ToolAnnotations(
        read_only=True, destructive=False, idempotent=True, open_world=True
    )
    parameters = probatio.Schema(
        {
            probatio.Required("query", description="Product or brand to search for"): cv.string,
            probatio.Optional("limit", description="Maximum number of results (1–100)"): cv.positive_int,
            probatio.Optional("store_scope", description="Use preferred stores or all stores"): vol.In(
                ["preferred", "all"]
            ),
        }
    )

    @override
    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> llm.ToolResult:
        entry = _first_entry(hass)
        latitude = hass.config.latitude
        longitude = hass.config.longitude
        dealer_ids: tuple[str, ...] = ()
        if entry and tool_input.tool_args.get("store_scope", "preferred") == "preferred":
            dealer_ids = tuple(
                str(value)
                for value in entry.options.get(
                    CONF_PREFERRED_STORE_IDS,
                    entry.data.get(CONF_PREFERRED_STORE_IDS, []),
                )
            )
        options = SearchOptions(
            limit=min(int(tool_input.tool_args.get("limit", 20)), 100),
            latitude=latitude if latitude is not None and longitude is not None else None,
            longitude=longitude if latitude is not None and longitude is not None else None,
            radius_m=25_000 if latitude is not None and longitude is not None else None,
            dealer_ids=dealer_ids,
        )
        client = EtilbudsavisClient(aiohttp_client.async_get_clientsession(hass))
        try:
            offers = await client.search_offers(str(tool_input.tool_args["query"]), options)
        except EtilbudsavisApiError as err:
            raise HomeAssistantError("Offer search failed") from err
        return llm.ToolResult(data={"offers": [_offer_to_dict(offer) for offer in offers]})


class GetListsTool(llm.Tool):
    """List only the shopping lists selected in integration options."""

    name = f"{DOMAIN}__get_shopping_lists"
    title = "Get selected shopping lists"
    description = "Return the eTilbudsavis shopping lists selected for synchronization."
    integration = DOMAIN
    annotations = llm.ToolAnnotations(
        read_only=True, destructive=False, idempotent=True, open_world=False
    )
    parameters = probatio.Schema({})

    @override
    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> llm.ToolResult:
        coordinator = _coordinator(hass)
        return llm.ToolResult(
            data={
                "lists": [
                    {"id": data.list_id, "name": data.name}
                    for data in (coordinator.data or {}).values()
                ]
            }
        )


class GetSavedSearchesTool(llm.Tool):
    """Read saved product searches."""

    name = f"{DOMAIN}__get_saved_searches"
    title = "Get saved product searches"
    description = "Return the user's saved eTilbudsavis product searches."
    integration = DOMAIN
    annotations = llm.ToolAnnotations(
        read_only=True, destructive=False, idempotent=True, open_world=False
    )
    parameters = probatio.Schema({})

    @override
    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> llm.ToolResult:
        return llm.ToolResult(data={"searches": get_saved_searches(hass)})


class SaveSearchTool(llm.Tool):
    """Create or update one saved search."""

    name = f"{DOMAIN}__save_search"
    title = "Save product search"
    description = "Save a product query and optional maximum offer price."
    integration = DOMAIN
    annotations = llm.ToolAnnotations(
        read_only=False, destructive=False, idempotent=False, open_world=False
    )
    parameters = probatio.Schema(
        {
            probatio.Required("name", description="Display name for the saved search"): cv.string,
            probatio.Required("query", description="Product or brand query"): cv.string,
            probatio.Optional("max_price", description="Optional maximum price in DKK"): probatio.All(
                float, probatio.Range(min=0)
            ),
            probatio.Optional("search_id", description="ID to update an existing saved search"): cv.string,
        }
    )

    @override
    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> llm.ToolResult:
        values = tool_input.tool_args
        item = await async_save_search(
            hass,
            name=str(values["name"]),
            query=str(values["query"]),
            max_price=(float(values["max_price"]) if values.get("max_price") is not None else None),
            search_id=values.get("search_id"),
        )
        return llm.ToolResult(data={"search": item})


class RemoveSavedSearchTool(llm.Tool):
    """Remove a saved search by its returned ID."""

    name = f"{DOMAIN}__remove_saved_search"
    title = "Remove saved search"
    description = "Delete one saved product search by its ID."
    integration = DOMAIN
    annotations = llm.ToolAnnotations(
        read_only=False, destructive=True, idempotent=True, open_world=False
    )
    parameters = probatio.Schema(
        {probatio.Required("search_id", description="ID returned by get_saved_searches"): cv.string}
    )

    @override
    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> llm.ToolResult:
        await async_remove_search(hass, str(tool_input.tool_args["search_id"]))
        return llm.ToolResult(data={"success": True})


class GetItemsTool(llm.Tool):
    """Read items in one selected shopping list."""

    name = f"{DOMAIN}__get_shopping_list_items"
    title = "Get shopping-list items"
    description = "Return items from one selected eTilbudsavis shopping list."
    integration = DOMAIN
    annotations = llm.ToolAnnotations(
        read_only=True, destructive=False, idempotent=True, open_world=False
    )
    parameters = probatio.Schema(
        {probatio.Required("list_id", description="ID returned by get_shopping_lists"): cv.positive_int}
    )

    @override
    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> llm.ToolResult:
        data = _selected_list(hass, int(tool_input.tool_args["list_id"]))
        return llm.ToolResult(data={"list_id": data.list_id, "items": list(data.items)})


class AddItemTool(llm.Tool):
    """Add a plain-text item; offer-specific linking is not exposed."""

    name = f"{DOMAIN}__add_shopping_list_item"
    title = "Add shopping-list item"
    description = "Add a plain-text item to a selected list. Does not attach offer metadata."
    integration = DOMAIN
    annotations = llm.ToolAnnotations(
        read_only=False, destructive=False, idempotent=False, open_world=True
    )
    parameters = probatio.Schema(
        {
            probatio.Required("list_id", description="ID returned by get_shopping_lists"): cv.positive_int,
            probatio.Required("name", description="Item name"): cv.string,
            probatio.Optional("count", description="Quantity, 1–99"): cv.positive_int,
            probatio.Optional("note", description="Optional item note"): cv.string,
        }
    )

    @override
    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> llm.ToolResult:
        list_id = int(tool_input.tool_args["list_id"])
        _selected_list(hass, list_id)
        entry = _coordinator(hass).config_entry
        client = _account_client(hass, entry)
        item = await client.add_item(
            list_id,
            str(tool_input.tool_args["name"]),
            count=min(int(tool_input.tool_args.get("count", 1)), 99),
            short_description=str(tool_input.tool_args.get("note", "")),
        )
        await _coordinator(hass).async_request_refresh()
        return llm.ToolResult(data={"item": item, "offer_metadata_attached": False})


class AddOfferTool(llm.Tool):
    """Add a current search result with its offer and store reference."""

    name = f"{DOMAIN}__add_offer_to_shopping_list"
    title = "Add offer to shopping list"
    description = (
        "Add a specific current offer returned by search_offers. Pass its exact offer ID "
        "and the same query; confirms offer/store metadata by reading the item back."
    )
    integration = DOMAIN
    annotations = llm.ToolAnnotations(
        read_only=False, destructive=False, idempotent=False, open_world=True
    )
    parameters = probatio.Schema(
        {
            probatio.Required("list_id", description="ID returned by get_shopping_lists"): cv.positive_int,
            probatio.Required("query", description="Exact query used to find this offer"): cv.string,
            probatio.Required("offer_id", description="Exact offer ID returned by search_offers"): cv.string,
            probatio.Optional("count", description="Quantity, 1–99"): cv.positive_int,
            probatio.Optional("store_scope", description="Use preferred stores or all stores"): vol.In(
                ["preferred", "all"]
            ),
        }
    )

    @override
    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> llm.ToolResult:
        values = tool_input.tool_args
        result = await async_add_offer_to_list(
            hass,
            list_id=int(values["list_id"]),
            query=str(values["query"]),
            offer_id=str(values["offer_id"]),
            count=min(int(values.get("count", 1)), 99),
            store_scope=str(values.get("store_scope", "preferred")),
        )
        return llm.ToolResult(data=result)


class SetCompletedTool(llm.Tool):
    """Change completion for an item known to belong to a selected list."""

    name = f"{DOMAIN}__set_item_completed"
    title = "Mark shopping-list item"
    description = "Mark an item complete or incomplete using its list and client IDs."
    integration = DOMAIN
    annotations = llm.ToolAnnotations(
        read_only=False, destructive=False, idempotent=True, open_world=False
    )
    parameters = probatio.Schema(
        {
            probatio.Required("list_id", description="ID of selected list"): cv.positive_int,
            probatio.Required("client_id", description="clientId from the item result"): cv.string,
            probatio.Required("completed", description="True to check, false to uncheck"): cv.boolean,
        }
    )

    @override
    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> llm.ToolResult:
        list_id = int(tool_input.tool_args["list_id"])
        data = _selected_list(hass, list_id)
        client_id = str(tool_input.tool_args["client_id"])
        item = next(
            (item for item in data.items if str(item.get("clientId")) == client_id),
            None,
        )
        if item is None:
            raise HomeAssistantError("Item does not belong to the selected list")
        await _account_client(hass, _coordinator(hass).config_entry).update_item(
            list_id,
            client_id,
            ticked=bool(tool_input.tool_args["completed"]),
            count=int(item.get("count") or 1),
            short_description=str(item.get("shortDescription") or ""),
        )
        await _coordinator(hass).async_request_refresh()
        return llm.ToolResult(data={"success": True})


class RemoveItemTool(llm.Tool):
    """Delete one item from a selected list."""

    name = f"{DOMAIN}__remove_shopping_list_item"
    title = "Remove shopping-list item"
    description = "Permanently remove one item from a selected list."
    integration = DOMAIN
    annotations = llm.ToolAnnotations(
        read_only=False, destructive=True, idempotent=True, open_world=False
    )
    parameters = probatio.Schema(
        {
            probatio.Required("list_id", description="ID of selected list"): cv.positive_int,
            probatio.Required("item_id", description="ID of the item to remove"): cv.positive_int,
        }
    )

    @override
    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> llm.ToolResult:
        list_id = int(tool_input.tool_args["list_id"])
        item_id = int(tool_input.tool_args["item_id"])
        data = _selected_list(hass, list_id)
        if not any(int(item.get("id", -1)) == item_id for item in data.items):
            raise HomeAssistantError("Item does not belong to the selected list")
        await _account_client(hass, _coordinator(hass).config_entry).remove_item(
            list_id, item_id
        )
        await _coordinator(hass).async_request_refresh()
        return llm.ToolResult(data={"success": True})


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


def _account_client(
    hass: HomeAssistant, entry: Any
) -> EtilbudsavisAccountClient:
    return EtilbudsavisAccountClient(
        aiohttp_client.async_get_clientsession(hass),
        token=entry.data.get("token"),
    )
