# Changelog

Alle nennenswerten Änderungen an uniali. Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
Versionierung nach [SemVer](https://semver.org/lang/de/).

## [1.0.2] — 2026-09-01

### Geändert

- **`uniali/sync/fehler` ist jetzt `log_only`** statt Push an `techn_support`.
  uniali hat keinen Scheduler, die Meldung kann also nur als Reaktion auf einen
  eigenen Sync-Klick entstehen — der User steht dabei vor der Card und sieht
  das Ergebnis dort sofort. Ein Push kam regelmässig zu spät (Belegfall: Push
  „Sync abgelehnt", 20 s später derselbe Client sauber gesynct). Damit sind
  alle vier Klick-Topics `log_only`; Push gibt es nur noch für
  `uniali/verbindung/fehler`, wo der Controller-Ausfall im Refresh-Pfad die
  eigentliche Nachricht ist. Wer den Push behalten will, setzt in Herold ein
  Topic-Override.

### Behoben

- **Fehlgeschlagener IP-Join liess den UniFi-Client ganz verschwinden.** Zeigt
  eine veraltete HA-Config-Entry auf eine IP, die DHCP inzwischen einem anderen
  Gerät gegeben hat, entsteht ein falscher IP-Join (Phase 1.5). Der Adapter-Read
  scheitert dann korrekt — bisher wurde daraufhin aber der ganze Eintrag
  verworfen, samt UniFi-Client. Der Client fehlte damit in Audit *und*
  Hygiene-Modus: unsichtbar für genau das Werkzeug, das ihn finden soll.
  Der Eintrag wird jetzt auf eine UniFi-only-Zeile zurückgestuft
  (`ha_known=False`), wie sie Phase 1.6 erzeugt hätte. Realfall: ein
  batteriebetriebener Shelly Button hielt die alte IP einer Miele-Kaffeemaschine
  fest, die dadurch aus dem Audit fiel.

## [1.0.1] — 2026-08-30

### Behoben

- **Tote UniFi-Session nach gescheitertem Re-Login.** aiounifi heilt eine
  abgelaufene Session selbst (`LoginRequired` → Re-Login → Request-Retry).
  Scheitert dieser Re-Login aber — etwa weil der Controller gerade neu startet
  und mit „Login Failed: Host starting up" antwortet — bleibt
  `can_retry_login` auf `False`, und jeder weitere Request wirft sofort
  `LoginRequired`, ohne je wieder einen Login zu versuchen. Da uniali das
  Controller-Objekt cacht, war das bis zum HA-Neustart tot. Der Cache wird
  jetzt bei `LoginRequired` / `Unauthorized` / `Forbidden` verworfen, sodass
  der nächste Aufruf frisch anmeldet — bewusst **nicht** bei Timeouts und
  Netzfehlern, weil ein zweiter Login kurz nach dem ersten vom
  UniFi-Controller mit 403 quittiert wird.

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
