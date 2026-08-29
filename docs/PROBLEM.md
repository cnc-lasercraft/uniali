# Problem

## Symptom

UniFi-Aliase und HA-Friendly-Names laufen auseinander. Bei ~80+ Shellys + diversen anderen Geräten:

- Tippfehler beim manuellen Setzen in UniFi
- Verwechslungen (z.B. heute: Shelly „DG_Klima" mit Alias `Shelly_Mini_Quooker` in UniFi)
- Alte Namen bleiben hängen wenn HA umbenannt wird
- Shelly-eigene „Device Name"-Settings wirken NICHT auf den DHCP-Hostname → UniFi sieht weiterhin den Werks-Hostname (`shellypmminig3-MAC`)
- Wenn UniFi-Alias gesetzt ist, überschreibt er den DHCP-Hostname dauerhaft — auch wenn Shelly umbenannt wird

## Konsequenzen

- Diagnose-Aufwand: Suche nach Geräten in UniFi mit falschem Alias → Zeitverlust, Fehlinterpretationen
- Falsche Aktionen möglich: Force-Provision auf falschem Gerät, etc.
- Kein einfacher Audit-Pfad

## Beispiel aus der Praxis (2026-04-25)

Bei der Diagnose eines instabilen Shellys (`Shelly_Mini_DG_Klima`) zeigte die UniFi-Client-Liste den Alias `Shelly_Mini_Quooker`. Bei ~80 Shellys ist im UniFi nicht sofort klar welche MAC welche Funktion hat — der falsche Alias führte zur Verwirrung welcher Shelly betroffen ist. Letztendlich nur per HA-MAC-Match auflösbar.

## Was schon getestet wurde

- **Shelly „Device Name" ändern**: ändert nur Display-Name + mDNS, NICHT DHCP-Hostname → UniFi unverändert
- **DHCP-Lease forcieren**: würde neuen Hostname holen, aber UniFi-Alias bleibt überschreibender Master
- **UniFi-Aliase manuell pflegen**: aktueller Zustand, fehleranfällig
- **UniFi-API-Skript**: machbar aber bisher nicht gebaut

## Ziel

Werkzeug mit dem User in 5 Min erkennt welche Geräte „aus dem Lot" sind und pro Zeile auf Knopfdruck syncen kann — domain-agnostisch (Shellys, ESPHome-Taster, iPhones, Drucker, etc.).
