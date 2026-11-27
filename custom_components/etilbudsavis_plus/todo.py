"""Native todo entities for the selected eTilbudsavis shopping lists."""

from __future__ import annotations

import json
import re
from typing import Any

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ShoppingListData, ShoppingListsCoordinator

_COUNT_PREFIX = re.compile(r"^(\d+)x\s+(.+)$", re.IGNORECASE)
_NOTE_SUFFIX = re.compile(r"^(.*?)\s+\((.+)\)$")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one todo entity per selected list."""
    coordinator: ShoppingListsCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        EtilbudsavisTodoList(coordinator, list_id, list_data)
        for list_id, list_data in coordinator.data.items()
    )


class EtilbudsavisTodoList(
    CoordinatorEntity[ShoppingListsCoordinator], TodoListEntity
):
    """Expose one eTilbudsavis list as Home Assistant's native todo entity."""

    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
    )

    def __init__(
        self,
        coordinator: ShoppingListsCoordinator,
        list_id: int,
        list_data: ShoppingListData,
    ) -> None:
        super().__init__(coordinator)
        self._list_id = list_id
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{list_id}"
        self._attr_name = list_data.name
        self._attr_icon = "mdi:cart-outline"

    @property
    def _list_data(self) -> ShoppingListData | None:
        return (self.coordinator.data or {}).get(self._list_id)

    @property
    def todo_items(self) -> list[TodoItem]:
        """Return active upstream items with checked state and quantity."""
        if self._list_data is None:
            return []
        items: list[TodoItem] = []
        for item in self._list_data.items:
            if not item.get("isActive", True):
                continue
            item_id = item.get("id")
            client_id = item.get("clientId")
            if item_id is None:
                continue
            count = item.get("count") or 1
            name = str(item.get("name") or "")
            note = str(item.get("shortDescription") or "")
            summary = f"{count}x {name}"
            if note:
                summary = f"{summary} ({note})"
            items.append(
                TodoItem(
                    uid=_encode_uid(item_id, client_id),
                    summary=summary,
                    status=(
                        TodoItemStatus.COMPLETED
                        if item.get("ticked", False)
                        else TodoItemStatus.NEEDS_ACTION
                    ),
                    description=_item_description(item),
                )
            )
        return sorted(
            items,
            key=lambda item: (
                item.status == TodoItemStatus.COMPLETED,
                item.summary.casefold(),
            ),
        )

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Add a plain text item to the selected upstream list."""
        count, name, note = _parse_summary(item.summary)
        await self.coordinator.client.add_item(
            self._list_id,
            name,
            count=count,
            short_description=note,
        )
        await self.coordinator.async_request_refresh()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Remove selected items from the upstream list."""
        for uid in uids:
            item_id, _client_id = _decode_uid(uid)
            await self.coordinator.client.remove_item(self._list_id, item_id)
        await self.coordinator.async_request_refresh()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Update quantity, note or completion when supported upstream."""
        item_id, client_id = _decode_uid(item.uid)
        current = next(
            (
                candidate
                for candidate in (self._list_data.items if self._list_data else ())
                if str(candidate.get("id")) == str(item_id)
            ),
            None,
        )
        if current is None:
            raise HomeAssistantError("The shopping-list item no longer exists")
        if not client_id:
            raise HomeAssistantError("The upstream item cannot be updated without its client id")

        count, name, note = _parse_summary(item.summary)
        await self.coordinator.client.update_item(
            self._list_id,
            client_id,
            ticked=item.status == TodoItemStatus.COMPLETED,
            count=count,
            short_description=note,
            name=name,
        )
        await self.coordinator.async_request_refresh()


def _encode_uid(item_id: Any, client_id: Any) -> str:
    return json.dumps(
        {"id": str(item_id), "client_id": str(client_id or "")},
        separators=(",", ":"),
    )


def _decode_uid(uid: str) -> tuple[int, str]:
    try:
        value = json.loads(uid)
        if not isinstance(value, dict) or "id" not in value:
            raise ValueError
        return int(value["id"]), str(value.get("client_id") or "")
    except (json.JSONDecodeError, ValueError, TypeError) as err:
        raise HomeAssistantError("Invalid eTilbudsavis todo item identifier") from err


def _parse_summary(summary: str) -> tuple[int, str, str]:
    value = summary.strip()
    count = 1
    if match := _COUNT_PREFIX.match(value):
        count = int(match.group(1))
        value = match.group(2).strip()
    note = ""
    if match := _NOTE_SUFFIX.match(value):
        value, note = match.group(1).strip(), match.group(2).strip()
    if not value:
        raise HomeAssistantError("Shopping-list item name must not be empty")
    return count, value, note


def _item_description(item: dict[str, Any]) -> str | None:
    business = item.get("business")
    if isinstance(business, dict) and business.get("name"):
        return str(business["name"])
    return None
