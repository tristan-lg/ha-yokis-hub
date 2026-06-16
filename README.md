# Yokis Hub – Intégration Home Assistant

Intégration personnalisée pour piloter les modules Yokis via un **YokisHub** sur
le réseau local (polling). Elle se configure depuis l'interface (UI).

Vibecodé avec Claude Opus 4.8

## Fonctionnalités

- Configuration via l'UI : **adresse du Hub + e-mail + mot de passe** (HTTP Basic Auth).
- Découverte automatique des modules à partir de l'archive chiffrée `Project.zip`.
- Un **Device « Hub »** parent + un Device/entité par module.
- Rafraîchissement global des états toutes les **30 s** (`DataUpdateCoordinator`).

## Plateformes prises en charge

| Type Yokis (`use`)                | Entité Home Assistant |
| --------------------------------- | --------------------- |
| Volets / stores / motorisation (0–3), portails (400–403) | `cover` |
| Variateur (100), éclairages (200, 202)                   | `light` |
| Prises / contacts (201, 203–206)                         | `switch` |
| Hub (500)                                                | Device parent |

> Les variateurs (`use=100`) exposent le réglage de **luminosité**.

## Détails techniques

- `info.xml?getinfo` : identité du Hub (sans authentification).
- `server.xml?gettable&update=1` : états runtime (`uid, alive, data, var, cpt`).
- `Project.zip` (AES, dépendance `pyzipper`) : métadonnées des modules (`name`, `use`, `uuid`).
- `command.xml?action=order&id=<uid>&order=<order>[&ext1=<v>]` : commandes.

## Hors périmètre (à venir)

- Thermostats (`climate`).
- Groupes, scénarios, zones.

