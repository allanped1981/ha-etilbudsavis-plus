"""eTilbudsavis Plus Home Assistant integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant import config_entries
    from homeassistant.core import HomeAssistant

from .const import DOMAIN

PLATFORMS = ["todo"]


async def async_setup(hass: HomeAssistant, config: dict[str, object]) -> bool:
    """Set up API commands and the dashboard card static path."""
    from pathlib import Path

    from homeassistant.components.http import StaticPathConfig

    from .websocket_api import async_setup as async_setup_websocket_api

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                "/etilbudsavis_plus",
                str(Path(__file__).parent / "www"),
                False,
            )
        ]
    )
    await async_setup_websocket_api(hass)
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    """Set up selected eTilbudsavis shopping lists."""
    from homeassistant.helpers import aiohttp_client, llm

    from .account_api import EtilbudsavisAccountClient
    from .coordinator import ShoppingListsCoordinator
    from .llm_api import EtilbudsavisAPI

    client = EtilbudsavisAccountClient(
        aiohttp_client.async_get_clientsession(hass),
        token=entry.data.get("token"),
    )
    coordinator = ShoppingListsCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.api_unload = llm.async_register_api(hass, EtilbudsavisAPI(hass))
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    """Unload selected shopping-list entities."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id, None)
        if coordinator and (unregister := getattr(coordinator, "api_unload", None)):
            unregister()
    return unloaded


async def async_update_options(
    hass: HomeAssistant, entry: config_entries.ConfigEntry
) -> None:
    """Reload entities after a list selection change."""
    from homeassistant import config_entries

    await hass.config_entries.async_reload(entry.entry_id)
