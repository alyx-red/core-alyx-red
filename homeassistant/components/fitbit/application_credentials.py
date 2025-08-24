"""Fitbit application credentials + provider-specific OAuth impl."""
from __future__ import annotations

import json
import logging
from typing import cast

from homeassistant.core import HomeAssistant
from homeassistant.components.application_credentials import ClientCredential
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import (
    AbstractOAuth2Implementation,
    LocalOAuth2Implementation,
)

_LOGGER = logging.getLogger(__name__)

AUTH_URL = "https://www.fitbit.com/oauth2/authorize"
TOKEN_URL = "https://api.fitbit.com/oauth2/token"


class FitbitOAuth2Implementation(LocalOAuth2Implementation):
    """Local OAuth2 implementation that logs Fitbit's exact error body."""

    async def _token_request(self, data: dict[str, str]) -> dict:
        """Make a token request, preserving Fitbit's error details in logs."""
        session = async_get_clientsession(self.hass)

        data["client_id"] = self.client_id
        if self.client_secret:
            data["client_secret"] = self.client_secret

        _LOGGER.debug("Sending token request to %s", self.token_url)
        resp = await session.post(self.token_url, data=data)
        text = await resp.text()

        if resp.status >= 400:
            err_code = None
            err_msg = None
            try:
                body = json.loads(text)
                if isinstance(body, dict):
                    # RFC 6749 style
                    err_code = body.get("error")
                    err_msg = body.get("error_description") or body.get("error_message")
                    # Fitbit style: {"errors":[{"errorType":"...","message":"..."}]}
                    errs = body.get("errors")
                    if not err_code and isinstance(errs, list) and errs:
                        first = errs[0] if isinstance(errs[0], dict) else {}
                        err_code = first.get("errorType") or first.get("error")
                        err_msg = first.get("message") or err_msg
                    # Sometimes there's a top-level "message"
                    if not err_msg and isinstance(body.get("message"), str):
                        err_msg = body["message"]
            except Exception:
                # keep raw text if not JSON
                pass

            _LOGGER.error(
                "Token request for %s failed (%s): %s",
                self.domain,
                err_code or f"{resp.status} {resp.reason}",
                err_msg or text,
            )
            resp.raise_for_status()

        return cast(dict, json.loads(text))


async def async_get_auth_implementation(
    hass: HomeAssistant, auth_domain: str, credential: ClientCredential
) -> AbstractOAuth2Implementation:
    """Return the Fitbit-specific OAuth implementation used by the config flow."""
    return FitbitOAuth2Implementation(
        hass,
        auth_domain,
        credential.client_id,
        credential.client_secret,
        AUTH_URL,
        TOKEN_URL,
    )
