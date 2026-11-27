"""Home Assistant setup and options flows."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL
from homeassistant.core import callback
from homeassistant.helpers import aiohttp_client, selector

from .account_api import (
    AccountApiError,
    AccountAuthenticationError,
    EtilbudsavisAccountClient,
)
from .api import EtilbudsavisApiError, EtilbudsavisClient
from .const import (
    CONF_LIST_IDS,
    CONF_OTP,
    CONF_PREFERRED_STORE_IDS,
    DOMAIN,
)


class EtilbudsavisPlusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure account authentication and the lists to synchronize."""

    VERSION = 1

    def __init__(self) -> None:
        self._email = ""
        self._otp_id = ""
        self._token = ""
        self._lists: list[dict[str, Any]] = []
        self._stores: list[dict[str, Any]] = []
        self._reauth_entry: config_entries.ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._email = user_input[CONF_EMAIL].strip()
            if not self._email:
                errors["invalid_auth"] = "invalid_auth"
            else:
                await self.async_set_unique_id(self._email.casefold())
                self._abort_if_unique_id_configured()
                try:
                    client = self._client()
                    self._otp_id = await client.request_otp(self._email)
                    return await self.async_step_otp()
                except AccountAuthenticationError:
                    errors["invalid_auth"] = "invalid_auth"
                except AccountApiError:
                    errors["cannot_connect"] = "cannot_connect"
                except (TimeoutError, OSError):
                    errors["cannot_connect"] = "cannot_connect"

        data_schema = vol.Schema(
            {
                vol.Required(CONF_EMAIL): str,
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    async def async_step_otp(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                client = self._client()
                self._token = await client.verify_otp(self._otp_id, user_input[CONF_OTP])
                if self._reauth_entry is not None:
                    return self.async_update_reload_and_abort(
                        self._reauth_entry,
                        data_updates={"token": self._token},
                        reason="reauth_successful",
                    )
                self._lists = await client.get_shopping_lists()
                try:
                    offer_client = EtilbudsavisClient(
                        aiohttp_client.async_get_clientsession(self.hass)
                    )
                    self._stores = [
                        {"id": store.store_id, "name": store.name}
                        for store in await offer_client.list_stores()
                    ]
                except EtilbudsavisApiError:
                    self._stores = []
                return await self.async_step_select_lists()
            except AccountAuthenticationError:
                errors["invalid_auth"] = "invalid_auth"
            except AccountApiError:
                errors["cannot_connect"] = "cannot_connect"
            except (TimeoutError, OSError):
                errors["cannot_connect"] = "cannot_connect"

        return self.async_show_form(
            step_id="otp",
            data_schema=vol.Schema({vol.Required(CONF_OTP): str}),
            errors=errors,
            description_placeholders={"email": self._email},
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Start a new email code flow for an expired session."""
        self._reauth_entry = self._get_reauth_entry()
        self._email = str(entry_data[CONF_EMAIL])
        try:
            self._otp_id = await self._client().request_otp(self._email)
            return await self.async_step_otp()
        except AccountAuthenticationError:
            return self.async_abort(reason="invalid_auth")
        except AccountApiError:
            return self.async_abort(reason="cannot_connect")
        except (TimeoutError, OSError):
            return self.async_abort(reason="cannot_connect")

    async def async_step_select_lists(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            selected = [str(item) for item in user_input[CONF_LIST_IDS]]
            return self.async_create_entry(
                title=self._email,
                data={
                    CONF_EMAIL: self._email,
                    "token": self._token,
                    CONF_LIST_IDS: selected,
                    CONF_PREFERRED_STORE_IDS: [
                        str(item) for item in user_input[CONF_PREFERRED_STORE_IDS]
                    ],
                },
            )

        options = [
            {
                "value": str(item.get("id")),
                "label": str(item.get("name") or item.get("title") or item.get("id")),
            }
            for item in self._lists
            if item.get("id") is not None
        ]
        if not options:
            return self.async_abort(reason="no_lists_found")
        stores = [
            {"value": str(item["id"]), "label": item["name"]}
            for item in self._stores
            if item.get("id") is not None and item.get("name")
        ]
        data_schema = vol.Schema(
            {
                vol.Required(CONF_LIST_IDS, default=[]): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_PREFERRED_STORE_IDS, default=[]): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=stores,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="select_lists", data_schema=data_schema)

    def _client(self) -> EtilbudsavisAccountClient:
        return EtilbudsavisAccountClient(
            aiohttp_client.async_get_clientsession(self.hass),
            token=self._token or None,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> EtilbudsavisPlusOptionsFlow:
        return EtilbudsavisPlusOptionsFlow()


class EtilbudsavisPlusOptionsFlow(config_entries.OptionsFlow):
    """Select which account lists are synchronized."""

    def __init__(self) -> None:
        self._lists: list[dict[str, Any]] = []

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_LIST_IDS: [str(item) for item in user_input[CONF_LIST_IDS]],
                    CONF_PREFERRED_STORE_IDS: [
                        str(item) for item in user_input[CONF_PREFERRED_STORE_IDS]
                    ],
                }
            )

        try:
            client = EtilbudsavisAccountClient(
                aiohttp_client.async_get_clientsession(self.hass),
                token=self.config_entry.data.get("token"),
            )
            self._lists = await client.get_shopping_lists()
            offer_client = EtilbudsavisClient(
                aiohttp_client.async_get_clientsession(self.hass)
            )
            stores = await offer_client.list_stores()
        except AccountAuthenticationError:
            return self.async_abort(reason="invalid_auth")
        except AccountApiError:
            return self.async_abort(reason="cannot_connect")
        except EtilbudsavisApiError:
            return self.async_abort(reason="cannot_connect")
        except (TimeoutError, OSError):
            return self.async_abort(reason="cannot_connect")

        options = [
            {
                "value": str(item.get("id")),
                "label": str(item.get("name") or item.get("title") or item.get("id")),
            }
            for item in self._lists
            if item.get("id") is not None
        ]
        store_options = [
            {"value": store.store_id, "label": store.name} for store in stores
        ]
        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_LIST_IDS,
                    default=self.config_entry.options.get(
                        CONF_LIST_IDS, self.config_entry.data.get(CONF_LIST_IDS, [])
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_PREFERRED_STORE_IDS,
                    default=self.config_entry.options.get(
                        CONF_PREFERRED_STORE_IDS,
                        self.config_entry.data.get(CONF_PREFERRED_STORE_IDS, []),
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=store_options,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=data_schema)
