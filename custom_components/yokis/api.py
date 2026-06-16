"""Client API du Yokis Hub."""
from __future__ import annotations

import asyncio
import io
import json
import logging
from typing import Any

import aiohttp
import pyzipper

from .const import DEFAULT_TIMEOUT, ZIP_PASSWORD

_LOGGER = logging.getLogger(__name__)


class YokisApiError(Exception):
    """Erreur générique de communication avec le Hub."""


class YokisAuthError(YokisApiError):
    """Identifiants invalides (HTTP 401)."""


class YokisConnectionError(YokisApiError):
    """Hub injoignable (timeout / connexion)."""


class YokisHubApi:
    """Client HTTP (aiohttp) pour le Yokis Hub.

    Toutes les routes de données exigent une authentification HTTP Basic
    (`email:password`), à l'exception de `info.xml?getinfo`.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        email: str,
        password: str,
    ) -> None:
        """Initialise le client."""
        self._session = session
        self._host = host.strip().rstrip("/")
        if not self._host.startswith("http"):
            self._host = f"http://{self._host}"
        self._email = email
        self._password = password
        self._auth = aiohttp.BasicAuth(email, password)

    @property
    def host(self) -> str:
        """Adresse de base du Hub."""
        return self._host

    async def _get_json(self, path: str, *, auth: bool = True) -> Any:
        """Effectue un GET et retourne la réponse JSON."""
        url = f"{self._host}/{path}"
        try:
            async with self._session.get(
                url,
                auth=self._auth if auth else None,
                headers={"Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT),
            ) as response:
                if response.status == 401:
                    raise YokisAuthError("Identifiants Yokis invalides (401)")
                response.raise_for_status()
                # Le hub renvoie du JSON quand l'en-tête Accept est défini,
                # mais le content-type peut rester text/xml.
                text = await response.text()
                return json.loads(text)
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as err:
            raise YokisConnectionError(f"Hub injoignable: {err}") from err
        except aiohttp.ClientResponseError as err:
            if err.status == 401:
                raise YokisAuthError("Identifiants Yokis invalides (401)") from err
            raise YokisApiError(f"Erreur HTTP {err.status}: {err}") from err
        except json.JSONDecodeError as err:
            raise YokisApiError(f"Réponse JSON invalide: {err}") from err

    async def async_get_info(self) -> dict[str, Any]:
        """Récupère l'identité du Hub (sans authentification).

        `info.xml?getinfo` → serialId, versionfw, netbiosname, uid.
        """
        data = await self._get_json("info.xml?getinfo", auth=False)
        if not isinstance(data, dict):
            raise YokisApiError("Réponse info.xml inattendue")
        return data

    async def async_get_box_state(self) -> dict[str, Any]:
        """Récupère l'état de la box (`server.xml?statebox`) → zipReady."""
        data = await self._get_json("server.xml?statebox")
        if not isinstance(data, dict):
            raise YokisApiError("Réponse statebox inattendue")
        return data

    async def async_get_states(self) -> list[dict[str, Any]]:
        """Récupère les états runtime (`server.xml?gettable&update=1`).

        Retourne la liste `table` (modules) : uid, alive, data, var, cpt.
        """
        data = await self._get_json("server.xml?gettable&update=1")
        if not isinstance(data, dict):
            raise YokisApiError("Réponse gettable inattendue")
        table = data.get("data", []).get("table", []) or []
        _LOGGER.debug(
            "Yokis gettable: %d module(s) d'état reçus -> %s",
            len(table),
            table,
        )
        return table

    async def async_get_config(self) -> list[dict[str, Any]]:
        """Télécharge et déchiffre `Project.zip` → liste des modules typés.

        L'archive est chiffrée en AES (WinZip), mot de passe `ZIP_PASSWORD`.
        Elle contient `Project.txt` (JSON de l'objet `Box`) dont la clé
        `modules` liste les modules (uid, name, use, uuid, room...).
        """
        url = f"{self._host}/Project.zip"
        try:
            async with self._session.get(
                url,
                auth=self._auth,
                timeout=aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT * 3),
            ) as response:
                if response.status == 401:
                    raise YokisAuthError("Identifiants Yokis invalides (401)")
                response.raise_for_status()
                content = await response.read()
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as err:
            raise YokisConnectionError(f"Hub injoignable: {err}") from err
        except aiohttp.ClientResponseError as err:
            if err.status == 401:
                raise YokisAuthError("Identifiants Yokis invalides (401)") from err
            raise YokisApiError(f"Erreur HTTP {err.status}: {err}") from err

        # Le déchiffrement AES est bloquant : on l'exécute dans un thread.
        loop = asyncio.get_running_loop()
        box = await loop.run_in_executor(None, self._extract_box, content)
        modules = box.get("modules", []) or []
        if not isinstance(modules, list):
            raise YokisApiError("Clé `modules` invalide dans Project.txt")
        return modules

    @staticmethod
    def _extract_box(content: bytes) -> dict[str, Any]:
        """Déchiffre l'archive et parse le JSON de la box (bloquant)."""
        try:
            with pyzipper.AESZipFile(io.BytesIO(content)) as zf:
                zf.setpassword(ZIP_PASSWORD.encode("utf-8"))
                # Recherche de l'entrée Project.txt (ou premier .txt/.json).
                names = zf.namelist()
                target = None
                for name in names:
                    lname = name.lower()
                    if lname.endswith("project.txt"):
                        target = name
                        break
                if target is None:
                    for name in names:
                        if name.lower().endswith((".txt", ".json")):
                            target = name
                            break
                if target is None:
                    raise YokisApiError(
                        f"Project.txt introuvable dans l'archive ({names})"
                    )
                raw = zf.read(target)
        except YokisApiError:
            raise
        except Exception as err:  # noqa: BLE001 - dépend de pyzipper
            raise YokisApiError(f"Déchiffrement Project.zip échoué: {err}") from err

        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as err:
            raise YokisApiError(f"Project.txt JSON invalide: {err}") from err

    async def async_send_order(
        self, uid: str, order: str, ext1: int | None = None
    ) -> None:
        """Envoie un ordre à un module (`command.xml?action=order`)."""
        path = f"command.xml?action=order&id={uid}&order={order}"
        if ext1 is not None:
            path = f"{path}&ext1={ext1}"
        url = f"{self._host}/{path}"
        try:
            async with self._session.get(
                url,
                auth=self._auth,
                headers={"Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT),
            ) as response:
                if response.status == 401:
                    raise YokisAuthError("Identifiants Yokis invalides (401)")
                response.raise_for_status()
                _LOGGER.debug(
                    "Ordre envoyé uid=%s order=%s ext1=%s -> %s",
                    uid,
                    order,
                    ext1,
                    response.status,
                )
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as err:
            raise YokisConnectionError(f"Hub injoignable: {err}") from err
        except aiohttp.ClientResponseError as err:
            raise YokisApiError(f"Erreur HTTP {err.status}: {err}") from err

