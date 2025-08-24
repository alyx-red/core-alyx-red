"""The (custom) fitbit component."""
from __future__ import annotations

import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)
_LOGGER.warning("✅ Loaded CUSTOM Fitbit integration (with flow logging)")

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.config_entry_oauth2_flow import OAuth2FlowHandler

from . import api
from .const import FitbitScope
from .coordinator import FitbitConfigEntry, FitbitData, FitbitDeviceCoordinator
from .exceptions import FitbitApiException, FitbitAuthException
from .model import config_from_entry_data

# ---------- Verbose masked flow logging ----------
def _mask(v: Any) -> str:
    if v is None:
        return "<none>"
    if isinstance(v, (bytes, bytearray)):
        try:
            v = v.decode(errors="ignore")
        except Exception:
            v = str(v)
    s = str(v)
    return (s[:3] + "*" * 6) if len(s) >= 3 else s + "*" * 6

def _mask_recursive(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in {"access_token", "refresh_token", "id_token", "code", "client_secret"}:
                out[k] = _mask(v)
            else:
                out[k] = _mask_recursive(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [_mask_recursive(x) for x in obj]
    return obj

# Patch once to log what the OAuth flow hands to create_entry (masked)
if not getattr(OAuth2FlowHandler, "_fitbit_logged", False):
    _orig_create_entry = OAuth2FlowHandler.async_oauth_create_entry

    async def _logged_async_oauth_create_entry(self: OAuth2FlowHandler, data: dict):
        _LOGGER.warning("Flow:create_entry IN (masked): %s", _mask_recursive(data))
        res = await _orig_create_entry(self, data)
        _LOGGER.warning("Flow:create_entry OUT -> %s", res)
        return res

    OAuth2FlowHandler.async_oauth_create_entry = _logged_async_oauth_create_entry  # type: ignore[attr-defined]
    OAuth2FlowHandler._fitbit_logged = True  # type: ignore[attr-defined]
# ------------------------------------------------

PLATFORMS: list[Platform] = [Platform.SENSOR]

async def async_setup_entry(hass: HomeAssistant, entry: FitbitConfigEntry) -> bool:
    """Set up fitbit from a config entry."""
    implementation = (
        await config_entry_oauth2_flow.async_get_config_entry_implementation(hass, entry)
    )
    session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)
    fitbit_api = api.OAuthFitbitApi(
        hass, session, unit_system=entry.data.get("unit_system")
    )
    try:
        await fitbit_api.async_get_access_token()
    except FitbitAuthException as err:
        raise ConfigEntryAuthFailed from err
    except FitbitApiException as err:
        raise ConfigEntryNotReady from err

    fitbit_config = config_from_entry_data(entry.data)
    coordinator: FitbitDeviceCoordinator | None = None
    if fitbit_config.is_allowed_resource(FitbitScope.DEVICE, "devices/battery"):
        coordinator = FitbitDeviceCoordinator(hass, entry, fitbit_api)
        await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = FitbitData(api=fitbit_api, device_coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: FitbitConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
