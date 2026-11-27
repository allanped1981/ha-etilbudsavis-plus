"""Shared persistent saved-search operations for the dashboard and MCP tools."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

STORAGE_VERSION = 1
DATA_KEY = "saved_searches"
STORE_KEY = f"{DATA_KEY}_store"


async def async_setup(hass: HomeAssistant) -> None:
    """Load saved searches once during integration setup."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{DATA_KEY}")
    value = await store.async_load()
    domain_data[DATA_KEY] = value if isinstance(value, dict) else {"items": []}
    domain_data[STORE_KEY] = store


def get_saved_searches(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Return saved searches in stable insertion order."""
    data = hass.data.get(DOMAIN, {}).get(DATA_KEY, {"items": []})
    items = data.get("items", []) if isinstance(data, dict) else []
    return [item for item in items if isinstance(item, dict)]


async def async_save_search(
    hass: HomeAssistant,
    *,
    name: str,
    query: str,
    max_price: float | None = None,
    search_id: str | None = None,
) -> dict[str, Any]:
    """Create or update a saved product search."""
    domain_data = hass.data[DOMAIN]
    search_id = search_id or str(uuid4())
    item = {
        "id": search_id,
        "name": name.strip(),
        "query": query.strip(),
        "max_price": max_price,
    }
    items = [existing for existing in get_saved_searches(hass) if existing.get("id") != search_id]
    items.append(item)
    domain_data[DATA_KEY] = {"items": items}
    await domain_data[STORE_KEY].async_save(domain_data[DATA_KEY])
    return item


async def async_remove_search(hass: HomeAssistant, search_id: str) -> None:
    """Delete one saved product search."""
    domain_data = hass.data[DOMAIN]
    items = [item for item in get_saved_searches(hass) if item.get("id") != search_id]
    domain_data[DATA_KEY] = {"items": items}
    await domain_data[STORE_KEY].async_save(domain_data[DATA_KEY])
