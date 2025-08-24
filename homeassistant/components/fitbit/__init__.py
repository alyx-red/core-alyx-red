"""The (custom) fitbit component."""
from __future__ import annotations

import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)
_LOGGER.warning("✅ Loaded CUSTOM Fitbit integration (session+setup logging)")

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_entry_oauth2_flow

from . import api
from .const import FitbitScope
from .coordinator import FitbitConfigEntry, FitbitData, FitbitDeviceCoordinator
from .exceptions import FitbitApiException, FitbitAuthException
from .model import config_from_entry_data

# ---------- Mask helpers ----------
def _mask(v: Any) -> str:
    if v is None:
        return "<none>"
    s = str(v)
    return (s[:3] + "*" * 6) if len(s) >= 3 else s + "*" * 6

def _mask_entry(entry) -> str:
    try:
        return f"id={getattr(entry, 'entry_id', '<na>')} title={getattr(entry, 'title', '<na>')}"
    except Exception:
        return "<entry?>"
# ----------------------------------

# ---------- Verbose logging for OAuth2Session (no forbidden imports) ----------
Session = config_entry_oauth2_flow.OAuth2Session
if not getattr(Session, "_fitbit_logged", False):
    _orig_init = Session.__init__
    _orig_ensure = Session.async_ensure_token_valid
    _orig_refresh = getattr(Session, "_async_refresh_token", None)

    def _logged_init(self, hass, entry, implementation):
        _LOGGER.warning(
            "OAuth2Session:init entry=(%s) impl_domain=%s",
            _mask_entry(entry),
            getattr(implementation, "domain", "<na>"),
        )
        return _orig_init(self, hass, entry, implementation)

    async def _logged_ensure(self):
        _LOGGER.warning("OAuth2Session:ensure_token_valid:start")
        try:
            res = await _orig_ensure(self)
            _LOGGER.warning("OAuth2Session:ensure_token_valid:ok")
            return res
        except Exception as e:
            _LOGGER.warning("OAuth2Session:ensure_token_valid:error=%r", e)
            raise

    Session.__init__ = _logged_init
    Session.async_ensure_token_valid = _logged_ensure

    if _orig_refresh is not None:
        async def _logged_refresh(self):
            _LOGGER.warning("OAuth2Session:_async_refresh_token:start")
            r = await _orig_refresh(self)
            _LOGGER.warning("OAuth2Session:_async_refresh_token:done")
            return r
        Session._async_refresh_token = _logged_refresh

    Session._fitbit_logged = True
# ------------------------------------------------------------------------------

PLATFORMS: list[Platform] = [Platform.SENSOR]

async def async_setup_entry(hass: HomeAssistant, entry: FitbitConfigEntry) -> bool:
    """Set up fitbit from a config entry."""
    _LOGGER.warning("async_setup_entry:start %s", _mask_entry(entry))

    implementation = await config_entry_oauth2_flow.async_get_config_entry_implementation(hass, entry)
    session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)
    fitbit_api = api.OAuthFitbitApi(
        hass, session, unit_system=entry.data.get("unit_system")
    )

    _LOGGER.warning("async_setup_entry:fetch_access_token:start")
    try:
        await fitbit_api.async_get_access_token()
        _LOGGER.warning("async_setup_entry:fetch_access_token:ok")
    except FitbitAuthException as err:
        _LOGGER.warning("async_setup_entry:fetch_access_token:auth_error=%r", err)
        raise ConfigEntryAuthFailed from err
    except FitbitApiException as err:
        _LOGGER.warning("async_setup_entry:fetch_access_token:api_error=%r", err)
        raise ConfigEntryNotReady from err

    fitbit_config = config_from_entry_data(entry.data)
    coordinator: FitbitDeviceCoordinator | None = None

    if fitbit_config.is_allowed_resource(FitbitScope.DEVICE, "devices/battery"):
        _LOGGER.warning("async_setup_entry:device_coordinator:first_refresh:start")
        coordinator = FitbitDeviceCoordinator(hass, entry, fitbit_api)
        await coordinator.async_config_entry_first_refresh()
        _LOGGER.warning("async_setup_entry:device_coordinator:first_refresh:done")

    entry.runtime_data = FitbitData(api=fitbit_api, device_coordinator=coordinator)
    _LOGGER.warning("async_setup_entry:forward_setups:start")
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.warning("async_setup_entry:forward_setups:done")

    _LOGGER.warning("async_setup_entry:done %s", _mask_entry(entry))
    return True

async def async_unload_entry(hass: HomeAssistant, entry: FitbitConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.warning("async_unload_entry:start %s", _mask_entry(entry))
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    _LOGGER.warning("async_unload_entry:done ok=%s %s", ok, _mask_entry(entry))
    return ok
