# Open Questions

## Designentscheidungen aus Gründungs-Session (2026-04-25)

### ✅ Entschieden

| # | Frage | Entscheidung | Begründung |
|---|---|---|---|
| 1 | Domain-Filter? | **Opt-out via Label `unifi_sync_ignore` + Auto-Filter „nur Geräte die in UniFi auftauchen"** (revidiert 2026-04-26) | Ursprüngliche Opt-in-Variante (`unifi_sync`-Label pro Gerät anlegen) wäre bei ~80 Shellys + ESPHome + diversem extreme Klickarbeit gewesen — widerspricht „uniali soll Reibung wegnehmen"-Geist. Auto-Filter „nur in UniFi" entfernt Cloud-only-Geräte (z.B. Tado, Dyson via Cloud) aus der Liste, ohne dass User explizit ausschliessen muss. |
| 2 | HA-Name-Quelle? | **`device.name_by_user` mit Fallback auf entity friendly_name** | Manuell-gesetzte User-Namen sind die echte Wahrheit |
| 3 | Sortierung in Card? | **Mismatches oben, dann alphabetisch** | Diff-Fokus |
| 4 | Auto-Sync? | **Nein** — Per-Row-Knopf | User behält Kontrolle, vermeidet Mass-Mistakes |
| 5 | Bulk-Sync? | Out-of-Scope für MVP | Phase 2, evtl. mit Confirm-Dialog |
| 6 | Schedule? | **Nein, manueller Refresh** | Audit nur wenn User schaut |
| A | UniFi-Auth | **(a) Local-User via `aiounifi`** | Lib bereits in HA-Core (offizielle UniFi-Integration nutzt sie), Cookie/CSRF/Reauth gelöst, Write-Pfad für Client-Alias seit Jahren stabil. Local-User in UniFi anlegen (Best Practice: eigener Audit-Account). Bestätigt durch Inspektion der laufenden HA-Installation 2026-04-25. |
| B | UniFi API-Endpoints | **Detection an `aiounifi` delegieren** (UDM-Prefix `/proxy/network/...` vs. classic Controller wird automatisch erkannt). Client-Alias-Write via `controller.request("put", "/rest/user/{_id}", json={"name": ...})` — Workflow: GET clients → match per MAC → `_id` → PUT. Endpoint stabil seit ~2018. |
| 7 | Sync-Reichweite | **3-Spalten-Modell mit Adapter-System.** Spalte 1 HA-Name (SoT), Spalte 2 UniFi-Alias, Spalte 3 Geräte-Name (vendor-intern). Beide Sync-Pfeile schreiben **immer den HA-Namen**, nie den UniFi-Alias. |
| 8 | Pfeil-Sichtbarkeit | **Pfeil 1→2** wenn `ha_name` gesetzt UND `ha_name ≠ unifi_alias`. **Pfeil 2→3** nur wenn `ha_name == unifi_alias` (Cascade-Rule, verhindert temporären 3-Wege-Drift) UND Adapter vorhanden UND Geräte-IP bekannt UND `device_name ≠ ha_name`. Self-healing: wenn HA-Name später nochmal ändert, verschwindet Pfeil 2 automatisch bis Spalte 1+2 wieder einig sind. |
| 9 | Phasenplan | **MVP v1**: 3-Spalten-Card von Anfang an, aber leere Adapter-Liste → nur Pfeil 1→2 aktiv, Spalte 3 zeigt `—`. **MVP v2**: `ShellyGen2Adapter` rein → sofort ~80 Geräte mit aktivem Pfeil 2→3. **Später**: weitere Adapter (Synology, Prusa/Voron, Shelly Gen1) nach Bedarf. |
| C | UniFi self-signed Cert | **Config-Toggle im Setup** (`verify_ssl: bool`). Default offen — entscheiden wir bei Implementation, wahrscheinlich `false` (HomeLab-Realität), aber User kann strict erzwingen. |
| D | Sensor-Update-Frequenz | **Nur manuell** — `uniali.refresh` per Service-Call (Button in Card). Kein Hintergrund-Polling. Audit ist eine bewusste Aktion, kein Dauer-Job. |
| E | Card-Implementation | **Custom JS Card** (`uniali-card`). Conditional Pfeil-Logik (Cascade-Rule, Konflikt-Ausblendung) ist mit `flex-table-card` nicht sauber lösbar. Card im Component-Repo unter `custom_components/uniali/lovelace/uniali-card.js`, Integration registriert sie automatisch als Lovelace-Resource. |
| F | Konflikt-Behandlung | **Hartes Ausblenden + Warnung.** Wenn HA-Name bereits als Alias auf einer anderen MAC in UniFi existiert: Pfeil 1→2 wird nicht gezeigt, stattdessen ⚠️-Icon mit Tooltip („Alias `<name>` bereits an MAC `<andere>` vergeben — bitte zuerst dort auflösen"). User muss bewusst entscheiden (Alias auf der anderen MAC ändern, oder HA-Name anpassen). Verhindert versehentliche Duplikate. |

### 💡 Spätere Erweiterungen (nach MVP)

- Bulk-Sync mit Confirm-Dialog
- Karteileichen-Detection (UniFi-Alias ohne aktiven Client)
- Herold-Topic für Audit-Resultate
- Schedule-Modus (für die ganz Vorsichtigen)
- Bidirektional (UniFi → HA) — nur falls Bedarf entsteht
- Reverse-Audit: HA-Devices ohne MAC, könnten gemeldet werden

## Notizen aus der Diskussion

- **Gen4-Shellys senden DHCP-Hostname mit Werks-Default** — ändern in der Shelly-UI hilft nicht
- **UniFi-Aliase sind sticky** — überschreiben DHCP-Hostname auch nach DHCP-Renew
- **MAC im HA-Device-Registry**: nicht alle Integrationen exponieren das (z.B. cloud-only). Bei Match-Failure sind diese Geräte nicht in der Liste — transparent in der UI
- **Random-MAC bei iPhones**: kann zu UniFi-Karteileichen führen (alter Alias auf alter MAC). Audit-Tool würde das aufzeigen.
