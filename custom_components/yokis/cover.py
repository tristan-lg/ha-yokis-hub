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

Détection ouverture/fermeture en cours :

Le Hub Yokis ne remonte aucun bit fiable indiquant qu'un volet est en train
de bouger (les constantes ``ModuleState.CLIMBING``/``DESCENDING`` existent
dans le code décompilé mais ne sont utilisées nulle part ailleurs dans
l'app -> vérifié non fiable en pratique). Un volet met ~28 s pour un cycle
complet d'ouverture/fermeture (mesuré manuellement).

On simule donc l'état « en mouvement » de deux façons complémentaires :
1. Commande envoyée depuis HA (``async_open/close_cover``) : on démarre la
   fenêtre de mouvement immédiatement (retour instantané dans l'UI), sans
   attendre le prochain poll.
2. Commande manuelle (bouton mural, télécommande RF) : HA ne reçoit aucune
   notification (l'API est en polling pur). On détecte le changement en
   comparant la position à chaque rafraîchissement du coordinator
   (``_handle_coordinator_update``) à la valeur précédemment connue : si
   elle diffère, on (re)démarre la fenêtre de mouvement. Le délai de
   détection est alors borné par l'intervalle de polling (``SCAN_INTERVAL``,
   10 s), ce qui est la meilleure précision possible sans push du Hub.
Dans les deux cas, tant que ``time.monotonic() - _transition_at`` reste
sous ``COVER_MOVEMENT_DURATION`` (28 s), `is_opening`/`is_closing` reflète
le sens du dernier changement observé (position croissante = ouverture,
décroissante = fermeture).
"""
from __future__ import annotations

import time
from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    COVER_MOVEMENT_DURATION,
    COVER_USES,
    DOMAIN,
    ORDER_DOWN,
    ORDER_GOTO,
    ORDER_OFF,
    ORDER_ON,
    USE_COVER_DEVICE_CLASS,
)
from .coordinator import YokisDataUpdateCoordinator
from .entity import YokisEntity

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

    # Position/état pas garantis en temps réel (polling + volets sans varX
    # figés sur `var`) : `assumed_state` indique au frontend HA de toujours
    # garder les boutons ouvrir/fermer/stop actifs, même si le volet est
    # déjà (censé être) ouvert ou fermé (cf. canOpen/canClose du frontend HA,
    # qui désactivent sinon le bouton correspondant à l'état courant).
    _attr_assumed_state = True

    def __init__(self, coordinator: YokisDataUpdateCoordinator, uid: str) -> None:
        """Initialise le suivi de position (détection de mouvement)."""
        super().__init__(coordinator, uid)
        # Dernière valeur de position observée (cf. `_position_value`).
        self._last_position: int | None = None
        # Horodatage (monotonic) du dernier changement de position détecté.
        self._transition_at: float | None = None
        # Sens du dernier changement détecté : True = ouverture, False = fermeture.
        self._moving_towards_open: bool | None = None

    @property
    def device_class(self) -> CoverDeviceClass | None:
        """Type de volet HA (shutter/awning/gate/garage) selon `use`.

        Permet à HA de proposer les bons libellés/icônes, et surtout de
        faire apparaître les conditions d'automatisation standard
        (« le volet est ouvert/fermé/en cours d'ouverture/de fermeture »)
        pour le Device correspondant : ces conditions sont générées par le
        composant `cover` dès que OPEN/CLOSE sont supportés (cf.
        `cover.device_condition.async_get_conditions`), indépendamment du
        `device_class`, mais celui-ci reste nécessaire pour un affichage
        correct (« volet » plutôt que « portail »/« garage » générique).
        """
        use = int(self._meta.get("use", -1))
        value = USE_COVER_DEVICE_CLASS.get(use)
        return CoverDeviceClass(value) if value else None

    @property
    def _has_varx(self) -> bool:
        """Le volet supporte le positionnement précis (bit 4 de `data`)."""
        return bool((self._data >> DATA_BIT_VARX) & 1)

    @property
    def _position_value(self) -> int:
        """Valeur de référence pour détecter un changement de position.

        - Volet AVEC varX : la position `var` (0-100).
        - Volet SANS varX : pas de position intermédiaire -> 100 si ouvert,
          0 si fermé (lecture du bit `data` via `is_closed`).
        """
        if self._has_varx:
            return self._var
        return 0 if self.is_closed else 100

    @property
    def _is_moving(self) -> bool:
        """Un mouvement (ouverture ou fermeture) est présumé en cours.

        Vrai pendant `COVER_MOVEMENT_DURATION` secondes après le dernier
        changement de position détecté (cf. docstring du module).
        """
        if self._transition_at is None:
            return False
        return (time.monotonic() - self._transition_at) < COVER_MOVEMENT_DURATION

    def _start_movement(self, *, towards_open: bool) -> None:
        """(Re)démarre la fenêtre de mouvement dans le sens indiqué."""
        self._transition_at = time.monotonic()
        self._moving_towards_open = towards_open

    @callback
    def _handle_coordinator_update(self) -> None:
        """Détecte un changement de position entre deux rafraîchissements.

        Couvre le cas d'une commande manuelle (bouton mural, télécommande) :
        le Hub étant interrogé en polling pur, on ne peut détecter ce
        changement qu'au prochain rafraîchissement du coordinator, avec un
        délai borné par l'intervalle de polling en cours.
        """
        position = self._position_value
        if self._last_position is not None and position != self._last_position:
            self._start_movement(towards_open=position > self._last_position)
        self._last_position = position
        super()._handle_coordinator_update()

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
        """Ouverture en cours (cf. `_is_moving` / fenêtre de 28 s)."""
        return self._is_moving and self._moving_towards_open is True

    @property
    def is_closing(self) -> bool:
        """Fermeture en cours (cf. `_is_moving` / fenêtre de 28 s)."""
        return self._is_moving and self._moving_towards_open is False

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Ouvre le volet (order=on).

        Démarre la fenêtre de mouvement immédiatement (retour instantané
        dans l'UI) plutôt que d'attendre le prochain poll.
        """
        self._start_movement(towards_open=True)
        self.async_write_ha_state()
        await self.coordinator.api.async_send_order(self._uid, ORDER_ON)
        await self.coordinator.async_request_fast_poll()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Ferme le volet (order=down). Voir `async_open_cover`."""
        self._start_movement(towards_open=False)
        self.async_write_ha_state()
        await self.coordinator.api.async_send_order(self._uid, ORDER_DOWN)
        await self.coordinator.async_request_confirm_refresh()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Arrête le volet en mouvement (order=off)."""
        self._transition_at = None
        self.async_write_ha_state()
        await self.coordinator.api.async_send_order(self._uid, ORDER_OFF)
        await self.coordinator.async_request_fast_poll()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Règle précisément la position du volet (order=varX&ext1=<%>).

        La position HA (0=fermé, 100=ouvert) correspond directement à `var`.
        """
        position = int(kwargs[ATTR_POSITION])
        position = min(max(position, 0), 100)
        if self._has_varx:
            self._start_movement(towards_open=position > self._var)
            self.async_write_ha_state()
        await self.coordinator.api.async_send_order(self._uid, ORDER_GOTO, position)
        await self.coordinator.async_request_fast_poll()

