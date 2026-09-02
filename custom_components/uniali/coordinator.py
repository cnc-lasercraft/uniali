"""Coordinator: liest UniFi + HA-Devices, baut entries-Liste."""
from __future__ import annotations

import asyncio
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, TypedDict

from aiounifi import Controller
from aiounifi.errors import Forbidden, LoginRequired, Unauthorized
from aiounifi.models.api import ApiRequest
from aiounifi.models.configuration import Configuration

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client, device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .adapters import ADAPTERS
from .adapters.base import DeviceAdapter
from .const import (
    CONF_DNS_DOMAIN,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SITE,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DOMAIN,
    LABEL_OPT_OUT,
)
from .herold import (
    TOPIC_CLIENT_VERGESSEN,
    TOPIC_SYNC_FEHLER,
    TOPIC_SYNC_GERAET,
    TOPIC_SYNC_UNIFI,
    TOPIC_VERBINDUNG_FEHLER,
    async_senden,
)
from .store import UnialiStore

_LOGGER = logging.getLogger(__name__)


class UnialiEntry(TypedDict):
    mac: str
    ha_name: str | None
    unifi_alias: str | None
    unifi_hostname: str | None
    unifi_id: str | None
    device_name: str | None
    device_ip: str | None
    adapter_id: str | None
    in_sync_unifi: bool
    in_sync_device: bool
    sync_unifi_possible: bool
    sync_device_possible: bool
    # Hostname-Spalte: der DHCP-Hostname lässt sich in UniFi überschreiben
    # (PUT /rest/user mit "hostname"), aber er gehört UniFi nicht dauerhaft —
    # der Controller lernt ihn aus DHCP-Option-12/mDNS und überschreibt den
    # API-Wert beim nächsten Lease. Deshalb schreibt derselbe Klick zusätzlich
    # einen echten lokalen DNS-Record (siehe unten), der bleibt.
    # Verglichen wird slug-normalisiert, sonst gälte `Shelly_Mini_DG_TV` vs.
    # `Shelly-Mini-DG-TV` als Unterschied.
    in_sync_hostname: bool
    sync_hostname_possible: bool
    # Wert, den ein Klick schreiben würde (slug aus ha_name) — die Card zeigt
    # ihn im Tooltip, damit sichtbar ist was passiert.
    hostname_target: str | None
    # True, wenn uniali den Hostnamen schon einmal gesetzt hat und UniFi
    # inzwischen wieder etwas anderes zeigt: das Gerät meldet seinen Namen
    # selbst (Shelly, ESPHome, Protect-Kamera). Gegen solche Geräte ist der
    # Hostname nicht zu gewinnen — die Zeile zählt deshalb nicht als Mismatch,
    # der DNS-Record daneben schon.
    hostname_volatile: bool
    # Lokaler DNS-Record (`local_dns_record`) — das persistente Gegenstück zum
    # flüchtigen Hostnamen. UniFi verlangt dafür eine DHCP-Reservation
    # (`api.err.LocalDnsRecordRequiresFixedIp`), die uniali beim Schreiben
    # gleich mit anlegt.
    unifi_dns_record: str | None
    dns_target: str | None
    in_sync_dns: bool
    sync_dns_possible: bool
    # Aktuelle IP aus /stat/sta — nur damit lässt sich eine Reservation
    # anlegen. None = Client offline, DNS-Teil des Klicks entfällt.
    unifi_ip: str | None
    # Vom User stummgeschaltete Zeile: bleibt sichtbar, zählt aber nicht.
    ignored: bool
    # Zentrale Mismatch-Definition — Sensor und Card lesen beide dieses Feld,
    # damit „X offen" und der Filter nie auseinanderlaufen.
    mismatch: bool
    conflict_unifi: str | None
    last_seen: str | None
    # UniFi-Schatten: HA-Device existiert nur weil die UniFi-Integration für
    # jeden Client einen device_tracker anlegt — keine echte Integration
    # (Shelly, ESPHome, …) und kein User-Override per name_by_user. Card
    # versteckt diese standardmässig.
    is_shadow: bool
    # Aktive Netzwerk-Interfaces wenn Adapter das liefert (Shelly: wifi/eth).
    # None heisst „unbekannt" (kein Adapter / nicht erreichbar).
    interfaces: dict | None
    # HA-Device-ID des chosen Devices — Card linkt damit auf die Geräteseite.
    # None bei UniFi-only-Karteileichen.
    device_id: str | None
    # False = UniFi-Client ohne korrespondierendes HA-Device (Karteileiche-Kandidat).
    # In dem Fall sind ha_name/device_name leer, aber unifi_alias/unifi_hostname
    # tragen Identifizierung. Card zeigt diese Einträge nur im Hygiene-Modus.
    ha_known: bool
    # HA-Device-Registry-Eintrag mit name_by_user, aber keine echte (Nicht-
    # UniFi-) Integration mehr — typisch wenn die Original-Integration
    # entfernt wurde (Beispiel: ausgemusterter Shelly mit Tracker-Rest in HA).
    ha_orphan: bool
    # UniFi DHCP-Reservation gesetzt → Forget hat Kollateral-Risiko (neue IP).
    use_fixedip: bool
    is_wired: bool


class UnialiCoordinator(DataUpdateCoordinator[list[UnialiEntry]]):
    """Manueller Coordinator (kein update_interval — Refresh nur per Service)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.entry = entry
        self._controller: Controller | None = None
        self._adapters: list[DeviceAdapter] = [cls(hass) for cls in ADAPTERS]
        self.store = UnialiStore(hass)
        # Suffix für lokale DNS-Records. Kommt entweder aus den Options oder
        # wird bei jedem Refresh aus den bereits vorhandenen Records der Site
        # abgeleitet — siehe _dns_domain_ermitteln.
        self._dns_domain: str | None = None

    async def _ensure_controller(self) -> Controller:
        if self._controller is not None:
            return self._controller
        data = self.entry.data
        session = aiohttp_client.async_get_clientsession(
            self.hass, verify_ssl=data[CONF_VERIFY_SSL]
        )
        config = Configuration(
            session=session,
            host=data[CONF_HOST],
            username=data[CONF_USERNAME],
            password=data[CONF_PASSWORD],
            port=data[CONF_PORT],
            site=data[CONF_SITE],
            ssl_context=data[CONF_VERIFY_SSL],
        )
        controller = Controller(config)
        await controller.login()
        self._controller = controller
        return controller

    def _verwerfe_controller_bei_auth_fehler(self, err: Exception) -> None:
        """Wirft die gecachte Session weg, wenn der Fehler Auth-Natur hat.

        aiounifi heilt eine abgelaufene Session selbst: `Connectivity.request`
        fängt `LoginRequired`, meldet sich neu an und wiederholt den Request.
        Scheitert aber dieser Re-Login (Controller im Neustart →
        "Login Failed: Host starting up"), bleibt `can_retry_login` auf False —
        und dann wirft jeder weitere Request sofort `LoginRequired`, ohne je
        wieder einen Login zu versuchen. Da wir das Controller-Objekt cachen,
        wäre das bis zum HA-Neustart tot.

        Bewusst NUR bei Auth-Fehlern: bei Timeouts und Netzfehlern lebt die
        Session weiter, und ein zweiter Login kurz nach dem ersten quittiert der
        UniFi-Controller mit 403 — ein pauschales Verwerfen würde aus einem
        Netz-Blip eine Login-Sperre machen.
        """
        if isinstance(err, (Forbidden, LoginRequired, Unauthorized)):
            self._controller = None
            _LOGGER.debug("Auth-Fehler (%s) — Controller-Session verworfen", type(err).__name__)

    def _dns_domain_ermitteln(self, users_raw: list[dict[str, Any]]) -> str | None:
        """Suffix für neue DNS-Records: Option gewinnt, sonst Mehrheit der Site.

        Ein lokaler DNS-Record ist ein FQDN (`proxmox2.sood4.ch`) — die Domain
        steht nirgends in der UniFi-Konfiguration, sie steckt nur in den
        Records selbst (die Netzwerk-`domain_name` ist regelmässig
        `localdomain` oder leer und damit unbrauchbar). Statt den User nach
        etwas zu fragen, was seine Site längst weiss, nehmen wir das häufigste
        Suffix der vorhandenen Records. Erst wenn es keinen einzigen gibt,
        braucht es die Option.
        """
        aus_option = (self.entry.options.get(CONF_DNS_DOMAIN) or "").strip().lstrip(".")
        if aus_option:
            return aus_option

        zaehler: dict[str, int] = defaultdict(int)
        for raw in users_raw:
            record = raw.get("local_dns_record")
            if not record or "." not in record:
                continue
            zaehler[record.split(".", 1)[1].lower()] += 1
        if not zaehler:
            return None
        return max(zaehler.items(), key=lambda kv: kv[1])[0]

    async def _async_update_data(self) -> list[UnialiEntry]:
        # clients_all = /rest/user (alias-DB, source of truth für _id)
        # clients     = /stat/sta (aktive Clients, gibt uns die IP)
        # Direkt via request() statt controller.clients_all.update() — die
        # aiounifi-Handler aggregieren nur, entfernen aber gelöschte Einträge
        # nicht aus ihrem internen Dict. Nach einem forget-sta blieben sonst
        # die forgotten MACs für immer sichtbar bis HA-Restart.
        try:
            controller = await self._ensure_controller()
            users_resp = await controller.request(
                ApiRequest(method="get", path="/rest/user")
            )
            sta_resp = await controller.request(
                ApiRequest(method="get", path="/stat/sta")
            )
        except Exception as err:  # noqa: BLE001
            self._verwerfe_controller_bei_auth_fehler(err)
            # Nur die Flanke ok → Fehler melden. Ohne diese Bedingung würde
            # jeder Refresh-Klick bei totem Controller erneut Herold füttern.
            if self.last_update_success:
                await async_senden(
                    self.hass,
                    TOPIC_VERBINDUNG_FEHLER,
                    "UniFi-Controller nicht erreichbar",
                    f"Refresh fehlgeschlagen: {err}",
                    severity="warnung",
                )
            raise UpdateFailed(f"UniFi-Abfrage fehlgeschlagen: {err}") from err
        users_raw: list[dict[str, Any]] = users_resp.get("data") or []
        sta_raw: list[dict[str, Any]] = sta_resp.get("data") or []

        # Index: MAC → UniFi-Client-Daten (von clients_all = user-DB)
        unifi_by_mac: dict[str, dict[str, Any]] = {}
        alias_to_macs: dict[str, list[str]] = defaultdict(list)

        for raw in users_raw:
            mac = _norm_mac(raw.get("mac"))
            if not mac:
                continue
            alias = raw.get("name") or None
            unifi_by_mac[mac] = {
                "alias": alias,
                "hostname": raw.get("hostname") or None,
                "ip": None,  # wird aus aktiven Clients ergänzt
                "_id": raw.get("_id"),
                "last_seen": raw.get("last_seen"),
                # use_fixedip = UniFi-DHCP-Reservation → Hygiene-Warnsignal vor
                # Forget, und Voraussetzung für einen lokalen DNS-Record.
                "use_fixedip": bool(raw.get("use_fixedip")),
                "dns_record": (
                    raw.get("local_dns_record")
                    if raw.get("local_dns_record_enabled")
                    else None
                )
                or None,
                "is_wired": bool(raw.get("is_wired")),
            }
            if alias:
                alias_to_macs[alias].append(mac)

        self._dns_domain = self._dns_domain_ermitteln(users_raw)

        # IP + frisches last_seen + ggf. aktuellerer Hostname aus aktiven Clients
        for raw in sta_raw:
            mac = _norm_mac(raw.get("mac"))
            if not mac or mac not in unifi_by_mac:
                continue
            if raw.get("ip"):
                unifi_by_mac[mac]["ip"] = raw["ip"]
            if raw.get("last_seen"):
                unifi_by_mac[mac]["last_seen"] = raw["last_seen"]
            if raw.get("hostname") and not unifi_by_mac[mac]["hostname"]:
                unifi_by_mac[mac]["hostname"] = raw["hostname"]

        # Alle HA-Devices mit MAC einsammeln, per Opt-Out + disabled gefiltert,
        # gruppiert nach MAC (mehrere HA-Devices pro MAC sind häufig: HA-UniFi-
        # Integration legt für jeden Client einen device_tracker an, parallel zur
        # "echten" Integration wie Shelly/ESPHome).
        device_reg = dr.async_get(self.hass)
        devices_by_mac: dict[str, list[dr.DeviceEntry]] = defaultdict(list)
        for d in device_reg.devices.values():
            if LABEL_OPT_OUT in d.labels or d.disabled_by:
                continue
            mac = _extract_mac(d)
            if mac:
                devices_by_mac[mac].append(d)

        # Phase 1: pro MAC zusammensetzen was wir wissen, ohne Adapter-Reads
        # (die kommen gleich gebündelt parallel)
        partials: list[dict[str, Any]] = []
        for mac, candidates in devices_by_mac.items():
            if mac not in unifi_by_mac:
                continue
            unifi = unifi_by_mac[mac]
            unifi_hostname = unifi.get("hostname")

            ha_name: str | None = None
            device: dr.DeviceEntry | None = None
            user_named = False
            for d in candidates:
                if d.name_by_user:
                    ha_name = d.name_by_user
                    device = d
                    user_named = True
                    break
            if not ha_name:
                for d in candidates:
                    if d.name and d.name != unifi_hostname:
                        ha_name = d.name
                        device = d
                        break
            if not ha_name or device is None:
                continue

            # Schatten = MAC hat in HA *ausschliesslich* UniFi-Integration-Devices
            # (keine echte Integration wie Shelly/ESPHome/Apple) UND kein
            # name_by_user-Override. Solche Einträge entstehen automatisch über
            # die UniFi-device_tracker-Spawning und tragen meist alten/keinen
            # echten HA-Intent — Card blendet sie default aus.
            has_real_integration = False
            for d in candidates:
                for entry_id in d.config_entries:
                    cfg = self.hass.config_entries.async_get_entry(entry_id)
                    if cfg and cfg.domain != "unifi":
                        has_real_integration = True
                        break
                if has_real_integration:
                    break
            is_shadow = not user_named and not has_real_integration
            # HA-orphan = Device trägt im Registry einen Identifier einer
            # Integration, deren ConfigEntry nicht mehr existiert (Beispiel:
            # `identifiers: [["shelly", "..."]]` aber kein shelly-ConfigEntry
            # mehr → die Shelly-Integration wurde mal entfernt, der Tracker
            # hängt am User-Namen fest). Geräte die *nie* eine eigene
            # Integration hatten (Drucker, IP-Cams, NAS, Proxmox) haben leere
            # identifiers und sind keine Orphans, sondern „nur durch UniFi
            # bekannte" Geräte.
            ha_orphan = False
            for d in candidates:
                cfg_domains: set[str] = set()
                for entry_id in d.config_entries:
                    cfg = self.hass.config_entries.async_get_entry(entry_id)
                    if cfg is not None:
                        cfg_domains.add(cfg.domain)
                for identifier in d.identifiers:
                    if (
                        identifier
                        and len(identifier) >= 1
                        and identifier[0] not in cfg_domains
                    ):
                        ha_orphan = True
                        break
                if ha_orphan:
                    break

            chosen_adapter: DeviceAdapter | None = None
            for adapter in self._adapters:
                if adapter.matches(device, mac, unifi.get("ip")):
                    chosen_adapter = adapter
                    break

            # ESPHome-Name aus dem HA-Registry — gibt es ein Device unter dieser
            # MAC mit ESPHome-Integration, ist `d.name` der YAML-`name:` (bzw.
            # friendly_name). Wir zeigen ihn read-only in Spalte 3 wenn kein
            # Live-Adapter vorhanden ist — ESP-Namen sind compile-time, nur per
            # Re-Flash änderbar.
            esphome_name = self._find_esphome_name(candidates)

            partials.append(
                {
                    "mac": mac,
                    "ha_name": ha_name,
                    "device": device,
                    "unifi": unifi,
                    "adapter": chosen_adapter,
                    "is_shadow": is_shadow,
                    "ha_orphan": ha_orphan,
                    "esphome_name": esphome_name,
                }
            )

        # Phase 1.5: IP-basierter Sekundär-Join für Geräte deren HA-MAC und
        # UniFi-MAC sich unterscheiden (Multi-Interface-Hardware: Shelly Pro
        # base+0/+3, SLZB Eth/WLAN-Chip, etc.). Wir suchen zu jedem UniFi-
        # Eintrag mit IP ein HA-Device das via ConfigEntry.data["host"] auf
        # dieselbe IP zeigt — das ist derselbe physische Apparat.
        # Verhalten: (a) UniFi-MAC noch nicht in partials → neu hinzufügen.
        # (b) UniFi-MAC ist als Schatten gematched → mit echtem Device upgraden.
        # (c) UniFi-MAC ist mit echtem Device gematched → unverändert lassen.
        partial_by_mac = {p["mac"]: p for p in partials}
        used_ha_devices = {p["device"].id for p in partials}

        ip_to_entries: dict[str, list[Any]] = defaultdict(list)
        for cfg in self.hass.config_entries.async_entries():
            if cfg.domain == "unifi":
                continue  # UniFi-Controller-Entry mit host=Controller-IP raus
            host = cfg.data.get("host")
            if isinstance(host, str) and host:
                # Host ist meist die IP, kann aber Hostname oder host:port sein.
                # Wir nehmen den Teil vor ":" und behandeln ihn als IP-Kandidat.
                ip = host.split(":", 1)[0].strip()
                if ip and ip[0].isdigit():
                    ip_to_entries[ip].append(cfg)

        for unifi_mac, unifi_data in unifi_by_mac.items():
            existing = partial_by_mac.get(unifi_mac)
            if existing is not None and not existing["is_shadow"]:
                continue  # echtes Match steht — nicht anfassen

            ip = unifi_data.get("ip")
            if not ip or ip not in ip_to_entries:
                continue

            # Beim Upgrade darf das aktuell vom Schatten belegte Device-ID neu
            # vergeben werden — der Schatten ist gleich weg.
            block = used_ha_devices.copy()
            if existing is not None:
                block.discard(existing["device"].id)

            best_device: dr.DeviceEntry | None = None
            best_score = -1
            for cfg in ip_to_entries[ip]:
                for d in device_reg.devices.values():
                    if (
                        LABEL_OPT_OUT in d.labels
                        or d.disabled_by
                        or d.id in block
                        or cfg.entry_id not in d.config_entries
                        # Sub-Devices (Shelly-Relais via switch_as_x, generische
                        # via_device-Children) ausschliessen — wir wollen den
                        # primären Apparat, nicht eine seiner Funktionen.
                        or d.via_device_id is not None
                    ):
                        continue
                    score = (2 if d.name_by_user else 0) + (1 if d.name else 0)
                    if score > best_score:
                        best_device = d
                        best_score = score

            if best_device is None:
                continue
            ha_name = best_device.name_by_user or best_device.name
            if not ha_name:
                continue

            chosen_adapter = None
            for adapter in self._adapters:
                if adapter.matches(best_device, unifi_mac, ip):
                    chosen_adapter = adapter
                    break

            esphome_name = self._find_esphome_name([best_device])

            # Per Konstruktion ist hier eine Nicht-UniFi-Integration im Spiel
            # (cfg.domain != "unifi") → kein Shadow.
            new_partial = {
                "mac": unifi_mac,
                "ha_name": ha_name,
                "device": best_device,
                "unifi": unifi_data,
                "adapter": chosen_adapter,
                "is_shadow": False,
                # Per Konstruktion echte Integration vorhanden (Phase 1.5
                # läuft via cfg.domain != "unifi") → kein HA-orphan.
                "ha_orphan": False,
                "esphome_name": esphome_name,
                # IP-Joins können falsch sein wenn die HA-ConfigEntry-IP veraltet
                # ist und DHCP sie inzwischen einem anderen Gerät zugewiesen hat
                # (Beispiel: schlafender batteriebetriebener Shelly Button → IP
                # wandert an eine Miele-Spülmaschine). Wir markieren den Join,
                # validieren ihn nach dem Adapter-Read und verwerfen wenn der
                # Adapter dort nichts findet.
                "via_ip": True,
            }
            if existing is not None:
                # Upgrade: in-place ersetzen, used_ha_devices anpassen
                used_ha_devices.discard(existing["device"].id)
                idx = partials.index(existing)
                partials[idx] = new_partial
                partial_by_mac[unifi_mac] = new_partial
            else:
                partials.append(new_partial)
                partial_by_mac[unifi_mac] = new_partial
            used_ha_devices.add(best_device.id)

        # Phase 1.6: UniFi-only-Karteileichen — UniFi kennt diese MACs aber HA
        # hat keinen passenden Device-Eintrag. Die landen normalerweise nicht
        # im Audit, sind aber genau die Hygiene-Kandidaten (alte Gäste, MAC-
        # Privacy-Rotationen, ausgemusterte Hardware). Wir nehmen sie mit als
        # ha_known=False — Card zeigt sie nur im Hygiene-Modus.
        for unifi_mac, unifi_data in unifi_by_mac.items():
            if unifi_mac in partial_by_mac:
                continue
            partials.append(
                {
                    "mac": unifi_mac,
                    "ha_name": None,
                    "device": None,
                    "unifi": unifi_data,
                    "adapter": None,
                    "is_shadow": False,
                    "ha_known": False,
                }
            )

        # Phase 2: alle Adapter-Reads parallel (sonst dauert ein Refresh
        # mit 80 Shellys minutenlang). Semaphore beschränkt Burst auf 20
        # gleichzeitige HTTP-Calls — fair zu Netz und Geräten.
        sem = asyncio.Semaphore(20)

        async def _read(adapter: DeviceAdapter, ip: str) -> dict | None:
            async with sem:
                try:
                    return await adapter.read_state(ip)
                except Exception:  # noqa: BLE001
                    return None

        # IP-Auflösung: UniFi-IP bevorzugt (frisch aus /stat/sta), Fallback
        # auf Adapter-spezifische Quelle (z.B. Shelly entry.data['host']) wenn
        # UniFi den Client gerade nicht aktiv trackt.
        for p in partials:
            ip = p["unifi"].get("ip")
            if not ip and p["adapter"]:
                ip = p["adapter"].ip_from_ha(p["device"])
            p["effective_ip"] = ip

        read_tasks: list[asyncio.Task] = []
        read_index: list[int] = []
        for i, p in enumerate(partials):
            ip = p["effective_ip"]
            if p["adapter"] and ip:
                read_tasks.append(asyncio.create_task(_read(p["adapter"], ip)))
                read_index.append(i)
        results = await asyncio.gather(*read_tasks) if read_tasks else []
        for idx, state in zip(read_index, results):
            if state:
                partials[idx]["device_name"] = state.get("name")
                partials[idx]["interfaces"] = state.get("interfaces")
            else:
                partials[idx]["read_failed"] = True

        # Phase 2.5: bogus IP-Joins zurückstufen. Wenn ein per IP zusammen-
        # gefügter Eintrag einen Adapter zugewiesen bekam (= „HA glaubt das ist
        # ein Shelly") aber der Adapter beim Read keinerlei Antwort vom Gerät
        # auf der IP bekam, war der Join falsch (typischer Fall: stale HA-
        # Config-Entry-Host). Die HA-Identität ist damit hinfällig — der
        # UniFi-Client selbst existiert aber sehr wohl und gehört als
        # Karteileiche in den Hygiene-Modus (wie Phase 1.6). Ihn ganz zu
        # streichen liesse ihn aus Audit *und* Hygiene verschwinden: genau die
        # Clients, die niemand mehr sieht, wären dann unsichtbar.
        for i, p in enumerate(partials):
            if p.get("via_ip") and p.get("adapter") and p.get("read_failed"):
                partials[i] = {
                    "mac": p["mac"],
                    "ha_name": None,
                    "device": None,
                    "unifi": p["unifi"],
                    "adapter": None,
                    "is_shadow": False,
                    "ha_known": False,
                    "effective_ip": p["unifi"].get("ip"),
                }

        # Phase 3: Entries komplett bauen
        entries: list[UnialiEntry] = []
        for p in partials:
            mac = p["mac"]
            ha_known = p.get("ha_known", True)
            ha_name = p["ha_name"]
            unifi = p["unifi"]
            unifi_alias = unifi.get("alias")
            device_ip = p.get("effective_ip")
            adapter_id = p["adapter"].id if p["adapter"] else None
            device_name = p.get("device_name")
            # ESPHome-Fallback für Spalte 3: kein Live-Adapter, aber wir kennen
            # den YAML-Namen aus dem HA-Registry. Wird read-only angezeigt —
            # Card erkennt die Read-only-Quelle an `adapter_id is None` plus
            # gefülltem `device_name`.
            if not device_name and p.get("esphome_name"):
                device_name = p["esphome_name"]

            if ha_known:
                conflict_mac: str | None = None
                other = [m for m in alias_to_macs.get(ha_name, []) if m != mac]
                if other:
                    conflict_mac = other[0]

                in_sync_unifi = ha_name == unifi_alias
                in_sync_device = ha_name == device_name
                sync_unifi_possible = (
                    ha_name != unifi_alias and conflict_mac is None
                )
                sync_device_possible = (
                    in_sync_unifi
                    and adapter_id is not None
                    and device_ip is not None
                    and ha_name != device_name
                )

                hostname_target = _host_slug(ha_name)
                in_sync_hostname = (
                    hostname_target is not None
                    and _host_slug(unifi.get("hostname")) == hostname_target
                )
            else:
                # Orphan: keine HA-Identität, keine Sync-Aktionen — nur Hygiene.
                conflict_mac = None
                in_sync_unifi = True
                in_sync_device = True
                sync_unifi_possible = False
                sync_device_possible = False
                # Karteileichen haben keinen HA-Namen als Quelle — nichts zu
                # schreiben, und „in sync" hält sie aus der Mismatch-Zählung.
                in_sync_hostname = True
                hostname_target = None

            # DNS-Record: gleiche Quelle wie der Hostname, nur als FQDN. Ohne
            # bekannte Domain gibt es kein Ziel und damit keinen DNS-Teil.
            dns_record = unifi.get("dns_record")
            dns_target = (
                f"{hostname_target}.{self._dns_domain}"
                if hostname_target and self._dns_domain
                else None
            )
            in_sync_dns = dns_target is not None and (
                (dns_record or "").lower() == dns_target
            )
            sync_dns_possible = dns_target is not None and not in_sync_dns

            # Hat uniali den Hostnamen hier schon einmal gesetzt und UniFi
            # zeigt trotzdem etwas anderes? Dann meldet das Gerät seinen Namen
            # selbst und drückt ihn beim nächsten DHCP-Lease wieder durch.
            geschrieben = self.store.hostname_geschrieben.get(mac)
            hostname_volatile = bool(
                geschrieben
                and _host_slug(unifi.get("hostname")) != _host_slug(geschrieben)
            )
            # Knopf anbieten, solange irgendeine der beiden Seiten abweicht —
            # ein Klick schreibt beides.
            sync_hostname_possible = hostname_target is not None and (
                not in_sync_hostname or sync_dns_possible
            )

            ignored = mac in self.store.ignoriert

            entry = UnialiEntry(
                mac=mac,
                ha_name=ha_name,
                unifi_alias=unifi_alias,
                unifi_hostname=unifi.get("hostname"),
                unifi_id=unifi.get("_id"),
                device_name=device_name,
                device_ip=device_ip,
                adapter_id=adapter_id,
                in_sync_unifi=in_sync_unifi,
                in_sync_device=in_sync_device,
                sync_unifi_possible=sync_unifi_possible,
                sync_device_possible=sync_device_possible,
                in_sync_hostname=in_sync_hostname,
                sync_hostname_possible=sync_hostname_possible,
                hostname_target=hostname_target,
                hostname_volatile=hostname_volatile,
                unifi_dns_record=dns_record,
                dns_target=dns_target,
                in_sync_dns=in_sync_dns,
                sync_dns_possible=sync_dns_possible,
                unifi_ip=unifi.get("ip"),
                ignored=ignored,
                conflict_unifi=conflict_mac,
                last_seen=_iso(unifi.get("last_seen")),
                is_shadow=p["is_shadow"],
                interfaces=p.get("interfaces"),
                device_id=p["device"].id if p.get("device") else None,
                ha_known=ha_known,
                ha_orphan=p.get("ha_orphan", False),
                use_fixedip=bool(unifi.get("use_fixedip")),
                is_wired=bool(unifi.get("is_wired")),
                mismatch=False,  # gleich unten aus dem fertigen Eintrag
            )
            entry["mismatch"] = _ist_mismatch(entry)
            entries.append(entry)

        # Sortierung: Mismatches oben, dann ha_known-Devices, dann alphabetisch.
        # Bewusst über das zentrale `mismatch`-Feld — so wandern stummgeschaltete
        # Zeilen nach unten, statt oben Aufmerksamkeit zu beanspruchen.
        entries.sort(
            key=lambda e: (
                not e["mismatch"],
                not e["ha_known"],  # ha_known=True zuerst
                (e["ha_name"] or e["unifi_alias"] or e["unifi_hostname"] or e["mac"] or "").casefold(),
            )
        )
        return entries

    async def async_sync_unifi(self, mac: str) -> None:
        mac = _norm_mac(mac)
        entries = self.data or []
        target = next((e for e in entries if e["mac"] == mac), None)
        if target is None or not target["sync_unifi_possible"]:
            _LOGGER.warning("sync_unifi abgelehnt für %s (nicht möglich)", mac)
            await async_senden(
                self.hass,
                TOPIC_SYNC_FEHLER,
                "UniFi-Sync abgelehnt",
                f"{_label(target) if target else mac}: Sync nicht möglich — "
                "Namenskonflikt oder veralteter Datenstand (Refresh nötig).",
                severity="warnung",
            )
            return
        if not target["unifi_id"]:
            _LOGGER.warning("sync_unifi: kein UniFi-_id für %s — Refresh nötig", mac)
            await async_senden(
                self.hass,
                TOPIC_SYNC_FEHLER,
                "UniFi-Sync abgelehnt",
                f"{_label(target)}: kein UniFi-_id bekannt — Refresh nötig.",
                severity="warnung",
            )
            return
        vorher = target["unifi_alias"]
        controller = await self._ensure_controller()
        try:
            await controller.request(
                ApiRequest(
                    method="put",
                    path=f"/rest/user/{target['unifi_id']}",
                    data={"name": target["ha_name"]},
                )
            )
        except Exception as err:  # noqa: BLE001
            self._verwerfe_controller_bei_auth_fehler(err)
            _LOGGER.exception("sync_unifi: Schreiben fehlgeschlagen für %s", mac)
            await async_senden(
                self.hass,
                TOPIC_SYNC_FEHLER,
                "UniFi-Sync fehlgeschlagen",
                f"{_label(target)}: UniFi-API-Fehler beim Setzen des Alias — {err}",
                severity="warnung",
            )
            return
        await async_senden(
            self.hass,
            TOPIC_SYNC_UNIFI,
            "UniFi-Alias gesetzt",
            f"{target['ha_name']} ({mac}): Alias "
            f"{vorher or '—'} → {target['ha_name']}",
        )
        # Optimistic update reicht — kein Auto-Refresh hinterher.
        # Sonst überschreibt ein in-flight Refresh die optimistic Daten
        # mit Stand vor dem zweiten Klick (UniFi-eventual-consistency).
        # User kann via ⟳ manuell verifizieren wenn gewünscht.
        self._optimistic_update(mac, unifi_alias=target["ha_name"])

    async def async_sync_hostname(
        self, mac: str, hostname: str | None = None
    ) -> None:
        """Setzt Hostname *und* lokalen DNS-Record des UniFi-Clients.

        Bewusst eine eigene Aktion und nicht Teil von `sync_unifi`: der Alias
        ist reine UniFi-Kosmetik, dieser Klick wirkt über die Card hinaus — er
        legt bei Bedarf eine DHCP-Reservation an und einen DNS-Namen
        `<name>.<domain>`, unter dem das Gerät danach im ganzen Netz auflöst.

        Warum beides: der `hostname` allein hält nicht. UniFi lernt ihn aus
        DHCP-Option-12/mDNS und überschreibt den API-Wert beim nächsten Lease,
        sobald das Gerät seinen eigenen Namen meldet (Shelly, ESPHome,
        Protect-Kameras). Stille Geräte behalten ihn — deshalb wird er
        weiterhin geschrieben, nur eben nicht mehr als einziges.

        Ohne `hostname` ist die Quelle der HA-Name der Zeile. Mit `hostname`
        wird ein freier Wert geschrieben — der Weg für reine UniFi-Clients
        (Kameras, Drucker, alles ohne HA-Gerät), die gar keinen HA-Namen
        haben, aber genau die Geräte sind, die sich unter einem Müll-Namen
        melden.
        """
        mac = _norm_mac(mac)
        entries = self.data or []
        target = next((e for e in entries if e["mac"] == mac), None)
        if hostname is not None:
            frei = _host_slug(hostname)
            if target is None or not frei:
                _LOGGER.warning(
                    "sync_hostname abgelehnt für %s (unbekannt oder leerer Wert)", mac
                )
                await async_senden(
                    self.hass,
                    TOPIC_SYNC_FEHLER,
                    "Hostname-Sync abgelehnt",
                    f"{_label(target) if target else mac}: "
                    f"„{hostname}“ ergibt keinen gültigen Hostnamen.",
                    severity="warnung",
                )
                return
            await self._async_hostname_schreiben(target, frei)
            return
        if target is None or not target["sync_hostname_possible"]:
            _LOGGER.warning("sync_hostname abgelehnt für %s (nicht möglich)", mac)
            await async_senden(
                self.hass,
                TOPIC_SYNC_FEHLER,
                "Hostname-Sync abgelehnt",
                f"{_label(target) if target else mac}: Sync nicht möglich — "
                "kein HA-Name oder veralteter Datenstand (Refresh nötig).",
                severity="warnung",
            )
            return
        await self._async_hostname_schreiben(target, target["hostname_target"])

    async def _async_hostname_schreiben(
        self, target: UnialiEntry, neuer_host: str | None
    ) -> None:
        """Gemeinsamer Schreibpfad für beide Hostname-Quellen (HA-Name / frei)."""
        mac = target["mac"]
        if not target["unifi_id"]:
            _LOGGER.warning("sync_hostname: kein UniFi-_id für %s — Refresh nötig", mac)
            await async_senden(
                self.hass,
                TOPIC_SYNC_FEHLER,
                "Hostname-Sync abgelehnt",
                f"{_label(target)}: kein UniFi-_id bekannt — Refresh nötig.",
                severity="warnung",
            )
            return
        vorher = target["unifi_hostname"]
        payload: dict[str, Any] = {"hostname": neuer_host}

        # DNS-Teil: nur mit bekannter Domain, und nur mit einer IP, auf die
        # sich eine Reservation setzen lässt. Ein Client, der gerade offline
        # ist, hat keine — seine letzte IP kann längst woanders hängen, eine
        # Reservation darauf wäre geraten. Dann bleibt es beim Hostnamen.
        dns_ziel = (
            f"{neuer_host}.{self._dns_domain}"
            if neuer_host and self._dns_domain
            else None
        )
        dns_hinweis = ""
        if dns_ziel and target["use_fixedip"]:
            # Reservation existiert schon — IP nicht anfassen, nur den Record.
            payload["local_dns_record"] = dns_ziel
            payload["local_dns_record_enabled"] = True
        elif dns_ziel and target["unifi_ip"]:
            payload["use_fixedip"] = True
            payload["fixed_ip"] = target["unifi_ip"]
            payload["local_dns_record"] = dns_ziel
            payload["local_dns_record_enabled"] = True
        elif dns_ziel:
            dns_hinweis = " (ohne DNS-Record — Client offline, keine IP für die Reservation)"
            dns_ziel = None
        elif neuer_host:
            dns_hinweis = " (ohne DNS-Record — keine Domain bekannt, siehe Optionen)"

        controller = await self._ensure_controller()
        try:
            await controller.request(
                ApiRequest(
                    method="put",
                    path=f"/rest/user/{target['unifi_id']}",
                    data=payload,
                )
            )
        except Exception as err:  # noqa: BLE001
            self._verwerfe_controller_bei_auth_fehler(err)
            _LOGGER.exception("sync_hostname: Schreiben fehlgeschlagen für %s", mac)
            await async_senden(
                self.hass,
                TOPIC_SYNC_FEHLER,
                "Hostname-Sync fehlgeschlagen",
                f"{_label(target)}: UniFi-API-Fehler beim Setzen des Hostnamens — {err}",
                severity="warnung",
            )
            return
        # Geschriebenen Wert merken: weicht der Hostname beim nächsten Refresh
        # wieder ab, meldet das Gerät seinen Namen selbst (→ hostname_volatile).
        if neuer_host:
            self.store.merke_hostname(mac, neuer_host)
        await async_senden(
            self.hass,
            TOPIC_SYNC_UNIFI,
            "UniFi-Hostname gesetzt",
            f"{_label(target)}: Hostname {vorher or '—'} → {neuer_host}"
            + (f", DNS-Record {dns_ziel}" if dns_ziel else dns_hinweis),
        )
        self._optimistic_update(
            mac,
            unifi_hostname=neuer_host,
            unifi_dns_record=dns_ziel,
            fixedip_gesetzt="fixed_ip" in payload,
        )

    def set_ignoriert(self, mac: str, ignorieren: bool) -> None:
        """Schaltet eine Zeile für Mismatch-Zähler und -Filter stumm (oder
        wieder laut). Die Zeile bleibt sichtbar — Stummschalten ist kein
        Verstecken, sonst verliert man sie aus dem Blick."""
        mac = _norm_mac(mac)
        self.store.set_ignoriert(mac, ignorieren)
        if not self.data:
            return
        new_data: list[UnialiEntry] = []
        for e in self.data:
            if e["mac"] != mac:
                new_data.append(e)
                continue
            updated = dict(e)
            updated["ignored"] = ignorieren
            updated["mismatch"] = _ist_mismatch(updated)  # type: ignore[arg-type]
            new_data.append(updated)  # type: ignore[arg-type]
        self.async_set_updated_data(new_data)

    async def async_forget_unifi(self, mac: str) -> None:
        """Lässt UniFi den Client komplett vergessen (= Eintrag aus /rest/user
        entfernen). Verliert: Alias, Fixed-IP-Reservation, User-Group-Membership,
        Block-Status, Stats. Beim nächsten Reconnect entsteht ein frischer
        Eintrag ohne Pflege."""
        mac = _norm_mac(mac)
        # Bezeichnung für die Meldung sichern, bevor der Eintrag verschwindet.
        target = next((e for e in (self.data or []) if e["mac"] == mac), None)
        # Optimistic FIRST — Card soll sofort reagieren, sonst fühlt sich der
        # Klick wie "tut nichts" an (UniFi-API kostet 200-500 ms). Falls die
        # API danach scheitert, korrigiert der nächste Refresh die Liste.
        if self.data:
            new_data = [e for e in self.data if e["mac"] != mac]
            if len(new_data) != len(self.data):
                self.async_set_updated_data(new_data)
        controller = await self._ensure_controller()
        try:
            await controller.request(
                ApiRequest(
                    method="post",
                    path="/cmd/stamgr",
                    data={"cmd": "forget-sta", "macs": [mac]},
                )
            )
        except Exception as err:  # noqa: BLE001
            self._verwerfe_controller_bei_auth_fehler(err)
            _LOGGER.exception("forget-sta für %s fehlgeschlagen", mac)
            await async_senden(
                self.hass,
                TOPIC_SYNC_FEHLER,
                "Forget fehlgeschlagen",
                f"{_label(target) if target else mac}: forget-sta abgelehnt — {err}",
                severity="warnung",
            )
            await self.async_request_refresh()
            return
        # Der Client ist weg — unsere Notizen dazu (Stummschaltung, zuletzt
        # geschriebener Hostname) hätten sonst ewig Bestand.
        self.store.vergiss_mac(mac)
        await async_senden(
            self.hass,
            TOPIC_CLIENT_VERGESSEN,
            "UniFi-Client vergessen",
            f"{_label(target) if target else mac} aus der UniFi-Datenbank "
            "entfernt (Alias, Fixed-IP, Gruppe, Stats verloren).",
        )

    async def async_sync_device(self, mac: str) -> None:
        mac = _norm_mac(mac)
        entries = self.data or []
        target = next((e for e in entries if e["mac"] == mac), None)
        if target is None or not target["sync_device_possible"]:
            _LOGGER.warning("sync_device abgelehnt für %s (nicht möglich)", mac)
            await async_senden(
                self.hass,
                TOPIC_SYNC_FEHLER,
                "Geräte-Sync abgelehnt",
                f"{_label(target) if target else mac}: Sync nicht möglich — "
                "UniFi-Alias noch nicht synchron, kein Adapter, keine IP oder "
                "veralteter Datenstand.",
                severity="warnung",
            )
            return
        adapter = next(
            (a for a in self._adapters if a.id == target["adapter_id"]), None
        )
        if adapter is None or not target["device_ip"]:
            return
        vorher = target["device_name"]
        ok = await adapter.write_name(target["device_ip"], target["ha_name"])
        if not ok:
            _LOGGER.warning("sync_device: Schreiben fehlgeschlagen für %s", mac)
            await async_senden(
                self.hass,
                TOPIC_SYNC_FEHLER,
                "Geräte-Sync fehlgeschlagen",
                f"{_label(target)}: {adapter.id} unter {target['device_ip']} "
                "hat den Namen nicht übernommen (nicht erreichbar oder "
                "Read-back-Mismatch).",
                severity="warnung",
            )
            return
        self._optimistic_update(mac, device_name=target["ha_name"])
        await async_senden(
            self.hass,
            TOPIC_SYNC_GERAET,
            "Gerätename gesetzt",
            f"{target['ha_name']} ({mac}, {adapter.id}): Gerätename "
            f"{vorher or '—'} → {target['ha_name']}",
        )

    def _find_esphome_name(self, candidates: list[dr.DeviceEntry]) -> str | None:
        """Sucht in einer Liste von HA-Devices das erste mit ESPHome-Integration
        und gibt dessen Registry-`name` zurück (= YAML-`name:` bzw. friendly_name
        aus dem ESPHome-Firmware-Build)."""
        for d in candidates:
            for entry_id in d.config_entries:
                cfg = self.hass.config_entries.async_get_entry(entry_id)
                if cfg and cfg.domain == "esphome":
                    return d.name
        return None

    def _optimistic_update(
        self,
        mac: str,
        *,
        unifi_alias: str | None = None,
        device_name: str | None = None,
        unifi_hostname: str | None = None,
        unifi_dns_record: str | None = None,
        fixedip_gesetzt: bool = False,
    ) -> None:
        """Mutiere die gecachte Liste sofort + pushe an Entities, damit die Card
        nach einem Sync-Klick nicht 5+ Sekunden auf den nächsten Refresh wartet.
        Der reguläre Refresh läuft hinterher und bestätigt/korrigiert."""
        if not self.data:
            return
        new_data: list[UnialiEntry] = []
        for e in self.data:
            if e["mac"] != mac:
                new_data.append(e)
                continue
            updated = dict(e)
            if unifi_alias is not None:
                updated["unifi_alias"] = unifi_alias
                updated["in_sync_unifi"] = updated["ha_name"] == unifi_alias
                updated["sync_unifi_possible"] = False
                # Geräte-Sync hängt an in_sync_unifi — sofort neu bewerten,
                # sonst ist der ⇨ in Spalte 3 bis zum nächsten Refresh tot.
                updated["sync_device_possible"] = (
                    updated["in_sync_unifi"]
                    and updated["adapter_id"] is not None
                    and updated["device_ip"] is not None
                    and updated["ha_name"] != updated["device_name"]
                )
            if device_name is not None:
                updated["device_name"] = device_name
                updated["in_sync_device"] = updated["ha_name"] == device_name
                updated["sync_device_possible"] = False
            if unifi_hostname is not None:
                updated["unifi_hostname"] = unifi_hostname
                updated["in_sync_hostname"] = True
                # Ob der Wert hält, weiss erst der nächste Refresh — bis dahin
                # gilt er als gesetzt und die Zeile ist nicht mehr flüchtig.
                updated["hostname_volatile"] = False
            if unifi_dns_record is not None:
                updated["unifi_dns_record"] = unifi_dns_record
                updated["in_sync_dns"] = True
                updated["sync_dns_possible"] = False
            if fixedip_gesetzt:
                updated["use_fixedip"] = True
            if unifi_hostname is not None or unifi_dns_record is not None:
                updated["sync_hostname_possible"] = bool(
                    updated["sync_dns_possible"] or not updated["in_sync_hostname"]
                )
            # Mismatch neu bewerten — Sensor und Filter hängen daran.
            updated["mismatch"] = _ist_mismatch(updated)  # type: ignore[arg-type]
            new_data.append(updated)  # type: ignore[arg-type]
        self.async_set_updated_data(new_data)


def _ist_mismatch(e: UnialiEntry) -> bool:
    """Die eine Mismatch-Definition — Sensor, Card-Filter und Sortierung lesen
    alle dieses Ergebnis.

    Zwei bewusste Abgrenzungen in der Hostname-Spalte:

    1. Ein *fehlender* DNS-Record ist keine Abweichung, sondern ein nie
       eingerichteter Sonderfall. Zählte er mit, stünden auf einen Schlag alle
       ~180 HA-Geräte im Audit, und jeder Klick zur Beruhigung würde eine
       DHCP-Reservation anlegen. Gezählt wird nur echte Drift: ein Record ist
       da und zeigt etwas anderes.
    2. Ein zurückgefallener Hostname zählt nicht. Gegen ein Gerät, das seinen
       Namen per DHCP selbst meldet, ist er nicht zu gewinnen — das Audit
       stünde dauerhaft auf Alarm für etwas, das kein Klick heilt.
    """
    if e["ignored"]:
        return False
    if e["sync_unifi_possible"] or e["sync_device_possible"] or e["conflict_unifi"]:
        return True
    if e["hostname_target"] is None:
        return False
    dns_drift = bool(e["unifi_dns_record"]) and e["sync_dns_possible"]
    hostname_drift = not e["in_sync_hostname"] and not e["hostname_volatile"]
    return dns_drift or hostname_drift


def _label(entry: UnialiEntry) -> str:
    """Kurzbezeichnung für Meldungen — bester verfügbarer Name plus MAC."""
    name = entry["ha_name"] or entry["unifi_alias"] or entry["unifi_hostname"]
    return f"{name} ({entry['mac']})" if name else entry["mac"]


# Umlaute vor dem Strippen ausschreiben — sonst würde aus „Wärmeschublade"
# ein „wrmeschublade" statt „waermeschublade".
_HOST_ERSATZ = {
    "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
    "à": "a", "á": "a", "â": "a", "è": "e", "é": "e", "ê": "e",
    "ì": "i", "í": "i", "ò": "o", "ó": "o", "ô": "o", "ù": "u", "ú": "u",
}


def _host_slug(name: str | None) -> str | None:
    """DNS-taugliche Form eines Namens.

    Dient zwei Zwecken: als Schreibwert für den UniFi-Hostnamen und als
    Vergleichsform. Ohne die Normalisierung würde jeder Shelly als Hostname-
    Mismatch gelten (`Shelly_Mini_DG_TV` vs. `Shelly-Mini-DG-TV`).
    """
    if not name:
        return None
    s = name.strip().lower()
    for a, b in _HOST_ERSATZ.items():
        s = s.replace(a, b)
    s = re.sub(r"[\s_.]+", "-", s)
    s = re.sub(r"[^a-z0-9-]", "", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    # RFC 1035: ein Label darf höchstens 63 Zeichen haben.
    return s[:63].rstrip("-") or None


def _norm_mac(mac: str | None) -> str:
    return (mac or "").lower().replace("-", ":")


def _extract_mac(device: dr.DeviceEntry) -> str | None:
    for conn_type, value in device.connections:
        if conn_type == dr.CONNECTION_NETWORK_MAC and value:
            return _norm_mac(value)
    return None


def _iso(unix_ts: int | float | None) -> str | None:
    if not unix_ts:
        return None
    return datetime.fromtimestamp(unix_ts, tz=timezone.utc).isoformat()
