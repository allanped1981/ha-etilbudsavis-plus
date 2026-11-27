"""Redacted Home Assistant diagnostics."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_LIST_IDS, CONF_PREFERRED_STORE_IDS


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return useful configuration state without account credentials."""
    return {
        "email_configured": bool(entry.data.get("email")),
        "session_configured": bool(entry.data.get("token")),
        "selected_list_count": len(
            entry.options.get(CONF_LIST_IDS, entry.data.get(CONF_LIST_IDS, []))
        ),
        "preferred_store_count": len(
            entry.options.get(
                CONF_PREFERRED_STORE_IDS,
                entry.data.get(CONF_PREFERRED_STORE_IDS, []),
            )
        ),
        "version": entry.version,
    }
