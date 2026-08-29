# uniali — Projekt-Kontext für Claude

## Was ist das

Home Assistant Custom Component — synchronisiert **Friendly-Names aus HA** mit **UniFi-Client-Aliases**. Manuell, pro Zeile, mit Sync-Knopf — keine Automation.

**Status (2026-07-09):** **MVP + Phase 2 + Phase 3 + ESPHome-Read-Only + SLZB-Live-Adapter laufen live in HAOS-Produktion.** 244 Geräte im Audit, davon **96 Shellys mit Live-Adapter** (alle in 3-Spalten-Sync), **6 SLZB-Koordinatoren mit Live-Adapter** (`adapters/smlight.py` — liest/schreibt SLZB-OS-Hostname via `/ha_info` + `/settings/saveParams`; Achtung: Name = mDNS-Hostname) und **37 ESPHome-Devices read-only** in Spalte 3 (YAML-Name aus HA-Registry, kein Sync-Knopf — Re-Flash nötig). Card erkennt Read-only an `adapter_id == null && device_name != null`, zeigt ✓ bei Match, `≠` bei Mismatch + violettes `ESP`-Badge. Phase 3 brachte: IP-Join für Multi-MAC-Geräte (Shelly Pro, SLZB), Hygiene-Modus mit Forget-Service (#18 Phase 1), aiounifi-Cache-Bug-Fix, Interface-Badges (ETH/WLAN/dual), klickbare Geräte-Links, Sortier-Headers + Suchfeld. Shelly-Reliability seit 2026-08-27 live (5 s Timeout, Read-back nach Write, Retry nur im Schreibpfad); 6 HA Voice PE per ESPHome-Adopt umgetauft (`HA Voice <Raum>`, ✓ in Spalte 3). **Audit steht am 2026-08-28 auf 0 Mismatches (282 Zeilen).** Offen nur low-prio: Shelly-Truncation-Quirk (#16), Reverse-Adopt (#17), Bulk-Forget (#18 Phase 2).

## Nachbar-Projekte

- **HA-Produktivsystem:** `/Volumes/Daten/ClaudeCode/home-assistant/` — Ziel-Installation, 2026.4.x HAOS, ~5400 Entities, ~80 Shellys, 9 UniFi APs.
- **HA-Quirks:** `/Volumes/Daten/ClaudeCode/ha_quirks.md` — zentrale Wissensbasis für HA-Eigenheiten.
- **ha-herold:** `/Volumes/Daten/ClaudeCode/ha-herold/` — CC-Pattern und Saver-Familie. **Seit 2026-08-30 als Meldungs-Senke angebunden** (`herold.py`, fünf Topics, siehe unten).
- **Saver-Familie:** `device_saver`, `tariff_saver`, `matter_saver`, `water_saver` — etablierter Naming-Pattern, uniali fügt sich ein (auch wenn nicht „saver" im Namen).

## Arbeitsregeln (übernommen vom HA-Projekt)

- **Deutsch** als primäre Sprache (Code-Kommentare, Docs, UI-Labels).
- **Vor Änderungen fragen** — keine unbesprochenen Architektur-Entscheidungen.
- **Root Cause fixen** — keine Workarounds.
- **MVP first** — Audit + Per-Row-Sync. Keine Automation, kein Scheduler, kein Bulk-Sync zunächst.

## Namens-Konvention

- **Repo/Verzeichnis:** `uniali`
- **Integrations-Domain:** `uniali` (→ `custom_components/uniali/`, Service-Calls `uniali.*`)

## Veröffentlichung (2026-08-30)

**Repo:** https://github.com/cnc-lasercraft/uniali (public, MIT). Release **v1.0.0**,
Validate-Workflow (hacs/action + hassfest) grün. **HACS-Default-PR:** hacs/default#10459
— offen, 11/11 grün, `REVIEW_REQUIRED`. Playbook dazu:
`ha-theme-studio/docs/HACS_DEFAULT_SUBMISSION.md`; **§8 beachten** — bei einem
`changes_requested` parkt der hacs-bot den PR als Draft ausserhalb der Review-Queue,
regelmässig `gh pr view 10459 --repo hacs/default --json isDraft` prüfen.
Release entsteht automatisch beim manifest-Versions-Bump (`release.yml`).
Brand-Assets liegen lokal unter `custom_components/uniali/brand/` (seit HA 2026.3 der
einzige Weg — kein brands-PR).

## Herold-Anbindung (2026-08-30)

`herold.py` — optionale Kann-Abhängigkeit, bewusst NICHT in der `manifest.json`.
Fünf Topics, beim Setup registriert (verschiebt sich auf `homeassistant_started`,
falls Herold noch nicht geladen ist):

| Topic | Wann | Zustellung |
|---|---|---|
| `uniali/sync/unifi` | UniFi-Alias geschrieben | `log_only` |
| `uniali/sync/geraet` | Gerätename via Adapter geschrieben | `log_only` |
| `uniali/client/vergessen` | Forget ausgeführt | `log_only` |
| `uniali/sync/fehler` | Sync abgelehnt / Schreiben fehlgeschlagen | warnung → `techn_support` |
| `uniali/verbindung/fehler` | Controller beim Refresh tot | warnung → `techn_support` |

Erfolge sind `log_only` (Audit-Trail ohne Push — wer klickt, sieht das Resultat in der
Card). `verbindung/fehler` meldet nur die Flanke ok → Fehler, sonst würde jeder
Refresh-Klick bei totem Controller erneut feuern. **Kein Scheduler** — bewusste
Entscheidung, uniali bleibt manuell; deshalb gibt es keinen proaktiven Drift-Report.
Der Refresh-Pfad wirft jetzt `UpdateFailed` statt eines rohen Tracebacks.

## Aktueller Stand

MVP + Phase 2 + Phase 3 laufen in Produktion (HAOS auf has.sood4.ch). Code unter `custom_components/uniali/`, deployed via SSH+rsync nach `/config/custom_components/uniali/` (Card unter `lovelace/uniali-card.js`!). Dashboard `uniali-audit` (URL `/uniali-audit/audit`). Sensor **`sensor.uniali_aliases`**. Config-Entry `01KQ399TSCKYPTDT0E14F60PY3` (UniFi 10.1.11.1, default site).

**Card-Modi:** Audit (3-Spalten-Sync mit ⇨ Pfeilen) und Hygiene (Karteileichen-Cleanup mit × Forget). Toggles: nur Mismatches / UniFi-Schatten anzeigen / Suchfeld. Sortierbare Headers.

Detaillierter Session-Stand: `~/.claude/projects/-Volumes-Daten-ClaudeCode-uniali/memory/session_last.md`.

## Kontext aus Gründungs-Session

Entstanden aus konkretem Schmerz: UniFi-Aliases werden manuell gesetzt und können von der Realität abdriften. Heute Entdeckt: ein Shelly „DG_Klima" hatte in UniFi den Alias `Shelly_Mini_Quooker` — verwirrend bei Diagnose, irreführend. Bei ~80 Shellys + iPhones + Macs + Drucker viele potenzielle Drift-Punkte.

UniFi-API ist gut dokumentiert, schreibender Zugriff auf Aliases einfach. HA hat Friendly-Names + MAC im Device-Registry — Match per MAC einfach.

User-Bedürfnis ist NICHT vollautomatischer Sync, sondern Vergleichs-Übersicht mit Sync-Knopf pro Zeile — User entscheidet bewusst was synchronisiert wird.

Plus: domain-agnostisch. Shellys, ESPHome-Taster, iPhones, Drucker, alles mit MAC im HA-Registry und UniFi-Client kann gesynct werden.
