"""Adapter für Shelly Gen2/3/4 (RPC-API).

- Detection: HA-Device-Manufacturer == "Shelly". Gen1 wird mit gemeldet,
  scheitert dann sauber beim RPC-Read (und der read_name liefert None).
- Read: GET http://<ip>/rpc/Sys.GetConfig → device.name
- Write: POST http://<ip>/rpc/Sys.SetConfig mit {config: {device: {name: ...}}}
- Auth: nur passwort-lose Geräte. Digest-Auth für gesicherte Shellys → Phase 3.
- Reliability: 5 s Timeout; 1 Retry nur im Schreibpfad (write + Read-back),
  nicht im Audit-Read — ein Offline-Gerät soll den Refresh nicht um 10 s
  verlängern, der nächste Refresh korrigiert Transientes von selbst. Read-back
  nach dem Schreiben (Shelly antwortet 200 auch wenn der Name gekürzt wurde, #16).
"""
from __future__ import annotations

import asyncio
import logging

import aiohttp

from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.device_registry import DeviceEntry

from .base import DeviceAdapter

_LOGGER = logging.getLogger(__name__)
_TIMEOUT = aiohttp.ClientTimeout(total=5)
_RETRIES = 1
_RETRY_DELAY = 0.5


class ShellyGen2Adapter(DeviceAdapter):
    id = "shelly_gen2"

    def matches(self, ha_device: DeviceEntry, mac: str, ip: str | None) -> bool:
        return (ha_device.manufacturer or "").lower() == "shelly"

    def ip_from_ha(self, ha_device: DeviceEntry) -> str | None:
        # Shelly-Integration speichert die IP in entry.data['host']. Nutzen wir
        # wenn UniFi keine aktuelle IP liefert (Client-Tracking-Lücke).
        for entry_id in ha_device.config_entries:
            entry = self.hass.config_entries.async_get_entry(entry_id)
            if entry is None or entry.domain != "shelly":
                continue
            host = entry.data.get("host")
            if isinstance(host, str) and host:
                return host
        return None

    async def _rpc(
        self,
        ip: str,
        path: str,
        payload: dict | None = None,
        *,
        retries: int = 0,
    ) -> dict | None:
        """RPC-Aufruf mit Timeout. GET ohne, POST mit Payload.

        Liefert das JSON-Dict oder None bei Netzfehler / HTTP != 200 /
        RPC-Error-Antwort. `retries` wiederholt nur bei Transportfehlern
        (Timeout, ClientError), nicht bei fachlichen Fehlern vom Gerät.
        """
        session = aiohttp_client.async_get_clientsession(self.hass)
        url = f"http://{ip}/rpc/{path}"
        for attempt in range(retries + 1):
            try:
                if payload is None:
                    req = session.get(url, timeout=_TIMEOUT)
                else:
                    req = session.post(url, json=payload, timeout=_TIMEOUT)
                async with req as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
                if attempt < retries:
                    _LOGGER.debug(
                        "Shelly %s %s: %s — Retry", ip, path, type(err).__name__
                    )
                    await asyncio.sleep(_RETRY_DELAY)
                    continue
                return None
            if not isinstance(data, dict):
                return None
            if "error" in data:
                _LOGGER.warning("Shelly RPC error bei %s/%s: %s", ip, path, data["error"])
                return None
            return data
        return None

    @staticmethod
    def _name_from_config(cfg: dict | None) -> str | None:
        if not cfg:
            return None
        device = cfg.get("device")
        if not isinstance(device, dict):
            return None
        name = device.get("name")
        return name if isinstance(name, str) and name else None

    async def read_name(self, ip: str, *, retries: int = 0) -> str | None:
        return self._name_from_config(
            await self._rpc(ip, "Sys.GetConfig", retries=retries)
        )

    async def read_state(self, ip: str) -> dict | None:
        # Sys.GetConfig liefert den Namen, Shelly.GetStatus die Live-Interfaces.
        # Parallel laufen lassen — pro Gerät 2 schnelle GETs statt zwei sequenziell.
        cfg, status = await asyncio.gather(
            self._rpc(ip, "Sys.GetConfig"), self._rpc(ip, "Shelly.GetStatus")
        )
        if cfg is None and status is None:
            return None

        name = self._name_from_config(cfg)

        interfaces: dict[str, bool] | None = None
        if status:
            wifi = status.get("wifi") or {}
            eth = status.get("eth") or {}
            interfaces = {
                # WiFi-STA als aktiv betrachten wenn ein gültiger Status ankommt
                # (got_ip / got ip — Schreibweise variiert je nach Firmware).
                "wifi": str(wifi.get("status", "")).replace("_", " ").lower()
                == "got ip",
                # Eth-Block existiert nur wenn das Interface konfiguriert UND
                # eine IP zugewiesen ist — guter Aktiv-Indikator.
                "eth": isinstance(eth.get("ip"), str) and bool(eth["ip"]),
            }

        return {"name": name, "interfaces": interfaces}

    async def write_name(self, ip: str, new_name: str) -> bool:
        data = await self._rpc(
            ip,
            "Sys.SetConfig",
            {"config": {"device": {"name": new_name}}},
            retries=_RETRIES,
        )
        if data is None:
            return False
        # Read-back: Shelly quittiert mit 200 auch wenn es den Namen still
        # gekürzt/verändert hat (#16). Erst der Vergleich zählt als Erfolg.
        actual = await self.read_name(ip, retries=_RETRIES)
        if actual != new_name:
            _LOGGER.warning(
                "Shelly %s: Read-back weicht ab — gesendet %r, gespeichert %r",
                ip, new_name, actual,
            )
            return False
        return True
