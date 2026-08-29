"""Konstanten für uniali."""

DOMAIN = "uniali"

CONF_HOST = "host"
CONF_PORT = "port"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SITE = "site"
CONF_VERIFY_SSL = "verify_ssl"

DEFAULT_PORT = 443
DEFAULT_SITE = "default"
DEFAULT_VERIFY_SSL = False

# Opt-OUT Label am HA-Device. Standardmässig erscheinen alle Geräte mit MAC die
# auch in UniFi bekannt sind. Wer ein Gerät verstecken will, labelt es mit:
LABEL_OPT_OUT = "unifi_sync_ignore"

SERVICE_REFRESH = "refresh"
SERVICE_SYNC_UNIFI = "sync_unifi"
SERVICE_SYNC_DEVICE = "sync_device"
SERVICE_FORGET_UNIFI = "forget_unifi"

ATTR_MAC = "mac"

# Frontend-Resource (Custom Card)
CARD_URL = f"/{DOMAIN}/uniali-card.js"
