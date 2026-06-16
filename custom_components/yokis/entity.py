"""Entité de base pour les modules Yokis."""
from __future__ import annotations

from typing import Any

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import YokisDataUpdateCoordinator

# Bits/valeurs de l'état (cf. ModuleState.java)
STATE_BIT_ON = 0
DATA_DESCENDING = 17
DATA_CLIMBING = 19


class YokisEntity(CoordinatorEntity[YokisDataUpdateCoordinator]):
    """Base commune : DeviceInfo par module + rattachement au Hub."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: YokisDataUpdateCoordinator, uid: str) -> None:
        """Initialise l'entité."""
        super().__init__(coordinator)
        self._uid = uid
        self._attr_unique_id = f"{coordinator.serial}_{uid}"

    @property
    def _meta(self) -> dict[str, Any]:
        """Métadonnées du module (nom, use, uuid...)."""
        return self.coordinator.data.get(self._uid, {}).get("meta", {})

    @property
    def _state(self) -> dict[str, Any]:
        """État runtime du module (data, var, alive...)."""
        return self.coordinator.data.get(self._uid, {}).get("state", {})

    @property
    def _data(self) -> int:
        """Champ `data` de l'état."""
        return int(self._state.get("data", 0) or 0)

    @property
    def _var(self) -> int:
        """Champ `var` (0-100) : position/niveau."""
        return int(self._state.get("var", 0) or 0)

    @property
    def _is_on(self) -> bool:
        """État on/off : bit 0 du champ `data`."""
        return bool((self._data >> STATE_BIT_ON) & 1)

    @property
    def name(self) -> str | None:
        """Nom du module (porté par le device, has_entity_name)."""
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Attributs additionnels : identifiants Yokis Hub."""
        return {
            "yokis_uid": self._uid,
            "yokis_uuid": self._meta.get("uuid"),
            "yokis_use": self._meta.get("use"),
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Device HA du module, rattaché au Hub parent."""
        serial = self.coordinator.serial
        return DeviceInfo(
            identifiers={(DOMAIN, f"{serial}_{self._uid}")},
            name=self._meta.get("name") or f"Module {self._uid}",
            manufacturer="Yokis",
            model=self._module_model(),
            serial_number=self._uid,
            via_device=(DOMAIN, serial),
        )

    def _module_model(self) -> str:
        """Libellé du modèle selon le champ `use`."""
        use = int(self._meta.get("use", -1))
        return f"Yokis device (use={use})"


