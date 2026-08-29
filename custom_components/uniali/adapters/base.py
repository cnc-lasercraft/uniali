"""Adapter-Interface für vendor-spezifische Geräte-Name-Sync."""
from __future__ import annotations

from abc import ABC, abstractmethod

from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry


class DeviceAdapter(ABC):
    """Basisklasse für vendor-spezifische Adapter (z.B. ShellyGen2Adapter)."""

    id: str

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    @abstractmethod
    def matches(
        self, ha_device: DeviceEntry, mac: str, ip: str | None
    ) -> bool:
        """True wenn dieser Adapter für das Gerät zuständig ist."""

    @abstractmethod
    async def read_name(self, ip: str) -> str | None:
        """Liest den geräteinternen Namen. None wenn nicht erreichbar."""

    @abstractmethod
    async def write_name(self, ip: str, new_name: str) -> bool:
        """Schreibt den geräteinternen Namen. True bei Erfolg."""

    async def read_state(self, ip: str) -> dict | None:
        """Liest Name + optional Interface-Status in einem Rutsch.

        Return-Shape: {"name": str | None, "interfaces": {"wifi": bool, "eth": bool} | None}.
        Default ruft read_name auf und liefert keine Interface-Info — Adapter
        die mehr wissen (z.B. Shelly RPC mit Shelly.GetStatus) überschreiben das.
        None wenn Gerät nicht erreichbar.
        """
        name = await self.read_name(ip)
        if name is None:
            return None
        return {"name": name, "interfaces": None}

    def ip_from_ha(self, ha_device: DeviceEntry) -> str | None:
        """Fallback-IP aus HA — wenn UniFi keine aktuelle hat (Client-Tracking-Lücke).

        Default: kein Fallback. Adapter überschreiben das wenn die jeweilige
        Integration die IP zuverlässig kennt (z.B. Shelly: entry.data['host']).
        """
        return None
