"""Offline regressions for API, entity and coordinator boundaries."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from enum import Enum, IntFlag, auto
import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).parents[1] / "custom_components" / "tapo_ir"
PACKAGE = "runtime_test_pkg"


class HAError(Exception):
    pass


class Modes(str, Enum):
    OFF = "off"
    COOL = "cool"
    HEAT = "heat"
    AUTO = "auto"
    FAN_ONLY = "fan_only"
    DRY = "dry"
    HEATING = "heating"
    COOLING = "cooling"
    IDLE = "idle"
    FAN = "fan"
    DRYING = "drying"


class Features(IntFlag):
    TURN_ON = auto()
    TURN_OFF = auto()
    TARGET_TEMPERATURE = auto()
    FAN_MODE = auto()
    SWING_MODE = auto()


class EntryState(Enum):
    LOADED = auto()
    SETUP_RETRY = auto()


class CoordinatorEntity:
    def __class_getitem__(cls, _item):
        return cls

    def __init__(self, coordinator):
        self.coordinator = coordinator

    @property
    def available(self):
        return self.coordinator.last_update_success

    def async_write_ha_state(self):
        pass


class DataCoordinator:
    def __class_getitem__(cls, _item):
        return cls

    def __init__(self, hass, logger, **kwargs):
        self.hass = hass
        self.config_entry = kwargs["config_entry"]
        self.always_update = kwargs["always_update"]
        self.data = {}
        self.last_update_success = True
        self.last_exception = None
        self.shutdown_called = False

    def async_set_updated_data(self, value):
        self.data = value

    async def async_refresh(self):
        try:
            self.data = await self._async_update_data()
            self.last_update_success = True
        except HAError as err:
            self.last_update_success = False
            self.last_exception = err

    async def async_shutdown(self):
        self.shutdown_called = True


class ClimateEntity:
    @property
    def min_temp(self):
        return self._attr_min_temp

    @property
    def max_temp(self):
        return self._attr_max_temp


class Flow:
    def __init_subclass__(cls, **kwargs):
        pass


class Request:
    def __init__(self, method="", params=None):
        self.method = method
        self.params = params

    @classmethod
    def get_child_device_list(cls, index):
        return cls("get_child_device_list", {"start_index": index})


def module(name, **attributes):
    result = ModuleType(name)
    result.__path__ = []
    result.__dict__.update(attributes)
    sys.modules[name] = result
    return result


def load_runtime():
    package = module(PACKAGE)
    package.__path__ = [str(ROOT)]
    module("homeassistant")
    module("homeassistant.core", HomeAssistant=object, callback=lambda fn: fn)
    module("homeassistant.config_entries", ConfigEntry=object, ConfigEntryState=EntryState,
           SIGNAL_CONFIG_ENTRY_CHANGED="entry_changed", ConfigEntryChange=SimpleNamespace(UPDATED="updated"),
           ConfigFlow=Flow, OptionsFlow=Flow, ConfigFlowResult=dict)
    module("homeassistant.const", Platform=SimpleNamespace(BUTTON="button", CLIMATE="climate", REMOTE="remote", SENSOR="sensor"),
           ATTR_TEMPERATURE="temperature", UnitOfTemperature=SimpleNamespace(CELSIUS="C"),
           EVENT_HOMEASSISTANT_STOP="stop")
    module("homeassistant.exceptions", HomeAssistantError=HAError, ConfigEntryAuthFailed=HAError, ConfigEntryNotReady=HAError)
    module("homeassistant.helpers")
    module("homeassistant.helpers.device_registry", DeviceInfo=dict, DeviceEntry=object, async_get=Mock())
    module("homeassistant.helpers.entity_registry", async_get=Mock())
    module("homeassistant.helpers.entity", EntityCategory=SimpleNamespace(CONFIG="config", DIAGNOSTIC="diagnostic"),
           entity_sources=Mock())
    module("homeassistant.helpers.dispatcher", async_dispatcher_connect=Mock())
    module("homeassistant.helpers.typing", ConfigType=dict)
    module("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)
    module("homeassistant.helpers.update_coordinator", CoordinatorEntity=CoordinatorEntity,
           DataUpdateCoordinator=DataCoordinator, UpdateFailed=HAError)
    module("homeassistant.helpers.issue_registry", async_create_issue=Mock(), async_delete_issue=Mock(),
           IssueSeverity=SimpleNamespace(WARNING="warning"))
    module("homeassistant.util")
    module("homeassistant.util.dt", utcnow=lambda: datetime.now(timezone.utc))
    module("homeassistant.components")
    module("homeassistant.components.button", ButtonEntity=type("ButtonEntity", (), {}))
    module("homeassistant.components.remote", RemoteEntity=type("RemoteEntity", (), {}))
    module("homeassistant.components.climate", ClimateEntity=ClimateEntity)
    module("homeassistant.components.climate.const", ClimateEntityFeature=Features, HVACAction=Modes, HVACMode=Modes)
    module(f"{PACKAGE}.compat", TapoRequest=Request, AuthCredential=lambda *args: args,
           DeviceConnectConfiguration=lambda **kwargs: kwargs, connect=AsyncMock())
    selector_names = ("NumberSelector", "NumberSelectorConfig", "SelectSelector", "SelectSelectorConfig",
                      "SelectOptionDict", "TextSelector", "TextSelectorConfig")
    module("homeassistant.helpers.selector", **{name: Mock() for name in selector_names},
           NumberSelectorMode=SimpleNamespace(BOX="box"), SelectSelectorMode=SimpleNamespace(DROPDOWN="dropdown"),
           TextSelectorType=SimpleNamespace(EMAIL="email", PASSWORD="password", TEXT="text"))
    module("voluptuous", Schema=lambda value: value,
           Required=lambda value, **kwargs: value, Optional=lambda value, **kwargs: value,
           All=lambda *args: args, Length=Mock(), Coerce=Mock(), Range=Mock())
    module("homeassistant.helpers.config_validation", string=str, boolean=bool, ensure_list=list)
    module("homeassistant.components.websocket_api", ActiveConnection=object,
           require_admin=lambda fn: fn, websocket_command=lambda schema: lambda fn: fn,
           async_response=lambda fn: fn)
    modules = {
        name: importlib.import_module(f"{PACKAGE}.{name}")
        for name in ("api", "shared_api", "coordinator", "button", "remote", "climate", "config_flow", "websocket")
    }
    module(f"{PACKAGE}.frontend", async_register_frontend=AsyncMock())
    spec = importlib.util.spec_from_file_location(f"{PACKAGE}.lifecycle", ROOT / "__init__.py")
    lifecycle = importlib.util.module_from_spec(spec)
    lifecycle.__package__ = PACKAGE
    spec.loader.exec_module(lifecycle)
    modules["lifecycle"] = lifecycle
    return SimpleNamespace(**modules)


with patch.dict(sys.modules):
    runtime = load_runtime()


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def api(self):
        return runtime.api.TapoIrApi("test.invalid", "test-user", "test-password")

    def coordinator(self, api=None):
        api = api or SimpleNamespace(
            host="test.invalid", hub_id="hub", identifier_domain="tapo_ir",
            hub_name="Hub", hub_model="H110", hub_fw="test", async_close=AsyncMock(),
            async_control_ac=AsyncMock(), async_control_ac_profile=AsyncMock(),
        )
        return runtime.coordinator.TapoIrCoordinator(
            SimpleNamespace(bus=SimpleNamespace(async_fire=Mock())),
            SimpleNamespace(entry_id="ir"), api, 300,
        )

    async def test_direct_pagination_and_duplicate_page_rejection(self):
        api = self.api()
        pages = [
            {"sum": 2, "child_device_list": [{"device_id": "one", "category": "ir.remote"}]},
            {"sum": 2, "child_device_list": [{"device_id": "two", "category": "ir.remote"}]},
        ]
        api._request = AsyncMock(side_effect=pages)
        self.assertEqual(len(await api.async_get_raw_devices()), 2)
        self.assertEqual(api._request.call_args_list[1].args[0].params["start_index"], 1)
        api._request = AsyncMock(side_effect=[pages[0], pages[0]])
        with self.assertRaisesRegex(runtime.api.TapoIrConnectionError, "repeated"):
            await api.async_get_raw_devices()

    async def test_direct_listing_rejects_protocol_errors(self):
        api = self.api()
        api._request = AsyncMock(return_value={"error_code": -1, "child_device_list": []})
        with self.assertRaises(runtime.api.TapoIrConnectionError):
            await api.async_get_raw_devices()

    async def test_runtime_auth_failure_uses_reauth_error(self):
        api = self.api()
        client = SimpleNamespace(execute_raw_request=AsyncMock(side_effect=RuntimeError("authentication failed")))
        api._get_client = AsyncMock(return_value=client)
        api._async_drop_device = AsyncMock()
        with self.assertRaises(runtime.api.TapoIrAuthError):
            await api._request(Request())
        self.assertEqual(client.execute_raw_request.await_count, 1)

    async def test_direct_writes_are_not_retried(self):
        api = self.api()
        client = SimpleNamespace(execute_raw_request=AsyncMock(side_effect=OSError("offline")))
        api._get_client = AsyncMock(return_value=client)
        api._async_drop_device = AsyncMock()
        with self.assertRaises(runtime.api.TapoIrConnectionError):
            await api.async_query_hub("addIrRemoteDevice", {})
        self.assertEqual(client.execute_raw_request.await_count, 1)

    async def test_cancelled_direct_request_drops_session(self):
        api = self.api()
        client = SimpleNamespace(execute_raw_request=AsyncMock(side_effect=asyncio.CancelledError()))
        api._get_client = AsyncMock(return_value=client)
        api._async_drop_device = AsyncMock()
        with self.assertRaises(asyncio.CancelledError):
            await api._request(Request())
        api._async_drop_device.assert_awaited_once()

    async def test_direct_validation_closes_success_and_failure(self):
        for failure in (None, runtime.api.TapoIrConnectionError("offline")):
            api = SimpleNamespace(async_connect=AsyncMock(side_effect=failure),
                                  async_enumerate=AsyncMock(), async_close=AsyncMock())
            with patch.object(runtime.config_flow, "TapoIrApi", return_value=api):
                if failure:
                    with self.assertRaises(runtime.api.TapoIrConnectionError):
                        await runtime.config_flow._validate_direct({"host": "host", "username": "user", "password": "test"})
                else:
                    self.assertIs(await runtime.config_flow._validate_direct(
                        {"host": "host", "username": "user", "password": "test"}), api)
            api.async_close.assert_awaited_once()

    async def test_initial_flow_keeps_direct_connection_option(self):
        flow = runtime.config_flow.TapoIrConfigFlow()
        flow.hass = object()
        flow.async_show_form = Mock(return_value={})
        hubs = [SimpleNamespace(entry_id="hub")]
        with patch.object(runtime.config_flow, "discover_shared_hubs", return_value=hubs), \
             patch.object(runtime.config_flow, "_shared_schema", return_value={}) as schema:
            await flow.async_step_user()
        schema.assert_called_once_with(hubs)

    async def test_failed_setup_closes_direct_client(self):
        api = SimpleNamespace(async_connect=AsyncMock(side_effect=runtime.api.TapoIrConnectionError("offline")),
                              async_close=AsyncMock())
        entry = SimpleNamespace(options={}, data={}, entry_id="entry", title="Hub")
        with patch.object(runtime.lifecycle, "_build_api", return_value=api):
            with self.assertRaises(HAError):
                await runtime.lifecycle.async_setup_entry(object(), entry)
        api.async_close.assert_awaited_once()

    async def test_failed_first_refresh_shuts_down_coordinator(self):
        api = SimpleNamespace(async_connect=AsyncMock(), async_close=AsyncMock())
        coordinator = SimpleNamespace(async_config_entry_first_refresh=AsyncMock(side_effect=HAError("offline")),
                                      async_shutdown=AsyncMock())
        entry = SimpleNamespace(options={}, data={}, entry_id="entry", title="Hub")
        with patch.object(runtime.lifecycle, "_build_api", return_value=api), \
             patch.object(runtime.lifecycle, "TapoIrCoordinator", return_value=coordinator):
            with self.assertRaises(HAError):
                await runtime.lifecycle.async_setup_entry(object(), entry)
        coordinator.async_shutdown.assert_awaited_once()

    async def test_shared_refresh_is_fresh_and_checks_health(self):
        hub = SimpleNamespace(children=[])
        parent = SimpleNamespace(device=hub, last_update_success=True,
                                 async_refresh=AsyncMock(), async_request_refresh=AsyncMock())
        entry = SimpleNamespace(state=EntryState.LOADED, runtime_data=SimpleNamespace(parent_coordinator=parent),
                                title="Hub", entry_id="core")
        hass = SimpleNamespace(config_entries=SimpleNamespace(async_get_entry=lambda _: entry))
        api = runtime.shared_api.TapoIrSharedApi(hass, "core")
        self.assertEqual(await api.async_get_raw_devices(), [])
        parent.async_refresh.assert_awaited_once()
        parent.async_request_refresh.assert_not_awaited()
        parent.last_update_success = False
        with self.assertRaises(runtime.api.TapoIrConnectionError):
            await api.async_get_raw_devices()

    async def test_coordinator_shutdown_and_timestamp_notifications(self):
        coordinator = self.coordinator()
        self.assertTrue(coordinator.always_update)
        await coordinator.async_shutdown()
        self.assertTrue(coordinator.shutdown_called)
        coordinator.api.async_close.assert_awaited_once()

    async def test_concurrent_ac_changes_preserve_both_fields(self):
        coordinator = self.coordinator()
        coordinator.data = {"ac": {"ac_state": {"P": 1, "M": 0, "T": 22, "S": 1, "D": 0}}}

        async def send(*args, **kwargs):
            await asyncio.sleep(0)

        coordinator.api.async_control_ac.side_effect = send
        await asyncio.gather(
            coordinator.async_control_ac("ac", temp=24),
            coordinator.async_control_ac("ac", wind_speed=3),
        )
        state = coordinator.data["ac"]["ac_state"]
        self.assertEqual((state["T"], state["S"]), (24, 3))

    async def test_post_write_refresh_failure_is_not_silent(self):
        coordinator = self.coordinator()
        coordinator.api.async_enumerate = AsyncMock(side_effect=runtime.api.TapoIrConnectionError("offline"))
        with self.assertRaisesRegex(HAError, "write completed"):
            await coordinator.async_refresh_after_mutation()

    async def test_numeric_key_identity_survives_protocol_rename(self):
        coordinator = self.coordinator()
        key = {"id": 1, "name": "old", "label": "Power", "icon": "mdi:power"}
        device = {"device_id": "remote", "name": "Remote", "keys": [key]}
        button = runtime.button.TapoIrKeyButton(coordinator, device, key, "remote_key_1")
        coordinator.data = {"remote": {**device, "keys": [{**key, "name": "new"}]}}
        coordinator.async_fire = AsyncMock()
        self.assertTrue(button.available)
        await button.async_press()
        coordinator.async_fire.assert_awaited_once_with("remote", "new")

    async def test_remote_resolves_exact_names_and_validates_before_transmission(self):
        coordinator = self.coordinator()
        keys = [
            {"name": "power", "label": "Source", "slug": "source"},
            {"name": "source", "label": "Input", "slug": "input"},
        ]
        device = {"device_id": "remote", "name": "Remote", "keys": keys}
        coordinator.data = {"remote": device}
        remote = runtime.remote.TapoIrRemote(coordinator, device)
        remote.entity_id = "remote.test"
        coordinator.async_fire = AsyncMock()
        self.assertEqual(remote._resolve_key("source"), "source")
        with self.assertRaises(HAError):
            await remote.async_send_command(["power", "invalid"])
        coordinator.async_fire.assert_not_awaited()
        with patch.object(runtime.remote.asyncio, "sleep", new_callable=AsyncMock) as sleep:
            await remote.async_send_command(["power"], num_repeats=2, delay_secs=1)
            sleep.assert_awaited_once_with(1)

    async def test_climate_unknown_and_combined_mode_temperature(self):
        coordinator = self.coordinator()
        device = {"device_id": "ac", "name": "AC", "ac_state": {}}
        coordinator.data = {"ac": device}
        climate = runtime.climate.TapoIrAcClimate(coordinator, device)
        self.assertIsNone(climate.hvac_mode)
        self.assertIsNone(climate.hvac_action)
        coordinator.async_control_ac = AsyncMock()
        await climate.async_set_temperature(temperature=23, hvac_mode=Modes.HEAT)
        coordinator.async_control_ac.assert_awaited_once_with(
            "ac",
            pressed_fid=3,
            use_mitsubishi_max=None,
            temp=23,
            power=True,
            mode=1,
        )

    async def test_inventory_isolates_failed_hubs(self):
        good, bad = self.coordinator(), self.coordinator()
        good.manager.async_configuration = AsyncMock(return_value=[])
        bad.manager.async_configuration = AsyncMock(side_effect=HAError("offline"))
        entries = [
            SimpleNamespace(entry_id=name, title=name, state=EntryState.LOADED, runtime_data=item, data={})
            for name, item in (("bad", bad), ("good", good))
        ]
        hass = SimpleNamespace(config_entries=SimpleNamespace(async_entries=lambda _: entries))
        connection = SimpleNamespace(send_result=Mock(), send_error=Mock())
        await runtime.websocket.ws_list(hass, connection, {"id": 1})
        result = connection.send_result.call_args.args[1]
        self.assertEqual([hub["entry_id"] for hub in result["hubs"]], ["good"])
        self.assertEqual(result["errors"][0]["entry_id"], "bad")

    async def test_delete_websocket_requires_confirmation_and_refreshes(self):
        coordinator = self.coordinator()
        coordinator.manager.async_delete_key = AsyncMock(
            return_value={"deleted_key_name": "source", "verified": True}
        )
        coordinator.async_refresh_after_mutation = AsyncMock()
        connection = SimpleNamespace(send_result=Mock(), send_error=Mock())
        message = {"id": 1, "remote_device_id": "remote", "key_reference": "source", "confirmation": ""}
        with patch.object(runtime.websocket, "_remote_coordinator", return_value=coordinator) as resolve:
            await runtime.websocket.ws_delete_key(object(), connection, message)
            resolve.assert_not_called()
            coordinator.manager.async_delete_key.assert_not_awaited()
            self.assertEqual(connection.send_error.call_args.args[1], "confirmation_required")
            connection.send_error.reset_mock()
            await runtime.websocket.ws_delete_key(object(), connection, {**message, "confirmation": "DELETE"})
            resolve.assert_called_once()
            coordinator.manager.async_delete_key.assert_awaited_once_with("remote", "source")
            coordinator.async_refresh_after_mutation.assert_awaited_once()
            connection.send_error.assert_not_called()
            self.assertTrue(connection.send_result.call_args.args[1]["verified"])
            connection.send_result.reset_mock()
            coordinator.manager.async_delete_key.side_effect = HAError("Delete rejected")
            await runtime.websocket.ws_delete_key(object(), connection, {**message, "confirmation": "DELETE"})
            connection.send_result.assert_not_called()
            self.assertEqual(connection.send_error.call_args.args[2], "Delete rejected")

    async def test_stop_is_scoped_to_requested_hub(self):
        selected, other = self.coordinator(), self.coordinator()
        selected.manager.async_stop_learning = AsyncMock(return_value=True)
        other.manager.async_stop_learning = AsyncMock(return_value=True)
        connection = SimpleNamespace(send_result=Mock(), send_error=Mock())
        with patch.object(runtime.websocket, "_entry_coordinator", return_value=selected):
            await runtime.websocket.ws_stop_learn(object(), connection, {"id": 1, "entry_id": "selected"})
        selected.manager.async_stop_learning.assert_awaited_once()
        other.manager.async_stop_learning.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
