# Plan : Intégration YokisHub pour Home Assistant
Créer un composant personnalisé Home Assistant `yokis` qui se configure via l'UI (adresse + email + mot de passe), récupère la liste des appareils du YokisHub, expose un Device « Hub » parent et un Device + entité par module connecté (volets → `cover`, éclairages → `light`/`switch`), et rafraîchit l'état de tous les modules via un `DataUpdateCoordinator` global toutes les 30 s. L'authentification au hub se fait en **HTTP Basic Auth**, et les métadonnées des modules (type, nom) proviennent du `Project.zip` chiffré (AES) du hub.
## Découvertes techniques validées (analyse du code Java décompilé + tests réseau sur 192.168.1.22)
### Authentification
- **Toutes** les routes de données (`server.xml`, `command.xml`, `datab.xml`, `Project.zip`) exigent une authentification : `WWW-Authenticate: Basic realm="Protected"`.
- Schéma : **HTTP Basic Auth** avec `email:motDePasse` (cf. `YokisBoxRequestInterceptor.java`).
- Seule exception : `info.xml?getinfo` est accessible **sans** auth (serialId, firmware, netbiosname) → utile pour identifier le Hub et valider l'adresse dans le config_flow.
### Récupération de la liste des appareils + types
- `server.xml?gettable&update=1` renvoie uniquement **l'état runtime** : `uid, alive, data, var, cpt, l_ref` (pas de type ni de nom). Tableau `table` = modules, `table_th` = thermostats.
- Les **métadonnées** (nom, type, uuid, room) sont dans `Project.zip` :
  - `GET http://<host>/Project.zip` (Basic Auth) → archive **AES** (zip4j / WinZip AES).
  - Mot de passe codé en dur dans l'app : `bUz?%HtS4W3%375G` (cf. `BoxConnectionService.java` l.328).
  - Contient `Project.txt` (JSON) → objet `Box` avec la clé `modules` (et `thermostats`, `rooms`).
  - Avant le pull, vérifier `server.xml?statebox` → champ `zipReady` (générer/attendre si 0).
- Croisement `gettable` ↔ `Project.txt` par **`uid`**.
### Mapping type d'appareil (champ `use` → `ModuleType.fromUse(use)` → `getFamily()`)
- `use=0,1,2,3` → famille 100 (MVR) → **`cover`** (volet / store / motorisation)
- `use=100` → famille 101 (MTV variateur) → **`light`** (dimmable)
- `use=200,202` → famille 102 (MTR éclairage) → **`light`** ; `use=201` (prise) → **`switch`**
- `use=203..206` (VMC, portail, gâche, contact) → **`switch`** / `cover`
- `use=300..302` → famille 104 (MFP chauffage) → `climate` (non implémenté pour l'instant)
- `use=400..403` → famille 105 (MAU portail) → `cover`
- `use=500` → **HUB** (Device parent, pas une entité contrôlable)
- Données réelles du hub de test : volets `use=0`, éclairages `use=200`, hub `use=500`.
### Interprétation de l'état (`ModuleState`)
- `data` bit 0 → on/off (`getState()`), `var` (0-100) → position/niveau.
- Volet : ouvert si `var != 0` ; `data=17` = en descente, `data=19` = en montée.
- `alive` : appareil joignable (les modules `alive=0` restent affichés mais en dernier état connu — choix utilisateur « toujours disponible »).
### Commandes (`command.xml?action=order&id=<uid>&order=<order>[&ext1=<v>]`)
- Volet (`cover`) — ouvert/fermé : ouvrir `order=on`, fermer `order=down`, stop/toggle `order=default` ; position `order=varX&ext1=<%>`.
- Éclairage / interrupteur : allumer `order=on`, éteindre `order=off`, toggle `order=default`.
## Architecture cible
- Domaine : `yokis` (aligné sur le dossier ; remplace `yokis_ha`).
- Emplacement : `dev/yokis/custom_components/yokis/`.
- Plateformes : `Platform.COVER`, `Platform.LIGHT`, `Platform.SWITCH` (climate plus tard).
- Coordinator global unique, intervalle 30 s, pull `server.xml?gettable`.
- Un Device HA par module Yokis, rattaché au Device Hub parent via `via_device`.
## Étapes d'implémentation
1. **`api/`** : client `aiohttp` (`YokisHubApi`) avec :
   - `BasicAuth(email, password)` sur toutes les requêtes ;
   - `async_get_info()` (`info.xml?getinfo`) pour validation + identité hub ;
   - `async_get_states()` (`server.xml?gettable&update=1`) → états runtime ;
   - `async_get_config()` : télécharge `Project.zip`, déchiffre AES (mdp `bUz?%HtS4W3%375G`), parse `Project.txt` → liste de modules typés ;
   - `async_send_order(uid, order, ext1=None)` (`command.xml?action=order`).
   - Dépendance : `pyzipper` (AES zip) → ajouter dans `manifest.json` `requirements` + `requirements.test.txt`.
2. **`const.py`** : `DOMAIN="yokis"`, `PLATFORMS`, clés `CONF_HOST/CONF_EMAIL/CONF_PASSWORD`, `SCAN_INTERVAL=30s`, `ZIP_PASSWORD`, mapping `use → famille → plateforme`, constantes d'ordres (`on/off/down/default/varX`).
3. **`config_flow.py`** : flux UI (`async_step_user`) demandant host + email + password ; validation via `async_get_info()` (gère 401 → « identifiants invalides », timeout → « hub injoignable ») ; `unique_id` = serialId du hub ; conserver l'`async_step_import` pour rétrocompat YAML.
4. **`coordinator.py`** : `YokisDataUpdateCoordinator(DataUpdateCoordinator)` ; au 1er refresh : pull config (modules typés) + états, ensuite pull états seuls toutes les 30 s ; expose `{uid: {meta, state}}` et l'info hub.
5. **`__init__.py`** : `async_setup_entry` instancie API + coordinator (`async_config_entry_first_refresh`), stocke dans `hass.data[DOMAIN][entry_id]`, forward des plateformes ; `async_unload_entry`.
6. **Entités** (toutes `CoordinatorEntity`, `DeviceInfo` par module + `via_device` hub) :
   - `cover.py` : volets (`use=0..3`, `400..403`) — open=`on`, close=`down`, état fermé si `var==0`.
   - `light.py` : éclairages/variateurs (`use=100,200,202`) — on/off, luminosité via `var`/`varX` si variateur.
   - `switch.py` : prises/contacts (`use=201,203..206`) — on/off.
   - Device Hub : `DeviceInfo` issu de `info.xml` (serialId, firmware, modèle).
7. **`manifest.json`** : `config_flow: true`, `iot_class: local_polling`, `requirements: ["pyzipper"]`, `domain: yokis`, `version` bump.
8. Validation : `get_errors` sur les fichiers édités ; vérifier le chargement de l'intégration.
## Hors périmètre (pour l'instant)
- Thermostats (`table_th` / `thermostats`, `VemerState`) : non implémentés (à venir).
- Position variable des volets (0-100 %) : démarrage en ouvert/fermé simple.
- Gestion des groupes, scénarios (`scenar.xml`), zones.
