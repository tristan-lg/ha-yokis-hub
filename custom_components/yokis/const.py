"""Constantes de l'intégration Yokis Hub."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "yokis"

PLATFORMS: list[Platform] = [Platform.COVER, Platform.LIGHT, Platform.SWITCH]

# Clés de configuration (config_flow / YAML)
CONF_HOST = "host"
CONF_EMAIL = "email"
CONF_PASSWORD = "password"

# Intervalle de rafraîchissement du coordinator (états runtime)
SCAN_INTERVAL = timedelta(seconds=10)

# Mot de passe AES (WinZip AES / zip4j) codé en dur dans l'app officielle
# cf. BoxConnectionService.java l.328
ZIP_PASSWORD = "bUz?%HtS4W3%375G"

# Délai HTTP par défaut (secondes)
DEFAULT_TIMEOUT = 10

# --- Ordres de commande (command.xml?action=order&order=<order>) ---
# cf. models/Action.java
ORDER_ON = "on"
ORDER_OFF = "off"
ORDER_DOWN = "down"
ORDER_UP = "up"
ORDER_TOGGLE = "default"
ORDER_GOTO = "varX"  # position/luminosité avec ext1 = pourcentage

# --- Mapping du champ `use` vers la plateforme Home Assistant ---
# cf. models/ModuleType.java (fromUse -> getFamily)
USE_HUB = 500

# Volets / stores / motorisations (famille 100 MVR) et portails (famille 105 MAU)
COVER_USES: set[int] = {0, 1, 2, 3, 400, 401, 402, 403}
# Éclairages et variateurs (famille 101 MTV / famille 102 MTR éclairage)
LIGHT_USES: set[int] = {100, 200, 202}
# Variateurs (luminosité réglable)
DIMMABLE_USES: set[int] = {100}
# Prises et contacts secs (famille 102/103 MTR autres)
SWITCH_USES: set[int] = {201, 203, 204, 205, 206}


def platform_for_use(use: int) -> Platform | None:
    """Retourne la plateforme HA correspondant à un champ `use`, ou None."""
    if use in COVER_USES:
        return Platform.COVER
    if use in LIGHT_USES:
        return Platform.LIGHT
    if use in SWITCH_USES:
        return Platform.SWITCH
    return None


def is_dimmable(use: int) -> bool:
    """Indique si le module est un variateur (luminosité réglable)."""
    return use in DIMMABLE_USES


def is_hub(use: int) -> bool:
    """Indique si le module est le Hub (Device parent, non contrôlable)."""
    return use == USE_HUB

