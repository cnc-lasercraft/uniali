"""Optionale Anbindung an ha-herold (zentrale Meldungs-Vermittlung).

Herold ist eine **Kann-Abhängigkeit**: ist die Integration nicht installiert,
verhält sich uniali exakt wie vorher — die Meldungen entfallen ersatzlos, es
gibt keinen Fallback auf `notify.*`. Darum steht `herold` bewusst NICHT in der
`manifest.json` (siehe ha-herold/docs/PRODUCER_GUIDE.md, Schritt 1).

uniali ist ein manuelles Werkzeug ohne Scheduler — Meldungen entstehen nur aus
Aktionen, die der User in der Card auslöst, plus dem Verbindungsfehler beim
Refresh. Alle vier Klick-Topics laufen deshalb als `log_only` (Audit-Trail in
der Herold-History, kein Push aufs Handy — wer klickt, sieht das Ergebnis,
Erfolg wie Fehler, bereits in der Card). Nur `uniali/verbindung/fehler` pusht:
er trifft den Refresh-Pfad, wo der Controller-Ausfall die eigentliche Nachricht
ist.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant, callback

_LOGGER = logging.getLogger(__name__)

HEROLD_DOMAIN = "herold"
SERVICE_SENDEN = "senden"
SERVICE_TOPIC_REGISTRIEREN = "topic_registrieren"

QUELLE = "custom_components.uniali"

# Topic-IDs
TOPIC_SYNC_UNIFI = "uniali/sync/unifi"
TOPIC_SYNC_GERAET = "uniali/sync/geraet"
TOPIC_SYNC_FEHLER = "uniali/sync/fehler"
TOPIC_CLIENT_VERGESSEN = "uniali/client/vergessen"
TOPIC_VERBINDUNG_FEHLER = "uniali/verbindung/fehler"

TOPICS: dict[str, dict[str, Any]] = {
    TOPIC_SYNC_UNIFI: {
        "name": "uniali: UniFi-Alias gesetzt",
        "beschreibung": (
            "Der HA-Friendly-Name wurde als UniFi-Client-Alias geschrieben."
        ),
        "default_severity": "info",
        "log_only": True,
    },
    TOPIC_SYNC_GERAET: {
        "name": "uniali: Gerätename gesetzt",
        "beschreibung": (
            "Der HA-Friendly-Name wurde via Vendor-Adapter (Shelly, SLZB) in "
            "das Gerät selbst geschrieben."
        ),
        "default_severity": "info",
        "log_only": True,
    },
    TOPIC_SYNC_FEHLER: {
        "name": "uniali: Sync fehlgeschlagen",
        "beschreibung": (
            "Ein Sync-Klick konnte nicht ausgeführt werden — Gerät nicht "
            "erreichbar, UniFi-API-Fehler oder veralteter Datenstand."
        ),
        "default_severity": "warnung",
        # Kein Push: der Fehler ist die Antwort auf einen eigenen Sync-Klick,
        # der User steht vor der Card und sieht das Resultat dort sofort.
        "log_only": True,
    },
    TOPIC_CLIENT_VERGESSEN: {
        "name": "uniali: UniFi-Client vergessen",
        "beschreibung": (
            "Ein Client wurde aus der UniFi-Datenbank entfernt (Hygiene-Modus). "
            "Irreversibel — Alias, Fixed-IP, Gruppe und Stats sind weg."
        ),
        "default_severity": "info",
        "log_only": True,
    },
    TOPIC_VERBINDUNG_FEHLER: {
        "name": "uniali: UniFi-Controller nicht erreichbar",
        "beschreibung": (
            "Der Refresh konnte den UniFi-Controller nicht abfragen. Meldet "
            "nur die Flanke ok → Fehler, nicht jeden Folgeversuch."
        ),
        "default_severity": "warnung",
        "default_rollen": ["techn_support"],
    },
}


def verfuegbar(hass: HomeAssistant) -> bool:
    """True wenn Herold geladen ist und Meldungen annimmt."""
    return hass.services.has_service(HEROLD_DOMAIN, SERVICE_SENDEN)


@callback
def async_topics_registrieren(hass: HomeAssistant) -> None:
    """Meldet die uniali-Topics bei Herold an (idempotent mit Update).

    Ist Herold beim uniali-Setup noch nicht geladen (Setup-Reihenfolge ist
    zwischen zwei unabhängigen Custom Components nicht garantiert), wird die
    Registrierung einmalig auf `homeassistant_started` verschoben.
    """
    if not hass.services.has_service(HEROLD_DOMAIN, SERVICE_TOPIC_REGISTRIEREN):
        @callback
        def _spaeter(_event: Any) -> None:
            if hass.services.has_service(HEROLD_DOMAIN, SERVICE_TOPIC_REGISTRIEREN):
                _async_topics_senden(hass)

        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _spaeter)
        return

    _async_topics_senden(hass)


@callback
def _async_topics_senden(hass: HomeAssistant) -> None:
    for topic, meta in TOPICS.items():
        hass.async_create_task(
            hass.services.async_call(
                HEROLD_DOMAIN,
                SERVICE_TOPIC_REGISTRIEREN,
                {"topic": topic, "quelle": QUELLE, **meta},
                blocking=False,
            )
        )
    _LOGGER.debug("%d Topics bei Herold registriert", len(TOPICS))


async def async_senden(
    hass: HomeAssistant,
    topic: str,
    titel: str,
    message: str,
    severity: str = "info",
) -> None:
    """Sendet eine Meldung via Herold — no-op wenn Herold fehlt.

    Fehler im Meldeweg dürfen die auslösende uniali-Aktion nie kippen, deshalb
    wird alles geschluckt und nur geloggt.
    """
    if not verfuegbar(hass):
        _LOGGER.debug("Herold nicht verfügbar — %s: %s", topic, message)
        return
    try:
        await hass.services.async_call(
            HEROLD_DOMAIN,
            SERVICE_SENDEN,
            {
                "topic": topic,
                "titel": titel,
                "message": message,
                "severity": severity,
            },
            blocking=False,
        )
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Herold-Meldung %s fehlgeschlagen", topic)
