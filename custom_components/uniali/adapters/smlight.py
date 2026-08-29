"""Adapter für SMLIGHT SLZB-Koordinatoren (SLZB-06-Familie, SLZB-OS).

- Detection: HA-Device-Manufacturer == "SMLIGHT" (Core-Integration `smlight`).
- Read: GET http://<ip>/ha_info → Info.hostname; GET /ha_sensors liefert
  ethernet/wifi_connected für die Interface-Badges.
- Write: POST http://<ip>/settings/saveParams mit pageId=6&host=<name>
  (form-urlencoded). Das General-Settings-Formular der Firmware hat genau
  dieses eine Feld (maxlength 50), Antwort ist JSON mit `changes.host` —
  dient als Write-Bestätigung. Kein Reboot nötig (needReboot=false).
- Auth: nur Geräte ohne Web-Auth (wie beim Shelly-Adapter).
- Achtung: der Name IST der mDNS-Hostname (<name>.local). Wer Z2M/ZHA über
  .local statt IP verbindet, kappt mit einem Rename die Verbindung — Sync
  bleibt deshalb bewusst per Klick pro Zeile.
"""
from __future__ import annotations

import asyncio
import json
import logging

import aiohttp

from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.device_registry import DeviceEntry

from .base import DeviceAdapter

_LOGGER = logging.getLogger(__name__)
_TIMEOUT = aiohttp.ClientTimeout(total=5)
_MAX_NAME_LEN = 50  # maxlength des host-Felds im General-Settings-Formular


class SmlightAdapter(DeviceAdapter):
    id = "smlight"

    def matches(self, ha_device: DeviceEntry, mac: str, ip: str | None) -> bool:
        return (ha_device.manufacturer or "").lower() == "smlight"

    def ip_from_ha(self, ha_device: DeviceEntry) -> str | None:
        # smlight-Integration speichert den Host in entry.data['host'].
        for entry_id in ha_device.config_entries:
            entry = self.hass.config_entries.async_get_entry(entry_id)
            if entry is None or entry.domain != "smlight":
                continue
            host = entry.data.get("host")
            if isinstance(host, str) and host:
                return host
        return None

    async def _get_json(self, ip: str, path: str) -> dict | None:
        session = aiohttp_client.async_get_clientsession(self.hass)
        try:
            async with session.get(
                f"http://{ip}/{path}", timeout=_TIMEOUT
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    async def read_name(self, ip: str) -> str | None:
        data = await self._get_json(ip, "ha_info")
        if data is None:
            return None
        info = data.get("Info")
        if not isinstance(info, dict):
            return None
        name = info.get("hostname")
        return name if isinstance(name, str) and name else None

    async def read_state(self, ip: str) -> dict | None:
        # /ha_info für den Namen, /ha_sensors für Live-Interface-Status.
        info_data, sensor_data = await asyncio.gather(
            self._get_json(ip, "ha_info"), self._get_json(ip, "ha_sensors")
        )
        if info_data is None and sensor_data is None:
            return None

        name: str | None = None
        if info_data:
            info = info_data.get("Info")
            if isinstance(info, dict):
                raw_name = info.get("hostname")
                if isinstance(raw_name, str) and raw_name:
                    name = raw_name

        interfaces: dict[str, bool] | None = None
        if sensor_data:
            sensors = sensor_data.get("Sensors")
            if isinstance(sensors, dict):
                interfaces = {
                    "wifi": bool(sensors.get("wifi_connected")),
                    "eth": bool(sensors.get("ethernet")),
                }

        return {"name": name, "interfaces": interfaces}

    async def write_name(self, ip: str, new_name: str) -> bool:
        if len(new_name) > _MAX_NAME_LEN:
            _LOGGER.warning(
                "SLZB %s: Name '%s' überschreitet %d Zeichen — Sync verweigert",
                ip,
                new_name,
                _MAX_NAME_LEN,
            )
            return False
        session = aiohttp_client.async_get_clientsession(self.hass)
        try:
            async with session.post(
                f"http://{ip}/settings/saveParams",
                data={"pageId": 6, "host": new_name},
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status != 200:
                    return False
                raw = await resp.text()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False
        # Antwort-JSON bestätigt den Write: {"changes": {"host": "<name>"}, ...}
        try:
            data = json.loads(raw)
        except ValueError:
            return False
        changes = data.get("changes") if isinstance(data, dict) else None
        if not isinstance(changes, dict) or changes.get("host") != new_name:
            _LOGGER.warning("SLZB %s: Write nicht bestätigt: %s", ip, raw)
            return False
        return True
