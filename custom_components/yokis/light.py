"""Plateforme light (éclairages, variateurs) Yokis."""
from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    LIGHT_USES,
    ORDER_GOTO,
    ORDER_OFF,
    ORDER_ON,
    is_dimmable,
)
from .coordinator import YokisDataUpdateCoordinator
from .entity import YokisEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configure les éclairages Yokis."""
    coordinator: YokisDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        YokisLight(coordinator, uid)
        for uid, item in coordinator.data.items()
        if int(item.get("meta", {}).get("use", -1)) in LIGHT_USES
    ]
    async_add_entities(entities)


def _pct_to_brightness(pct: int) -> int:
    """Convertit un pourcentage (0-100) en luminosité HA (0-255)."""
    return round(min(max(pct, 0), 100) * 255 / 100)


def _brightness_to_pct(brightness: int) -> int:
    """Convertit une luminosité HA (0-255) en pourcentage (0-100)."""
    return round(min(max(brightness, 0), 255) * 100 / 255)


class YokisLight(YokisEntity, LightEntity):
    """Éclairage ou variateur Yokis."""

    def __init__(self, coordinator: YokisDataUpdateCoordinator, uid: str) -> None:
        """Initialise l'entité éclairage."""
        super().__init__(coordinator, uid)
        use = int(self._meta.get("use", -1))
        if is_dimmable(use):
            self._attr_color_mode = ColorMode.BRIGHTNESS
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        else:
            self._attr_color_mode = ColorMode.ONOFF
            self._attr_supported_color_modes = {ColorMode.ONOFF}

    @property
    def is_on(self) -> bool:
        """État allumé/éteint."""
        return self._is_on

    @property
    def brightness(self) -> int | None:
        """Luminosité (uniquement pour les variateurs)."""
        if self._attr_color_mode != ColorMode.BRIGHTNESS:
            return None
        return _pct_to_brightness(self._var)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Allume l'éclairage (ou règle la luminosité)."""
        if (
            self._attr_color_mode == ColorMode.BRIGHTNESS
            and ATTR_BRIGHTNESS in kwargs
        ):
            pct = _brightness_to_pct(kwargs[ATTR_BRIGHTNESS])
            await self.coordinator.api.async_send_order(self._uid, ORDER_GOTO, pct)
        else:
            await self.coordinator.api.async_send_order(self._uid, ORDER_ON)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Éteint l'éclairage."""
        await self.coordinator.api.async_send_order(self._uid, ORDER_OFF)
        await self.coordinator.async_request_refresh()

