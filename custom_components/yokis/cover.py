"""Plateforme cover (volets, stores, portails) Yokis.

Logique d'état dérivée du code source décompilé de l'app Yokis :

- Positionnement précis (varX) disponible ⟺ ``testBit(data, 4)``
  (cf. ``Module.isShutterVarXAvailable`` -> ``CFGSUtils.testBit(data, 4)``).
- Affichage de l'état (cf. ``ModuleRecyclerViewAdapter.getStateText``) :
    * volet AVEC varX  -> position = ``var`` ; ouvert si ``var > 0``.
    * volet SANS varX  -> l'app se base aussi sur ``var``, mais ce type de
      module laisse ``var`` figé : on se rabat sur le drapeau « ouvert » du
      champ ``data`` (bit 1 ; ouvert data=10, fermé data=1).
- Commandes (cf. ``OrderActionText`` / ``PilotShutterActivity``) :
  ouvrir = ``on`` ; fermer = ``down`` ; stop = ``off`` ;
  position = ``varX`` + ``ext1`` (0 = fermé, 100 = ouvert).
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    COVER_USES,
    DOMAIN,
    ORDER_DOWN,
    ORDER_GOTO,
    ORDER_OFF,
    ORDER_ON,
)
from .coordinator import YokisDataUpdateCoordinator
from .entity import DATA_CLIMBING, DATA_DESCENDING, YokisEntity

# Bit du champ `data` indiquant la disponibilité du positionnement précis
# (cf. Module.isShutterVarXAvailable -> testBit(data, 4)).
DATA_BIT_VARX = 4
# Bit du champ `data` indiquant l'état « ouvert » d'un volet classique
# (sans varX) : ouvert data=10 (bit 1 = 1), fermé data=1 (bit 1 = 0).
DATA_BIT_OPEN = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configure les volets/portails Yokis."""
    coordinator: YokisDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        YokisCover(coordinator, uid)
        for uid, item in coordinator.data.items()
        if int(item.get("meta", {}).get("use", -1)) in COVER_USES
    ]
    async_add_entities(entities)


class YokisCover(YokisEntity, CoverEntity):
    """Volet / store / portail Yokis."""

    _BASE_FEATURES = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )

    @property
    def _has_varx(self) -> bool:
        """Le volet supporte le positionnement précis (bit 4 de `data`)."""
        return bool((self._data >> DATA_BIT_VARX) & 1)

    @property
    def supported_features(self) -> CoverEntityFeature:
        """Fonctions supportées, avec SET_POSITION si le volet le permet."""
        features = self._BASE_FEATURES
        if self._has_varx:
            features |= CoverEntityFeature.SET_POSITION
        return features

    @property
    def is_closed(self) -> bool | None:
        """État fermé du volet.

        - Volet AVEC varX : fermé si la position `var` vaut 0 (logique Yokis).
        - Volet SANS varX : `var` étant figé, on lit le drapeau « ouvert » du
          champ `data` (bit 1) ; fermé s'il est absent.
        Pendant un mouvement, `is_opening`/`is_closing` priment dans l'UI.
        """
        if self._has_varx:
            return self._var == 0
        return not bool((self._data >> DATA_BIT_OPEN) & 1)

    @property
    def current_cover_position(self) -> int | None:
        """Position en pourcentage (0 = fermé, 100 = ouvert).

        Exposée uniquement pour les volets qui remontent une position réelle
        (varX). Les volets classiques n'ont pas de position.
        """
        if not self._has_varx:
            return None
        return self._var

    @property
    def is_opening(self) -> bool:
        """En montée : data == 19 (cf. ModuleState.CLIMBING)."""
        return self._data == DATA_CLIMBING

    @property
    def is_closing(self) -> bool:
        """En descente : data == 17 (cf. ModuleState.DESCENDING)."""
        return self._data == DATA_DESCENDING

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Ouvre le volet (order=on)."""
        await self.coordinator.api.async_send_order(self._uid, ORDER_ON)
        await self.coordinator.async_request_fast_poll()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Ferme le volet (order=down)."""
        await self.coordinator.api.async_send_order(self._uid, ORDER_DOWN)
        await self.coordinator.async_request_confirm_refresh()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Arrête le volet en mouvement (order=off)."""
        await self.coordinator.api.async_send_order(self._uid, ORDER_OFF)
        await self.coordinator.async_request_fast_poll()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Règle précisément la position du volet (order=varX&ext1=<%>).

        La position HA (0=fermé, 100=ouvert) correspond directement à `var`.
        """
        position = int(kwargs[ATTR_POSITION])
        position = min(max(position, 0), 100)
        await self.coordinator.api.async_send_order(self._uid, ORDER_GOTO, position)
        await self.coordinator.async_request_fast_poll()

