"""Plateforme switch (prises, contacts) Yokis."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, ORDER_OFF, ORDER_ON, SWITCH_USES
from .coordinator import YokisDataUpdateCoordinator
from .entity import YokisEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configure les prises/contacts Yokis."""
    coordinator: YokisDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        YokisSwitch(coordinator, uid)
        for uid, item in coordinator.data.items()
        if int(item.get("meta", {}).get("use", -1)) in SWITCH_USES
    ]
    async_add_entities(entities)


class YokisSwitch(YokisEntity, SwitchEntity):
    """Prise ou contact sec Yokis."""

    @property
    def is_on(self) -> bool:
        """État allumé/éteint."""
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Allume (order=on)."""
        await self.coordinator.api.async_send_order(self._uid, ORDER_ON)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Éteint (order=off)."""
        await self.coordinator.api.async_send_order(self._uid, ORDER_OFF)
        await self.coordinator.async_request_refresh()

