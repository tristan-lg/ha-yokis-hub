"""Coordinator global de rafraîchissement des modules Yokis."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import YokisApiError, YokisAuthError, YokisHubApi
from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


def _norm_uid(uid: Any) -> str:
    """Normalise un uid pour l'appariement (casse/espaces insensibles)."""
    return str(uid).strip().upper()


class YokisDataUpdateCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Coordinator unique : métadonnées (Project.zip) + états (gettable)."""

    def __init__(
        self, hass: HomeAssistant, api: YokisHubApi, entry: ConfigEntry
    ) -> None:
        """Initialise le coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.api = api
        self.entry = entry
        self.hub_info: dict[str, Any] = {}
        # Métadonnées des modules indexées par uid (issues de Project.zip).
        self._modules: dict[str, dict[str, Any]] = {}

    async def _async_setup_modules(self) -> None:
        """Charge les métadonnées des modules + l'identité du Hub (1 fois)."""
        if not self.hub_info:
            self.hub_info = await self.api.async_get_info()
        if not self._modules:
            modules = await self.api.async_get_config()
            self._modules = {
                str(mod.get("uid")): mod
                for mod in modules
                if mod.get("uid") is not None
            }
            _LOGGER.debug("Modules Yokis chargés: %d", len(self._modules))

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Rafraîchit les états runtime de tous les modules."""
        try:
            # Au 1er passage : récupère les métadonnées typées + identité hub.
            await self._async_setup_modules()

            states = await self.api.async_get_states()
            # Appariement insensible à la casse/aux espaces : les uid du
            # Project.zip (métadonnées) et de gettable (états) peuvent différer
            # par la casse (ex. "c31f2167" vs "C31F2167").
            states_by_uid = {
                _norm_uid(state.get("uid")): state
                for state in states
                if state.get("uid") is not None
            }

            # --- Diagnostic : association métadonnées (Project.zip) <-> états ---
            meta_norm = {_norm_uid(uid): uid for uid in self._modules}
            missing = set(meta_norm) - set(states_by_uid)
            extra = set(states_by_uid) - set(meta_norm)
            _LOGGER.debug(
                "Yokis coordinator: %d module(s) connu(s), %d état(s) reçu(s).\n"
                "  clés modules (Project.zip): %s\n"
                "  clés états   (gettable)   : %s\n"
                "  uid SANS état: %s | uid d'état SANS module: %s",
                len(self._modules),
                len(states_by_uid),
                sorted(meta_norm),
                sorted(states_by_uid),
                sorted(missing) or "aucun",
                sorted(extra) or "aucun",
            )

            data: dict[str, dict[str, Any]] = {}
            for uid, meta in self._modules.items():
                key = _norm_uid(uid)
                matched = key in states_by_uid
                previous = (
                    self.data.get(uid, {}).get("state", {}) if self.data else {}
                )
                state = states_by_uid.get(key, previous)
                data[uid] = {
                    "meta": meta,
                    # Conserve le dernier état connu si le module est absent.
                    "state": state,
                }
                # Journalise l'interprétation pour chaque module.
                self._log_interpretation(uid, meta, state, matched=matched)
            return data
        except YokisAuthError as err:
            raise UpdateFailed(f"Authentification Yokis échouée: {err}") from err
        except YokisApiError as err:
            raise UpdateFailed(f"Erreur de communication Yokis: {err}") from err

    @property
    def serial(self) -> str:
        """Numéro de série du Hub (identifiant unique)."""
        return str(self.hub_info.get("serialId", self.entry.entry_id))

    @staticmethod
    def _log_interpretation(
        uid: str, meta: dict[str, Any], state: dict[str, Any], *, matched: bool
    ) -> None:
        """Journalise l'état brut d'un module et son interprétation."""
        if not _LOGGER.isEnabledFor(logging.DEBUG):
            return

        data = int(state.get("data", 0) or 0)
        var = int(state.get("var", 0) or 0)
        alive = state.get("alive")
        use = meta.get("use")
        name = meta.get("name")

        has_varx = bool((data >> 4) & 1)
        is_open_bit = bool((data >> 1) & 1)
        if has_varx:
            closed = var == 0
            interpretation = (
                f"varX=oui -> position=var={var}% ; fermé={closed} (var==0)"
            )
        else:
            closed = not is_open_bit
            interpretation = (
                f"varX=non -> fermé={closed} (bit1 de data={'1' if is_open_bit else '0'})"
            )

        _LOGGER.debug(
            "Yokis [%s] '%s' (use=%s) | brut: data=%s (0b%s) var=%s alive=%s matched=%s "
            "| interprétation: %s",
            uid,
            name,
            use,
            data,
            format(data, "08b"),
            var,
            alive,
            matched,
            interpretation,
        )

