"""Fitbit application credentials + provider-specific OAuth impl."""
from __future__ import annotations

import json
import logging
from typing import cast, Any

from aiohttp import BasicAuth
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


def _mask(val: Any) -> str:
    """Mask sensitive values: first 3 chars + six asterisks (total 9)."""
    if val is None:
        return "<none>"
    s = str(val)
    head = s[:3]
    return f"{head}{'*' * 6}"  # always 9 chars shown


def _mask_payload(d: dict[str, Any]) -> dict[str, Any]:
    """Mask known sensitive fields inside a dict for logging."""
    sensitive = {"code", "refresh_token", "access_token", "id_token", "client_secret"}
    masked: dict[str, Any] = {}
    for k, v in d.items():
        if k in sensitive and isinstance(v, (str, bytes)):
            masked[k] = _mask(v)
        else:
            masked[k] = v
    return masked


class FitbitOAuth2Implementation(LocalOAuth2Implementation):
    """Local OAuth2 implementation that logs Fitbit's exact error body."""

    async def async_resolve_external_data(self, external_data: dict[str, str]) -> dict:
        """Exchange the auth code for tokens, with verbose, masked logging."""
        code = external_data.get("code")
        state = external_data.get("state")

        _LOGGER.warning(
            "Fitbit OAuth: received external_data: code=%s state=%s",
            _mask(code),
            _mask(state),
        )

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
        }
        _LOGGER.warning(
            "Fitbit OAuth: pre-token payload (masked): %s",
            _mask_payload(data),
        )

        tokens = await self._token_request(data)

        # Log token response keys and masked secrets
        resp_log = {}
        for k in sorted(tokens.keys()):
            resp_log[k] = _mask(tokens[k]) if k in {"access_token", "refresh_token", "id_token"} else tokens[k]
        _LOGGER.warning("Fitbit OAuth: token response (masked): %s", resp_log)

        return tokens

    async def _token_request(self, data: dict[str, str]) -> dict:
        """Make a token request, preserving Fitbit's error details in logs."""
        session = async_get_clientsession(self.hass)

        # Fitbit expects HTTP Basic for confidential clients.
        auth = None
        data["client_id"] = self.client_id
        if self.client_secret:
            auth = BasicAuth(self.client_id, self.client_secret)
            # Don't send the secret in the body when using Basic
            data.pop("client_secret", None)

        _LOGGER.warning(
            "Fitbit OAuth: POST %s auth_basic=%s body_keys=%s body_masked=%s",
            self.token_url,
            bool(auth),
            sorted(list(data.keys())),
            _mask_payload(data),
        )

        resp = await session.post(self.token_url, data=data, auth=auth)
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
                    # Sometimes a top-level "message"
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

        # Success path
        try:
            parsed = cast(dict, json.loads(text))
        except Exception:
            _LOGGER.error("Fitbit OAuth: non-JSON token response: %s", text)
            raise
        return parsed


async def async_get_auth_implementation(
    hass: HomeAssistant, auth_domain: str, credential: ClientCredential
) -> AbstractOAuth2Implementation:
    """Return the Fitbit-specific OAuth implementation used by the config flow."""
    _LOGGER.warning(
        "Fitbit OAuth: building impl for domain=%s client_id=%s secret_present=%s",
        auth_domain,
        _mask(credential.client_id),
        bool(credential.client_secret),
    )
    return FitbitOAuth2Implementation(
        hass,
        auth_domain,
        credential.client_id,
        credential.client_secret,
        AUTH_URL,
        TOKEN_URL,
    )
