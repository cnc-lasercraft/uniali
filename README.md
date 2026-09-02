# uniali

[![Validate](https://github.com/cnc-lasercraft/uniali/actions/workflows/validate.yml/badge.svg)](https://github.com/cnc-lasercraft/uniali/actions/workflows/validate.yml)
[![Release](https://img.shields.io/github/v/release/cnc-lasercraft/uniali)](https://github.com/cnc-lasercraft/uniali/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Keep **Uni**Fi client **ali**ases in sync with your Home Assistant friendly names.

*[Deutsche Fassung](./README.de.md)*

## The problem

UniFi aliases are set by hand and drift away from reality. With ~80 Shellys and everything else on the network you get typos, mix-ups and names that were never updated. During diagnosis that actively misleads you — a real example from this network: a Shelly named `DG_Klima` in Home Assistant carried the UniFi alias `Shelly_Mini_Quooker`.

## The solution

A custom component plus a Lovelace card:

- An audit table of every device whose MAC is known both to the HA device registry and to UniFi — three columns: HA friendly name ↔ UniFi alias ↔ device name (read straight from the device by an adapter).
- Arrow buttons per row sync in one direction: ⇨ HA→UniFi (always available), ⇨ UniFi→device (for Shellys).
- Mismatches sort to the top; a ✓ means all three names agree.
- **Nothing is automatic.** You decide row by row.

Opt out with the HA device label `unifi_sync_ignore` — anything you don't want in the audit gets labelled and disappears.

### Hostname and DNS sync

Besides the alias you can set the client's **hostname** and its **local DNS record** — useful when a device reports itself under a wrong or outdated name and neither a factory reset nor a rename at the vendor helps. The card only reveals the column and button behind the "Hostnames + DNS" toggle, and the sync is deliberately a **separate action**: it creates a DHCP reservation where needed plus a DNS name the device then resolves under across the network — so one click reaches well beyond the card.

Why both: **the hostname alone does not stick.** UniFi learns it from DHCP option 12 / mDNS and overwrites any value written through the API at the next lease, as soon as the device announces a name of its own (Shellys, ESPHome, UniFi Protect cameras). Devices that announce *no* name keep it. The persistent counterpart is `local_dns_record`, which UniFi only accepts alongside a DHCP reservation (`api.err.LocalDnsRecordRequiresFixedIp`) — so uniali writes all of it in one go: hostname, reservation on the current IP, DNS record. If the client is offline the DNS part is skipped (a reservation on its last known IP would be guesswork).

What gets written is a DNS-safe form of the HA name (`Wärmeschublade` → `waermeschublade`); comparison is normalised the same way, so `Shelly_Mini_DG_TV` and `Shelly-Mini-DG-TV` don't count as a difference. The domain suffix is taken from the DNS records already present on the site, and can be pinned in the integration options.

When a device reclaims its hostname, uniali notices (it remembers the value it wrote) and marks the row **volatile** — it then stops counting as a mismatch, because a hostname cannot be won against a device that announces its own. The DNS record next to it stays.

Clients **without an HA device** have no HA name to use as a source — yet they are often exactly the ones reporting a garbage name (cameras showing up as `…dynamic.cust.…`). For those, hygiene mode offers the `✎ host` button: a free value via dialog, normalised on the way in.

### Mismatches and muting

A mismatch is a differing alias, a differing device name, an alias conflict, or genuine drift in the hostname column. Deliberately **not**: a merely missing DNS record (that is not drift but a feature never set up — otherwise every device would fill the audit) and a hostname that fell back.

Individual rows can be muted with 🔔: they stay visible but drop out of the counter and the mismatch filter. Meant for values that differ on purpose, such as a hand-maintained DNS record on a client named differently in HA. This is stored per MAC — pure UniFi clients have no HA device to carry a label.

### Hygiene mode

A second card mode for cleaning up stale records: it shows UniFi-only clients with no HA counterpart (privacy-MAC rotations, deleted guests), HA orphans (tracker leftovers from old integrations), and everything offline for more than 30 days. A × forget button per row with a confirmation dialog (which warns about losing the alias and any fixed-IP reservation).

## Status

**Running in production** on HAOS, with 244 devices in the audit:

- **96 Shellys** with a live adapter, all at 100% three-column sync.
- **6 SLZB coordinators** (SMLIGHT SLZB-06 family) with a live adapter that reads and writes the SLZB-OS hostname. Note: that name is also the mDNS hostname (`<name>.local`) — if you connect Z2M or ZHA over `.local` rather than by IP, a rename cuts the connection.
- **37 ESPHome devices** read-only (the YAML name comes from the HA registry; no sync, since ESP names are compile-time and only change on a reflash). Marked with a purple `ESP` badge.
- The rest — iPhones, Macs, printers, NAS and so on: columns 1 and 2 work, column 3 shows `—` for lack of an adapter.

## Features

- **Three-column audit** with directional sync arrows
- **Hygiene mode** with a forget action that scales to bulk cleanup
- **IP join** for multi-MAC hardware (Shelly Pro with separate Wi-Fi and Ethernet chips, SLZB Zigbee bridges, …)
- **Interface badges** (ETH/WLAN/dual) on adapter reads
- **ESPHome read-only** in column 3 (display only, not syncable)
- **Hostname sync** as its own action behind the "Hostnames" toggle — for devices reporting a wrong DHCP name
- Sortable headers, a search field, clickable device links (HA device page, web UI)
- Manual refresh service `uniali.refresh`; no polling
- **Optional Herold integration** for notifications (see below)

## Services

| Service | Purpose |
|---|---|
| `uniali.refresh` | Re-read UniFi clients and HA devices |
| `uniali.sync_unifi` | Write the HA friendly name as the UniFi client alias (`mac`) |
| `uniali.sync_device` | Write the HA friendly name into the device via a vendor adapter (`mac`) |
| `uniali.sync_hostname` | Write the UniFi **hostname** and a local **DNS record**, normalised to be DNS-safe, creating a DHCP reservation where needed (`mac`, plus optional `hostname` for a free value) |
| `uniali.set_ignore` | Mute a row or count it again (`mac`, `ignore`) |
| `uniali.forget_unifi` | Make UniFi forget the client entirely (`mac`) |

## Notifications via Herold (optional)

If [ha-herold](https://github.com/cnc-lasercraft/ha-herold) is installed, uniali reports its actions there and gains role-based routing and a central history. Without Herold the notifications simply don't happen — there is no dependency and no `notify.*` fallback.

Five topics are registered at setup (idempotently):

| Topic | Severity | When |
|---|---|---|
| `uniali/sync/unifi` | info, `log_only` | UniFi alias written (with old → new) |
| `uniali/sync/geraet` | info, `log_only` | Device name written via adapter |
| `uniali/client/vergessen` | info, `log_only` | Client removed from the UniFi database |
| `uniali/sync/fehler` | warning, `log_only` | Sync rejected, or the write failed |
| `uniali/verbindung/fehler` | warning → `techn_support` | Controller unreachable during refresh |

The four click-triggered topics run as `log_only`: they land in the Herold history as an audit trail but raise no push — whoever clicks in the card sees the result immediately anyway, success or failure. Only `uniali/verbindung/fehler` is delivered, because a controller outage in the refresh path is the actual news; it reports only the ok → error edge, not every subsequent retry.

## Architecture

- `coordinator.py` — merges the UniFi API with the HA device registry, adapter reads in parallel.
- `adapters/` — pluggable device adapters (today: Shelly Gen2 RPC, SMLIGHT SLZB). Your own adapter implements `matches()`, `read_state()` and `write_name()`.
- `sensor.py` — `sensor.uniali_aliases` exposes the mismatch count as its state and the full entries as an attribute.
- `herold.py` — the optional notification bridge to ha-herold.
- `lovelace/uniali-card.js` — the custom card for audit and hygiene.

See `docs/ARCHITECTURE.md` for detail.

## Requirements

- Home Assistant 2024.11 or newer
- UniFi Network Application (local, with API access)
- HA devices carrying a MAC in the device registry

## Installation

### HACS

1. HACS → Integrations → three-dot menu → **Custom repositories**
2. `https://github.com/cnc-lasercraft/uniali`, category **Integration**
3. Download "uniali", then **restart Home Assistant**
4. Settings → Devices & Services → **Add integration** → "uniali", then enter the UniFi host and credentials

### Manually

1. Copy `custom_components/uniali/` to `<config>/custom_components/`
2. Restart Home Assistant
3. Settings → Devices & Services → Add integration → "uniali"

### Dashboard setup

The integration serves the custom card itself (under `/uniali/uniali-card.js`) and registers it **automatically as a Lovelace resource** at startup. Nothing needs copying to `<config>/www/`. After the first install, clear the browser cache once, then add the card:

```yaml
views:
  - title: uniali audit
    type: panel
    cards:
      - type: custom:uniali-card
        entity: sensor.uniali_aliases
```

If Lovelace runs in YAML mode you have to add the resource by hand (`url: /uniali/uniali-card.js`, `type: module`) — the integration points this out in the log.

## License

MIT — see [LICENSE](LICENSE).
