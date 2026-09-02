# uniali

[![Validate](https://github.com/cnc-lasercraft/uniali/actions/workflows/validate.yml/badge.svg)](https://github.com/cnc-lasercraft/uniali/actions/workflows/validate.yml)
[![Release](https://img.shields.io/github/v/release/cnc-lasercraft/uniali)](https://github.com/cnc-lasercraft/uniali/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Uni**Fi-Client-**Ali**ases mit Home Assistant Friendly-Names synchronisieren.

## Problem

UniFi-Aliase werden manuell gesetzt und driften von der Realität ab. Bei ~80 Shellys + weiteren Geräten passieren Tippfehler, Verwechslungen, alte Namen bleiben hängen. Bei der Diagnose führt das in die Irre (echtes Beispiel: ein Shelly „DG_Klima" hatte Alias `Shelly_Mini_Quooker`).

## Lösung

Custom Component + Lovelace-Card:
- Audit-Tabelle aller Geräte mit MAC im HA-Registry, deren MAC auch UniFi kennt — drei Spalten: HA-Friendly-Name ↔ UniFi-Alias ↔ Geräte-Name (vom Adapter direkt vom Gerät gelesen).
- Pfeil-Knöpfe pro Zeile syncen gerichtet: ⇨ HA→UniFi (immer möglich), ⇨ UniFi→Gerät (für Shellys).
- Mismatches stehen oben, ✓ wenn alle drei Namen identisch sind.
- **Kein Automatismus.** User entscheidet pro Zeile.

Opt-out per HA-Device-Label `unifi_sync_ignore` — was nicht im Audit auftauchen soll wird gelabelt und ist weg.

### Hostname- und DNS-Sync

Neben dem Alias lassen sich der **Hostname** des Clients und sein **lokaler DNS-Record** setzen — nützlich, wenn ein Gerät sich unter einem falschen oder veralteten Namen meldet und weder Werksreset noch Rename beim Hersteller hilft. Die Card blendet Spalte und Knopf erst über den Toggle „Hostnamen + DNS" ein, und der Sync ist bewusst eine **eigene Aktion**: er legt bei Bedarf eine DHCP-Reservation an und einen DNS-Namen, unter dem das Gerät im ganzen Netz auflöst — ein Klick wirkt also weit über die Card hinaus.

Warum beides: **der Hostname allein hält nicht.** UniFi lernt ihn aus DHCP-Option-12/mDNS und überschreibt jeden per API gesetzten Wert beim nächsten Lease, sobald das Gerät seinen eigenen Namen meldet (Shellys, ESPHome, UniFi-Protect-Kameras). Geräte, die *keinen* Namen melden, behalten ihn dagegen. Der persistente Gegenwert ist `local_dns_record`, und den akzeptiert UniFi nur mit DHCP-Reservation (`api.err.LocalDnsRecordRequiresFixedIp`) — deshalb schreibt uniali alles in einem Rutsch: Hostname, Reservation auf die aktuelle IP, DNS-Record. Ist der Client offline, entfällt der DNS-Teil (eine Reservation auf die letzte bekannte IP wäre geraten).

Geschrieben wird eine DNS-taugliche Form des HA-Namens (`Wärmeschublade` → `waermeschublade`); verglichen wird ebenso normalisiert, damit `Shelly_Mini_DG_TV` und `Shelly-Mini-DG-TV` nicht als Unterschied gelten. Das Domain-Suffix nimmt uniali aus den DNS-Records, die auf der Site schon existieren; über die Integrations-Optionen lässt es sich festlegen.

Holt sich ein Gerät seinen Hostnamen zurück, merkt uniali das (es kennt den zuletzt geschriebenen Wert) und markiert die Zeile als **flüchtig** — sie zählt dann nicht mehr als Mismatch, denn gegen ein Gerät, das seinen Namen selbst meldet, ist er nicht zu gewinnen. Der DNS-Record daneben bleibt.

Clients **ohne HA-Gerät** haben keinen HA-Namen als Quelle — sie sind aber oft genau die, die sich unter einem Müll-Namen melden (Kameras mit `…dynamic.cust.…`). Für sie gibt es im Hygiene-Modus den Knopf `✎ host`: freier Wert per Dialog, gleich normalisiert.

### Mismatches und Stummschalten

Als Mismatch zählt eine abweichender Alias, ein abweichender Gerätename, ein Alias-Konflikt und echte Drift in der Hostname-Spalte. Bewusst **nicht**: ein bloss fehlender DNS-Record (das ist kein Drift, sondern ein nie eingerichteter Sonderfall — sonst stünde jedes Gerät im Audit) und ein zurückgefallener Hostname.

Einzelne Zeilen lassen sich per 🔔 stummschalten: sie bleiben sichtbar, fallen aber aus Zähler und Mismatch-Filter. Gedacht für bewusst abweichende Werte, etwa einen handgepflegten DNS-Record an einem Client, der in HA anders heisst. Gespeichert wird das pro MAC — reine UniFi-Clients haben kein HA-Gerät, an dem ein Label hinge.

### Hygiene-Modus

Zweiter Card-Modus für Karteileichen-Cleanup: zeigt UniFi-only-Clients ohne HA-Bezug (Privacy-MAC-Rotationen, gelöschte Gäste), HA-Orphans (Tracker-Reste alter Integrationen), und alles >30 Tage offline. × Forget-Knopf pro Zeile mit Confirm-Dialog (warnt vor Verlust von Alias / Fixed-IP-Reservation).

## Status

**Live in Produktion** auf HAOS. 244 Geräte im Audit:

- **96 Shellys** mit Live-Adapter, alle 100% in 3-Spalten-Sync.
- **6 SLZB-Koordinatoren** (SMLIGHT SLZB-06-Familie) mit Live-Adapter — liest/schreibt den SLZB-OS-Hostname. Achtung: der Name ist zugleich der mDNS-Hostname (`<name>.local`); wer Z2M/ZHA über `.local` statt IP verbindet, kappt mit einem Rename die Verbindung.
- **37 ESPHome-Devices** read-only (YAML-Name aus HA-Registry, kein Sync — ESP-Namen sind compile-time, nur per Re-Flash änderbar). Erkennbar am violetten `ESP`-Badge.
- Rest: iPhones, Macs, Drucker, NAS etc. — Spalte 1+2 funktionieren, Spalte 3 zeigt `—` mangels Adapter.

## Features

- **3-Spalten-Audit** mit gerichteten Sync-Pfeilen
- **Hygiene-Modus** mit Bulk-tauglichem Forget
- **IP-Join** für Multi-MAC-Hardware (Shelly Pro mit getrenntem WLAN/Eth-Chip, SLZB Zigbee-Bridge etc.)
- **Interface-Badges** (ETH/WLAN/dual) auf Adapter-Reads
- **ESPHome-Read-Only** in Spalte 3 (nicht-syncbar, nur Anzeige)
- **Hostname-Sync** als eigene Aktion hinter dem Toggle „Hostnamen" — für Geräte, die einen falschen DHCP-Namen melden
- Sortier-Headers, Suchfeld, klickbare Geräte-Links (HA-Geräteseite, Web-UI)
- Manueller Refresh-Service `uniali.refresh`, kein Polling
- **Optionale Herold-Anbindung** für Meldungen (siehe unten)

## Services

| Service | Zweck |
|---|---|
| `uniali.refresh` | UniFi-Clients + HA-Devices neu einlesen |
| `uniali.sync_unifi` | HA-Friendly-Name als UniFi-Client-Alias schreiben (`mac`) |
| `uniali.sync_device` | HA-Friendly-Name via Vendor-Adapter ins Gerät schreiben (`mac`) |
| `uniali.sync_hostname` | UniFi-**Hostname** und lokalen **DNS-Record** schreiben, DNS-tauglich normalisiert, DHCP-Reservation bei Bedarf (`mac`, optional `hostname` für einen freien Wert) |
| `uniali.set_ignore` | Zeile stummschalten oder wieder mitzählen (`mac`, `ignore`) |
| `uniali.forget_unifi` | UniFi-Client komplett vergessen lassen (`mac`) |

## Meldungen via Herold (optional)

Ist [ha-herold](https://github.com/cnc-lasercraft/ha-herold) installiert, meldet uniali seine Aktionen dorthin und profitiert von Rollen-Routing und zentraler History. Fehlt Herold, entfallen die Meldungen ersatzlos — es gibt keine Abhängigkeit und keinen `notify.*`-Fallback.

Fünf Topics werden beim Setup registriert (idempotent):

| Topic | Severity | Wann |
|---|---|---|
| `uniali/sync/unifi` | info, `log_only` | UniFi-Alias geschrieben (mit Alt → Neu) |
| `uniali/sync/geraet` | info, `log_only` | Gerätename via Adapter geschrieben |
| `uniali/client/vergessen` | info, `log_only` | Client aus der UniFi-DB entfernt |
| `uniali/sync/fehler` | warnung, `log_only` | Sync abgelehnt oder Schreiben fehlgeschlagen |
| `uniali/verbindung/fehler` | warnung → `techn_support` | Controller beim Refresh nicht erreichbar |

Die vier Klick-Topics laufen als `log_only`: sie landen in der Herold-History als Audit-Trail, lösen aber keinen Push aus — wer in der Card klickt, sieht das Ergebnis ohnehin sofort, Erfolg wie Fehler. Zugestellt wird nur `uniali/verbindung/fehler`, weil der Controller-Ausfall im Refresh-Pfad die eigentliche Nachricht ist; er meldet ausschliesslich die Flanke ok → Fehler, nicht jeden Folgeversuch.

## Architektur

- `coordinator.py` — UniFi-API + HA-Device-Registry zusammenführen, Adapter-Reads parallel.
- `adapters/` — pluggable Geräte-Adapter (heute: Shelly Gen2 RPC, SMLIGHT SLZB). Eigene Adapter implementieren `matches()` + `read_state()` + `write_name()`.
- `sensor.py` — `sensor.uniali_aliases` exposed Mismatch-Count als State und volle Entries als Attribut.
- `herold.py` — optionale Meldungs-Brücke zu ha-herold.
- `lovelace/uniali-card.js` — Custom Card für Audit + Hygiene.

Details siehe `docs/ARCHITECTURE.md`.

## Voraussetzungen

- Home Assistant 2024.11 oder neuer
- UniFi Network Application (lokal, mit API-Zugriff)
- HA-Geräte mit MAC im Device-Registry

## Installation

### HACS

1. HACS → Integrationen → Drei-Punkt-Menü → **Custom repositories**
2. `https://github.com/cnc-lasercraft/uniali`, Kategorie **Integration**
3. „uniali" herunterladen, **Home Assistant neu starten**
4. Einstellungen → Geräte & Dienste → **Integration hinzufügen** → „uniali", UniFi-Host + Credentials eintragen

### Manuell

1. `custom_components/uniali/` nach `<config>/custom_components/` kopieren
2. HA neu starten
3. Einstellungen → Geräte & Dienste → Integration hinzufügen → „uniali"

### Dashboard-Setup

Die Custom Card liefert die Integration selbst aus (serviert unter `/uniali/uniali-card.js`) und trägt sich beim Start **automatisch als Lovelace-Resource** ein. Es müssen keine Dateien nach `<config>/www/` kopiert werden. Nach der Erstinstallation einmal den Browser-Cache leeren, dann die Karte einbinden:

```yaml
views:
  - title: uniali-Audit
    type: panel
    cards:
      - type: custom:uniali-card
        entity: sensor.uniali_aliases
```

Läuft Lovelace im YAML-Mode, muss die Resource manuell eingetragen werden (`url: /uniali/uniali-card.js`, `type: module`) — die Integration weist im Log darauf hin.

## Lizenz

MIT — siehe [LICENSE](LICENSE).
