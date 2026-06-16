"""Config flow pour l'intégration Yokis Hub."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import YokisAuthError, YokisConnectionError, YokisHubApi
from .const import CONF_EMAIL, CONF_HOST, CONF_PASSWORD, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class YokisConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Gère le flux de configuration UI de Yokis."""

    VERSION = 1

    async def _async_validate(self, data: dict[str, Any]) -> dict[str, Any]:
        """Valide la connexion et retourne l'identité du Hub."""
        session = async_get_clientsession(self.hass)
        api = YokisHubApi(
            session,
            data[CONF_HOST],
            data[CONF_EMAIL],
            data[CONF_PASSWORD],
        )
        # info.xml ne nécessite pas d'auth : valide l'adresse du Hub.
        info = await api.async_get_info()
        # gettable nécessite l'auth : valide les identifiants.
        await api.async_get_states()
        return info

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Étape initiale déclenchée par l'utilisateur."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await self._async_validate(user_input)
            except YokisAuthError:
                errors["base"] = "invalid_auth"
            except YokisConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Erreur inattendue lors de la validation Yokis")
                errors["base"] = "unknown"
            else:
                serial = info.get("serialId")
                if serial:
                    await self.async_set_unique_id(str(serial))
                    self._abort_if_unique_id_configured()
                title = info.get("netbiosname") or "Yokis Hub"
                return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_import(self, import_config: dict[str, Any]) -> FlowResult:
        """Import depuis configuration.yaml (rétrocompat)."""
        return await self.async_step_user(import_config)

