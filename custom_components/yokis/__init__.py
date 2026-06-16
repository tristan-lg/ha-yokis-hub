"""Intégration Yokis Hub pour Home Assistant."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import YokisHubApi
from .const import CONF_EMAIL, CONF_HOST, CONF_PASSWORD, DOMAIN, PLATFORMS
from .coordinator import YokisDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_HOST): cv.string,
                vol.Required(CONF_EMAIL): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Prise en charge de la configuration YAML (rétrocompat)."""
    if DOMAIN not in config:
        return True

    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_IMPORT},
            data=config[DOMAIN],
        )
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configure une entrée Yokis (config_flow)."""
    session = async_get_clientsession(hass)
    api = YokisHubApi(
        session,
        entry.data[CONF_HOST],
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
    )

    coordinator = YokisDataUpdateCoordinator(hass, api, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Enregistre le Device « Hub » parent.
    _async_register_hub_device(hass, entry, coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Décharge une entrée Yokis."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


def _async_register_hub_device(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: YokisDataUpdateCoordinator,
) -> None:
    """Crée le Device parent représentant le Hub."""
    from homeassistant.helpers import device_registry as dr

    info = coordinator.hub_info
    serial = coordinator.serial
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, serial)},
        manufacturer="Yokis",
        name=info.get("netbiosname") or "Yokis Hub",
        model="YokisHub",
        sw_version=info.get("versionfw"),
    )


