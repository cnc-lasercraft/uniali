"""Config-Flow für uniali."""
from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol
from aiounifi import Controller, LoginRequired, ResponseError
from aiounifi.models.configuration import Configuration

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import aiohttp_client

from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SITE,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DEFAULT_PORT,
    DEFAULT_SITE,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_SITE, default=DEFAULT_SITE): str,
        vol.Required(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
    }
)


class UnialiConfigFlow(ConfigFlow, domain=DOMAIN):
    """Setup-Flow: einmal Login probieren, dann Eintrag anlegen."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            error = await _try_login(self.hass, user_input)
            if error is None:
                await self.async_set_unique_id(
                    f"{user_input[CONF_HOST]}:{user_input[CONF_SITE]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"UniFi {user_input[CONF_HOST]}", data=user_input
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )


async def _try_login(hass, data: dict[str, Any]) -> str | None:
    """Versucht Login. Gibt None bei Erfolg, sonst error-key."""
    session = aiohttp_client.async_get_clientsession(
        hass, verify_ssl=data[CONF_VERIFY_SSL]
    )
    config = Configuration(
        session=session,
        host=data[CONF_HOST],
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        port=data[CONF_PORT],
        site=data[CONF_SITE],
        ssl_context=data[CONF_VERIFY_SSL],
    )
    controller = Controller(config)
    try:
        await controller.login()
    except LoginRequired:
        return "invalid_auth"
    except (aiohttp.ClientError, ResponseError):
        return "cannot_connect"
    except Exception:  # noqa: BLE001
        return "unknown"
    return None
