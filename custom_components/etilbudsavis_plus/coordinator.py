"""Account shopping-list data coordination and refresh throttling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .account_api import (
    AccountApiError,
    AccountAuthenticationError,
    EtilbudsavisAccountClient,
)
from .const import CONF_LIST_IDS, DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ShoppingListData:
    """One selected upstream list and its latest items."""

    list_id: int
    name: str
    items: tuple[dict[str, Any], ...]


class ShoppingListsCoordinator(DataUpdateCoordinator[dict[int, ShoppingListData]]):
    """Refresh only selected shopping lists at a conservative interval."""

    config_entry: ConfigEntry
    client: EtilbudsavisAccountClient

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: EtilbudsavisAccountClient,
    ) -> None:
        self.config_entry = entry
        self.client = client
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=5),
        )

    async def _async_update_data(self) -> dict[int, ShoppingListData]:
        selected = {
            int(list_id)
            for list_id in self.config_entry.options.get(
                CONF_LIST_IDS, self.config_entry.data.get(CONF_LIST_IDS, [])
            )
        }
        if not selected:
            return {}
        try:
            upstream_lists = await self.client.get_shopping_lists()
            metadata = {
                int(item["id"]): item
                for item in upstream_lists
                if item.get("id") is not None
            }
            result: dict[int, ShoppingListData] = {}
            for list_id in sorted(selected):
                items = await self.client.get_shopping_list_items(list_id)
                list_metadata = metadata.get(list_id, {})
                name = str(list_metadata.get("name") or list_metadata.get("title") or list_id)
                result[list_id] = ShoppingListData(list_id, name, tuple(items))
            return result
        except AccountAuthenticationError as err:
            raise ConfigEntryAuthFailed("eTilbudsavis session expired; reauthentication required") from err
        except AccountApiError as err:
            raise UpdateFailed("Unable to refresh eTilbudsavis shopping lists") from err
