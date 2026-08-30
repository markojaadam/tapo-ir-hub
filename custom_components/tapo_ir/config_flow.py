"""Config and options flows for Tapo IR Hub."""
from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    SelectOptionDict,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import TapoIrApi, TapoIrAuthError, TapoIrError
from .const import (
    CONF_CONNECTION_MODE,
    CONF_HOST,
    CONF_NAME_OVERRIDES,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_TPLINK_ENTRY_ID,
    CONF_USERNAME,
    CONNECTION_MODE_DIRECT,
    CONNECTION_MODE_SHARED,
    DEFAULT_SCAN_INTERVAL,
    DIRECT_CONNECTION_OPTION,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)
from .shared_api import SharedHub, discover_shared_hubs

_LOGGER = logging.getLogger(__name__)


def _connection_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST): TextSelector(),
            vol.Required(CONF_USERNAME): TextSelector(
                TextSelectorConfig(type=TextSelectorType.EMAIL)
            ),
            vol.Required(CONF_PASSWORD): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
        }
    )


def _credentials_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_USERNAME): TextSelector(
                TextSelectorConfig(type=TextSelectorType.EMAIL)
            ),
            vol.Required(CONF_PASSWORD): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
        }
    )


def _options_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_SCAN_INTERVAL): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_SCAN_INTERVAL,
                    max=3600,
                    step=10,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="s",
                )
            ),
            vol.Optional(CONF_NAME_OVERRIDES): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True)
            ),
        }
    )


def _shared_schema(
    hubs: list[SharedHub], *, include_direct: bool = True
) -> vol.Schema:
    options = [
        SelectOptionDict(
            value=hub.entry_id,
            label=f"{hub.name} ({hub.host or 'local'})",
        )
        for hub in hubs
    ]
    if include_direct:
        options.append(
            SelectOptionDict(
                value=DIRECT_CONNECTION_OPTION,
                label="Connect directly with Tapo credentials",
            )
        )
    return vol.Schema(
        {
            vol.Required(CONF_TPLINK_ENTRY_ID): SelectSelector(
                SelectSelectorConfig(
                    options=options,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
        }
    )


async def _validate_direct(data: dict[str, Any]) -> TapoIrApi:
    api = TapoIrApi(
        host=data[CONF_HOST],
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
    )
    try:
        await api.async_connect()
        await api.async_enumerate()
        return api
    except Exception:
        await api.async_close()
        raise


def _validate_overrides(raw: str) -> str | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return "invalid_overrides"
    return None if isinstance(parsed, dict) else "invalid_overrides"


class TapoIrConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure shared-session or direct access to one IR hub."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        hubs = discover_shared_hubs(self.hass)
        if not hubs:
            return await self.async_step_direct(user_input)
        if user_input is not None:
            selected = user_input[CONF_TPLINK_ENTRY_ID]
            if selected == DIRECT_CONNECTION_OPTION:
                return await self.async_step_direct()
            hub = next((item for item in hubs if item.entry_id == selected), None)
            if hub is None:
                return self.async_show_form(
                    step_id="user",
                    data_schema=_shared_schema(hubs, include_direct=False),
                    errors={"base": "shared_hub_unavailable"},
                )
            await self.async_set_unique_id(hub.hub_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=hub.name,
                data={
                    CONF_CONNECTION_MODE: CONNECTION_MODE_SHARED,
                    CONF_TPLINK_ENTRY_ID: hub.entry_id,
                },
            )
        return self.async_show_form(
            step_id="user",
            data_schema=_shared_schema(hubs),
        )

    async def async_step_direct(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None and CONF_HOST in user_input:
            try:
                api = await _validate_direct(user_input)
            except TapoIrAuthError:
                errors["base"] = "invalid_auth"
            except TapoIrError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error validating Tapo IR hub")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(api.hub_id)
                self._abort_if_unique_id_configured()
                await api.async_close()
                return self.async_create_entry(
                    title=api.hub_name,
                    data={
                        **user_input,
                        CONF_CONNECTION_MODE: CONNECTION_MODE_DIRECT,
                    },
                )
        return self.async_show_form(
            step_id="direct",
            data_schema=self.add_suggested_values_to_schema(
                _connection_schema(), user_input or {}
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        if entry_data.get(CONF_CONNECTION_MODE) == CONNECTION_MODE_SHARED:
            return self.async_abort(reason="reauth_not_required")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            merged = {**entry.data, **user_input}
            try:
                api = await _validate_direct(merged)
            except TapoIrAuthError:
                errors["base"] = "invalid_auth"
            except TapoIrError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(api.hub_id)
                self._abort_if_unique_id_mismatch(reason="wrong_hub")
                await api.async_close()
                return self.async_update_reload_and_abort(entry, data=merged)
        suggested = {CONF_USERNAME: entry.data.get(CONF_USERNAME, "")}
        if user_input:
            suggested.update(user_input)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                _credentials_schema(), suggested
            ),
            errors=errors,
            description_placeholders={CONF_HOST: entry.data.get(CONF_HOST, "")},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        if entry.data.get(CONF_CONNECTION_MODE) == CONNECTION_MODE_SHARED:
            hubs = discover_shared_hubs(self.hass)
            if user_input is not None:
                selected = user_input[CONF_TPLINK_ENTRY_ID]
                hub = next(
                    (item for item in hubs if item.entry_id == selected), None
                )
                if hub is None:
                    return self.async_show_form(
                        step_id="reconfigure",
                        data_schema=_shared_schema(hubs),
                        errors={"base": "shared_hub_unavailable"},
                    )
                await self.async_set_unique_id(hub.hub_id)
                self._abort_if_unique_id_mismatch(reason="wrong_hub")
                return self.async_update_reload_and_abort(
                    entry,
                    data={
                        CONF_CONNECTION_MODE: CONNECTION_MODE_SHARED,
                        CONF_TPLINK_ENTRY_ID: selected,
                    },
                )
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=self.add_suggested_values_to_schema(
                    _shared_schema(hubs, include_direct=False),
                    {CONF_TPLINK_ENTRY_ID: entry.data[CONF_TPLINK_ENTRY_ID]},
                ),
            )
        return await self._async_reconfigure_direct(entry, user_input)

    async def _async_reconfigure_direct(
        self,
        entry: ConfigEntry,
        user_input: dict[str, Any] | None,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                api = await _validate_direct(user_input)
            except TapoIrAuthError:
                errors["base"] = "invalid_auth"
            except TapoIrError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(api.hub_id)
                self._abort_if_unique_id_mismatch(reason="wrong_hub")
                await api.async_close()
                return self.async_update_reload_and_abort(
                    entry,
                    data={
                        **user_input,
                        CONF_CONNECTION_MODE: CONNECTION_MODE_DIRECT,
                    },
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                _connection_schema(), user_input or dict(entry.data)
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return TapoIrOptionsFlow()


class TapoIrOptionsFlow(OptionsFlow):
    """Configure scan interval and explicit remote-name overrides."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := _validate_overrides(
                user_input.get(CONF_NAME_OVERRIDES, "")
            ):
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                        CONF_NAME_OVERRIDES: (
                            user_input.get(CONF_NAME_OVERRIDES, "") or ""
                        ).strip(),
                    },
                )
        suggested = {
            CONF_SCAN_INTERVAL: self.config_entry.options.get(
                CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
            ),
            CONF_NAME_OVERRIDES: self.config_entry.options.get(
                CONF_NAME_OVERRIDES, ""
            ),
        }
        if user_input:
            suggested.update(user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                _options_schema(), suggested
            ),
            errors=errors,
        )
