# Architektur

Diese Spec wurde am 2026-04-25 vom ursprünglichen 2-Spalten-Modell auf das **3-Spalten-Modell mit Adapter-System** erweitert. Begründung und Entscheidungs-Tabelle: siehe `OPEN_QUESTIONS.md` (Einträge 7–9).

## Grundidee — 3-Spalten-Modell

Für jedes per Label `unifi_sync` opt-in markierte HA-Gerät zeigen wir **drei Namen** nebeneinander:

| Spalte | Inhalt | Quelle |
|---|---|---|
| 1 | **HA-Name** (Source of Truth) | Device-Registry: `name_by_user` mit Fallback auf `device.name` |
| 2 | **UniFi-Alias** | UniFi-Controller: `client.name` (per MAC-Match) |
| 3 | **Geräte-Name** | Vendor-API via Adapter (z.B. Shelly-RPC) — leer wenn kein Adapter passt |

Zwischen den Spalten zwei Sync-Pfeile, **beide schreiben immer den HA-Namen** (nie den UniFi-Alias an das Gerät weiter):

- **Pfeil 1→2** (`uniali.sync_unifi`): HA-Name → UniFi-Alias.
  - Sichtbar wenn: `ha_name` gesetzt UND `ha_name ≠ unifi_alias` UND **kein Konflikt** (HA-Name nicht bereits als Alias auf einer anderen MAC).
  - Bei Konflikt: Pfeil ausblenden, ⚠️-Icon mit Tooltip einblenden.
- **Pfeil 2→3** (`uniali.sync_device`): HA-Name → Geräte-interner Name.
  - Sichtbar nur wenn: `ha_name == unifi_alias` (Cascade-Rule) UND Adapter vorhanden UND Geräte-IP bekannt UND `device_name ≠ ha_name`.
  - Cascade-Rule verhindert temporären 3-Wege-Drift und erzwingt sequenzielle Sync-Schritte.

## Komponenten

### 1. Custom Component `uniali`

**Pfad:** `custom_components/uniali/`

```
custom_components/uniali/
├── __init__.py
├── manifest.json
├── config_flow.py
├── coordinator.py        # DataUpdateCoordinator: liest UniFi + HA-Devices
├── sensor.py             # sensor.uniali_aliases
├── services.yaml
├── strings.json
├── adapters/
│   ├── __init__.py       # AdapterRegistry, lädt aktive Adapter
│   ├── base.py           # DeviceAdapter Interface (ABC)
│   └── shelly_gen2.py    # MVP v2: erster Adapter
└── lovelace/
    └── uniali-card.js    # Custom Card, auto-registriert als Resource
```

**Verantwortlichkeiten:**

- **Config-Flow:** UniFi-Host + Port + Username + Password + Site-Slug + `verify_ssl`-Toggle. Optional pro Adapter-spezifische Settings (z.B. Shelly-Default-Passwort).
- **Coordinator:** auf Befehl (manueller Refresh) liest:
  1. Alle UniFi-Clients (MAC, `name`, `_id`, last-known-IP, `last_seen`)
  2. Alle HA-Devices mit Label `unifi_sync` und MAC im Device-Registry
  3. Pro gematchtem Device: jeden registrierten Adapter fragen ob er zuständig ist; wenn ja, `read_name(ip)` aufrufen
- **Match-Logik:** MAC-basiert (case-insensitive, normalisiert). Geräte ohne Match sind nicht in der Liste — Verhalten transparent in der UI dokumentiert.
- **Konflikt-Erkennung:** beim Build der Sensor-Daten wird pro Zeile geprüft ob `ha_name` bereits als Alias auf einer **anderen** MAC in UniFi existiert.

**Sensor:** `sensor.uniali_aliases`

- **State:** Anzahl Mismatches insgesamt (Spalte 1↔2 oder Spalte 2↔3, ohne Konflikte)
- **Attribut `entries`:** Liste, ein Eintrag pro Device:
  ```python
  {
    "mac": "cc:ba:97:dd:12:dc",
    "ha_name": "DG_Klima",
    "unifi_alias": "Shelly_Mini_Quooker",
    "device_name": "shelly2pmg4-ccba97dd12dc",  # None wenn kein Adapter
    "device_ip": "192.168.1.42",                # None wenn unbekannt
    "adapter_id": "shelly_gen2",                # None wenn kein Adapter
    "in_sync_unifi": False,
    "in_sync_device": False,
    "sync_unifi_possible": True,                # respektiert Konflikt-Check
    "sync_device_possible": False,              # nur True wenn Cascade-Rule erfüllt
    "conflict_unifi": None,                     # MAC der kollidierenden Gegenseite, sonst None
    "last_seen": "2026-04-25T14:32:01+00:00",
  }
  ```

**Services:**

- `uniali.refresh` — Re-Read von UniFi + HA + Adapter-Reads, Sensor-Update.
- `uniali.sync_unifi(mac)` — schreibt HA-Friendly-Name als UniFi-Alias für diese MAC. Lehnt ab wenn Konflikt vorhanden (Defense-in-Depth zur Card-Logik).
- `uniali.sync_device(mac)` — ruft den zuständigen Adapter und schreibt HA-Name an das Gerät. Lehnt ab wenn Cascade-Rule nicht erfüllt (`ha_name ≠ unifi_alias`).

### 2. Adapter-System

**Interface** (`adapters/base.py`):

```python
class DeviceAdapter(ABC):
    id: str  # z.B. "shelly_gen2"

    @abstractmethod
    def matches(self, ha_device, mac: str, ip: str | None) -> bool:
        """Erkennt ob dieses Gerät vom Adapter behandelt werden kann.
        Detection idR via HA-Device-Registry-Manufacturer + Model,
        oder als Fallback OUI-Match auf MAC-Prefix."""

    @abstractmethod
    async def read_name(self, ip: str) -> str | None:
        """Liest aktuellen Geräte-Namen. None wenn nicht erreichbar."""

    @abstractmethod
    async def write_name(self, ip: str, new_name: str) -> bool:
        """Schreibt neuen Namen. True bei Erfolg."""
```

**Registry** (`adapters/__init__.py`): hält Liste aktiver Adapter. Coordinator iteriert und nutzt den ersten Treffer pro Device.

**Erster Adapter (MVP v2):** `ShellyGen2Adapter`
- Detection: `manufacturer == "Shelly"` UND Model passt zu Gen2/3/4 (RPC-fähig)
- IP-Quelle: aus UniFi-last-known-IP (Fallback: HA-Shelly-Integration falls da)
- Read: `POST http://{ip}/rpc/Sys.GetConfig` → `device.name`
- Write: `POST http://{ip}/rpc/Sys.SetConfig` mit `{"config": {"device": {"name": new_name}}}`
- Auth: kein Default; falls Passwort gesetzt, Digest-Auth (Konfig pro-Adapter optional)

### 3. Lovelace-Card (Custom JS)

**Pfad:** `custom_components/uniali/lovelace/uniali-card.js`

- Auto-Registrierung: Component fügt beim Setup einen Lovelace-Resource-Eintrag (`/uniali/uniali-card.js`) hinzu, sodass User die Card ohne manuellen HACS-Schritt einbinden kann (`type: custom:uniali-card`).
- 3-Spalten-Layout, gerendert aus `sensor.uniali_aliases` Attribut `entries`.
- Pro Zeile: zwei Pfeil-Buttons mit Conditional-Logik wie oben, ⚠️-Icon bei Konflikt.
- Sortierung: Mismatches oben, dann alphabetisch (entschieden in OPEN_QUESTIONS Eintrag 3).
- Refresh-Button im Card-Header → ruft `uniali.refresh`.
- Optionaler Filter im Header: „nur Mismatches anzeigen".

## Datenfluss

```
            ┌──────────────┐  ┌─────────────┐  ┌─────────────────┐
            │  HA Device   │  │   UniFi     │  │  Devices        │
            │  Registry    │  │  Controller │  │  (Shelly etc.   │
            │  + name_by_  │  │  + Clients  │  │   via Adapter)  │
            │  user + MAC  │  │  + IP       │  │                 │
            └──────┬───────┘  └──────┬──────┘  └────────┬────────┘
                   │                 │                  │
                   │  on refresh     │  on refresh      │  on refresh,
                   │                 │                  │  pro matchendem
                   ▼                 ▼                  ▼  Adapter
                 ┌──────────────────────────────────────────────────┐
                 │                Coordinator                       │
                 │  - Match per MAC                                 │
                 │  - Konflikt-Check (HA-Name ↔ andere UniFi-MACs)  │
                 │  - Adapter-Lookup pro Device                     │
                 │  - Build entries-list                            │
                 └────────────────────┬─────────────────────────────┘
                                      │
              ┌───────────────────────┼───────────────────────────┐
              ▼                       ▼                           ▼
   sensor.uniali_aliases   uniali.sync_unifi(mac)      uniali.sync_device(mac)
   (state + entries)       → PUT UniFi /rest/user      → Adapter.write_name()
              │                       │                           │
              ▼                       └────────┬──────────────────┘
       custom:uniali-card  ──── tap auf Pfeil ─┘
       (3 Spalten + 2 Pfeile)
```

## Auth gegenüber UniFi

**Entschieden: (a) Local-User via `aiounifi`** (siehe OPEN_QUESTIONS Eintrag A).

- Library `aiounifi` ist im HA-Core sowieso vorhanden (offizielle UniFi-Integration nutzt sie) — kein zusätzliches Requirement.
- Config-Flow: Host, Port, Username, Password, Site-Slug, `verify_ssl`-Toggle.
- `aiounifi` erkennt UDM-Prefix (`/proxy/network/...`) vs. classic Controller automatisch — keine User-Auswahl nötig.
- Best Practice: in UniFi einen dedizierten Local-User `uniali` mit Read+Write auf Clients anlegen (eigene Audit-Spur).
- Client-Alias-Write: `controller.request("put", "/rest/user/{_id}", json={"name": ...})` — Endpoint stabil seit ~2018.
- `_id`-Resolution: GET `/rest/user` → match per MAC → `_id`. Cache pro Refresh-Zyklus.

## Filter

**Opt-out** (revidiert 2026-04-26, siehe OPEN_QUESTIONS Eintrag 1).

Standardmässig werden **alle HA-Geräte mit MAC im Device-Registry** einbezogen, die auch in UniFi bekannt sind. Zwei Filter werden automatisch angewendet:

1. **MAC muss in UniFi vorhanden sein** — sonst ist nichts actionable (kein Alias möglich, kein Adapter erreichbar). Devices die HA via Cloud-API kennt aber die nicht im UniFi-Netz auftauchen (z.B. Cloud-only Tado/Dyson) werden so automatisch ausgeblendet.
2. **`disabled_by` muss leer sein** — abgeschaltete Devices sind sowieso ausgeblendet.

**Opt-OUT-Label `unifi_sync_ignore`:** Wer einzelne Geräte verstecken will (z.B. iPhones mit Random-MAC die ständig „driften"), labelt sie mit `unifi_sync_ignore` — damit verschwinden sie aus der Liste.

Card-seitige Filter (Toggle „nur Mismatches") helfen zusätzlich, Lärm bei Bedarf zu reduzieren ohne Geräte hart auszublenden.

## Konflikt-Behandlung

**Konflikt = HA-Name existiert bereits als UniFi-Alias auf einer anderen MAC.** UniFi erlaubt Duplikate technisch, aber Drift entsteht oft genau dadurch (Copy-Paste-Fehler).

- Bei Konflikt: `sync_unifi_possible = False`, `conflict_unifi = "<andere_mac>"`.
- Card blendet Pfeil 1→2 aus, zeigt ⚠️ mit Tooltip „Alias `<name>` bereits an MAC `<andere>` vergeben".
- Service `uniali.sync_unifi` prüft selbst nochmal (Defense-in-Depth) und lehnt ab.
- User-Action: Konflikt manuell auflösen (Alias auf der anderen MAC umbenennen, oder HA-Name ändern), dann Refresh.

## Idempotenz

Re-Run sicher: wenn `ha_name == unifi_alias` und/oder `device_name == ha_name` → kein Write, nur Status. Sync-Pfeile sind in dieser Lage unsichtbar.

## Refresh-Verhalten

**Nur manuell** (entschieden in OPEN_QUESTIONS Eintrag D). Kein periodisches Polling.

- Card-Header hat einen Refresh-Button → `uniali.refresh`.
- Refresh re-liest UniFi-Clients, HA-Device-Registry, und ruft `read_name()` auf jedem matchenden Adapter.
- Adapter-Read kann fehlschlagen (Gerät offline, Auth-Fehler, etc.) → `device_name = None` für diese Zeile, Spalte 3 zeigt `—`. Kein Fehler, kein Retry, kein Hintergrund-Lärm.

## Phasenplan

| Phase | Inhalt | Wert |
|---|---|---|
| **MVP v1** | Komplette Architektur inkl. 3-Spalten-Card und leerem Adapter-System. Nur Pfeil 1→2 aktiv, Spalte 3 zeigt überall `—`. | UniFi-Sync funktioniert sofort, kein Adapter-Risiko. |
| **MVP v2** | `ShellyGen2Adapter` rein. Sofort ~80 Geräte mit aktivem Pfeil 2→3. | Grosser Hebel bei minimalem Zusatzaufwand. |
| **Phase 3+** | Weitere Adapter nach Bedarf: Synology DSM, Prusa/Voron (Klipper/PrusaLink), Shelly Gen1, ESPHome (mit Compile-Trigger? Eventuell zu komplex). | Nice-to-have, on-demand. |

## Out-of-Scope (auch in v2)

- **Bulk-Sync** aller Mismatches in einem Klick — Phase ?, evtl. mit Confirm-Dialog
- **Automatischer Schedule** (z.B. nachts) — bewusst nicht, User behält Kontrolle
- **Bidirektional** (UniFi → HA) — HA bleibt Source-of-Truth, kein Reverse-Pfad
- **Karteileichen-Detection** (UniFi-Aliase ohne aktive Clients) — Erweiterungs-Idee
- **Herold-Notification** der Audit-Resultate — Phase ?
