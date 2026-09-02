"""Konstanten für uniali."""

DOMAIN = "uniali"

CONF_HOST = "host"
CONF_PORT = "port"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SITE = "site"
CONF_VERIFY_SSL = "verify_ssl"

# Options-Flow: Suffix für lokale DNS-Records (`<name>.<domain>`). Leer =
# automatisch aus den bereits vorhandenen Records der Site ableiten.
CONF_DNS_DOMAIN = "dns_domain"

DEFAULT_PORT = 443
DEFAULT_SITE = "default"
DEFAULT_VERIFY_SSL = False

# Opt-OUT Label am HA-Device. Standardmässig erscheinen alle Geräte mit MAC die
# auch in UniFi bekannt sind. Wer ein Gerät verstecken will, labelt es mit:
LABEL_OPT_OUT = "unifi_sync_ignore"

SERVICE_REFRESH = "refresh"
SERVICE_SYNC_UNIFI = "sync_unifi"
SERVICE_SYNC_DEVICE = "sync_device"
SERVICE_SYNC_HOSTNAME = "sync_hostname"
SERVICE_FORGET_UNIFI = "forget_unifi"
SERVICE_SET_IGNORE = "set_ignore"

ATTR_MAC = "mac"
# Optional bei sync_hostname: freier Zielwert für Clients ohne HA-Gerät.
ATTR_HOSTNAME = "hostname"
ATTR_IGNORE = "ignore"

# Frontend-Resource (Custom Card)
CARD_URL = f"/{DOMAIN}/uniali-card.js"
