# Changelog

Alle nennenswerten Änderungen an uniali. Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
Versionierung nach [SemVer](https://semver.org/lang/de/).

## [1.0.0] — 2026-08-30

Erstes öffentliches Release. Der Code läuft seit Juli 2026 im Produktivsystem
des Autors (244 Geräte im Audit, 0 Mismatches).

### Neu

- **3-Spalten-Audit**: HA-Friendly-Name ↔ UniFi-Alias ↔ Geräte-Name, mit
  gerichteten Sync-Pfeilen pro Zeile. Kein Automatismus — der User entscheidet.
- **Vendor-Adapter** für den Geräte-Namen: Shelly Gen2 (RPC) und SMLIGHT SLZB
  (SLZB-OS). ESPHome-Devices erscheinen read-only (Name ist compile-time).
- **Hygiene-Modus** für Karteileichen-Cleanup mit `forget_unifi` inkl.
  Confirm-Dialog und Warnung vor Verlust von Alias / Fixed-IP-Reservation.
- **IP-Join** für Multi-MAC-Hardware (Shelly Pro, SLZB), Interface-Badges
  (ETH/WLAN/dual), Sortier-Headers, Suchfeld, klickbare Geräte-Links.
- **Opt-out** per HA-Device-Label `unifi_sync_ignore`.
- Vier Services: `refresh`, `sync_unifi`, `sync_device`, `forget_unifi`.
- Sensor `sensor.uniali_aliases` (State = Anzahl offener Mismatches,
  Attribut `entries` = vollständige Audit-Liste, vom Recorder ausgenommen).
- Custom Card wird von der Integration ausgeliefert und automatisch als
  Lovelace-Resource registriert.
- **Optionale Herold-Anbindung**: fünf Topics (`uniali/sync/unifi`,
  `uniali/sync/geraet`, `uniali/client/vergessen`, `uniali/sync/fehler`,
  `uniali/verbindung/fehler`). Erfolgs-Topics als `log_only` (Audit-Trail ohne
  Push), Fehler an die Rolle `techn_support`. Ohne Herold ein No-op.

### Behoben

- **aiounifi-Cache**: `clients_all.update()` aggregiert nur und entfernt
  gelöschte Einträge nie aus dem internen Dict — nach einem `forget-sta` blieben
  MACs bis zum HA-Restart sichtbar. Jetzt direkter `request(ApiRequest)`.
- **Shelly-Reliability**: 5 s Timeout, Read-back nach jedem Schreibvorgang,
  Retry ausschliesslich im Schreibpfad.
- Refresh-Fehler werden als `UpdateFailed` gemeldet statt als roher Traceback.
