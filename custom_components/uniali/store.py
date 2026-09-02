"""Persistenter Kleinkram, den uniali über Neustarts hinweg braucht.

Zwei Dinge, beide MAC-basiert (nicht Device-basiert): eine Zeile kann ein
reiner UniFi-Client ohne HA-Gerät sein, an dem sich weder ein Label noch ein
Registry-Eintrag anbringen liesse.

- **ignoriert** — Zeilen, die der User bewusst stumm geschaltet hat. Sie
  bleiben sichtbar, fallen aber aus Mismatch-Zähler und Mismatch-Filter.
- **hostname_geschrieben** — der Wert, den uniali zuletzt als UniFi-Hostname
  gesetzt hat. Damit lässt sich beim nächsten Refresh erkennen, ob der Client
  seinen eigenen Namen wieder durchgedrückt hat (Shelly, ESPHome, Protect-
  Kameras melden ihren Hostnamen per DHCP/mDNS und überschreiben den
  API-Wert beim nächsten Lease). Solche Zeilen zählen nicht als Mismatch —
  sonst stünde das Audit dauerhaft auf Alarm für etwas, das sich nicht
  gewinnen lässt.
"""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

STORAGE_KEY = f"{DOMAIN}.state"
STORAGE_VERSION = 1


class UnialiStore:
    """Dünne Hülle um HA-Storage — lädt einmal, schreibt bei Änderung."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.ignoriert: set[str] = set()
        self.hostname_geschrieben: dict[str, str] = {}

    async def async_load(self) -> None:
        data: dict[str, Any] | None = await self._store.async_load()
        if not data:
            return
        self.ignoriert = {m.lower() for m in data.get("ignoriert", [])}
        self.hostname_geschrieben = {
            m.lower(): v for m, v in (data.get("hostname_geschrieben") or {}).items()
        }

    def _speichern(self) -> None:
        self._store.async_delay_save(
            lambda: {
                "ignoriert": sorted(self.ignoriert),
                "hostname_geschrieben": self.hostname_geschrieben,
            },
            5,
        )

    def set_ignoriert(self, mac: str, ignorieren: bool) -> None:
        if ignorieren:
            self.ignoriert.add(mac)
        else:
            self.ignoriert.discard(mac)
        self._speichern()

    def merke_hostname(self, mac: str, hostname: str) -> None:
        self.hostname_geschrieben[mac] = hostname
        self._speichern()

    def vergiss_mac(self, mac: str) -> None:
        """Nach einem Forget ist der Client weg — die Notizen dazu auch."""
        self.ignoriert.discard(mac)
        self.hostname_geschrieben.pop(mac, None)
        self._speichern()
