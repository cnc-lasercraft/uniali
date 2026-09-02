// uniali-card — 3-Spalten-Audit-Card für UniFi-Alias-Sync.
// Konfiguration:
//   type: custom:uniali-card
//   entity: sensor.uniali_aliases

class UnialiCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._showOnlyMismatches = false;
    // Schatten-Devices (HA-Devices die nur durch UniFi-device_tracker existieren,
    // ohne echte Integration und ohne name_by_user) sind default versteckt —
    // das war der Grund für die meisten "irrelevanten" Zeilen in der Liste.
    this._showShadows = false;
    this._search = "";
    this._sortBy = null; // null = Default-Sortierung vom Sensor (Mismatches oben)
    this._sortDir = "asc";
    // "audit" = Standard-3-Spalten-Sync. "hygiene" = Karteileichen-Cleanup mit
    // Last-Seen, Warnungen und Forget-Knopf.
    this._mode = "audit";
    // Hostname-Spalte ist default aus: sie betrifft nur Sonderfälle (Gerät
    // meldet einen falschen/legacy DHCP-Namen) und würde die Tabelle sonst
    // für alle um zwei Spalten verbreitern.
    this._showHostname = false;
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("uniali-card: 'entity' fehlt in der Konfiguration");
    }
    this._config = config;
  }

  set hass(hass) {
    const stateObj = hass.states[this._config && this._config.entity];
    // Re-Render nur wenn unser Sensor-State wirklich neu ist; sonst zerstören
    // wir Buttons mitten im User-Klick (Lovelace ruft set hass bei JEDER
    // HA-State-Änderung, auch von fremden Entities).
    if (this._hass && this._lastState === stateObj) {
      this._hass = hass;
      return;
    }
    this._hass = hass;
    this._lastState = stateObj;
    this._render();
  }

  getCardSize() {
    return 6;
  }

  _render() {
    if (!this._hass || !this._config) return;
    const stateObj = this._hass.states[this._config.entity];
    if (!stateObj) {
      this._renderError(`Entity ${this._config.entity} nicht gefunden`);
      return;
    }

    const entries = Array.isArray(stateObj.attributes.entries)
      ? stateObj.attributes.entries
      : [];
    const mismatchCount = parseInt(stateObj.state, 10) || 0;
    const shadowCount = entries.filter((e) => e.is_shadow).length;
    const orphanCount = entries.filter((e) => e.ha_known === false).length;

    let visible;
    if (this._mode === "hygiene") {
      // Hygiene zeigt drei Klassen Karteileichen-Kandidaten:
      // - ha_known=false: reine UniFi-Clients ohne HA-Bezug
      // - ha_orphan=true: HA-Device existiert aber ohne echte Integration
      //   (z.B. Shelly-Integration entfernt, Tracker-Rest hängt am name_by_user)
      // - last_seen >30 Tage: alles was lange weg ist, egal welcher Klasse
      visible = entries.filter((e) => {
        if (e.ha_known === false) return true;
        if (e.ha_orphan === true) return true;
        if (!e.last_seen) return false;
        const days = (Date.now() - new Date(e.last_seen).getTime()) / 86400000;
        return days > 30;
      });
    } else {
      visible = this._showShadows
        ? entries.filter((e) => e.ha_known !== false)
        : entries.filter((e) => !e.is_shadow && e.ha_known !== false);
      if (this._showOnlyMismatches) {
        // e.mismatch kommt fertig aus dem Coordinator (Alias, Gerätename,
        // DNS-Record, Konflikt — minus stummgeschaltete Zeilen). Damit zeigt
        // der Filter exakt das, was der Sensor als "X offen" zählt.
        visible = visible.filter((e) => e.mismatch);
      }
    }
    if (this._search) {
      const q = this._search.toLowerCase();
      visible = visible.filter((e) =>
        [e.ha_name, e.unifi_alias, e.unifi_hostname, e.device_name, e.mac]
          .some((v) => (v || "").toLowerCase().includes(q))
      );
    }
    if (this._sortBy) {
      const key = this._sortBy;
      const dir = this._sortDir === "desc" ? -1 : 1;
      visible = [...visible].sort((a, b) => {
        const va = (a[key] || "").toString().toLowerCase();
        const vb = (b[key] || "").toString().toLowerCase();
        if (va === vb) return 0;
        return va < vb ? -dir : dir;
      });
    }

    if (!this.shadowRoot.querySelector("ha-card")) {
      this.shadowRoot.innerHTML = this._baseHtml();
      this._wireHeader();
    }
    // Mode-spezifischen thead rendern (Audit 5 bzw. 7 Spalten mit Hostname,
    // Hygiene 6) — muss vor den Zeilen laufen, die Spaltenzahl muss passen.
    this._renderThead();

    const tbody = this.shadowRoot.querySelector("tbody");
    tbody.innerHTML = "";
    const renderRow = this._mode === "hygiene"
      ? (e) => this._renderRowHygiene(e)
      : (e) => this._renderRow(e);
    for (const e of visible) {
      tbody.appendChild(renderRow(e));
    }

    this.shadowRoot.querySelector(".count").textContent =
      mismatchCount === 0 ? "alles sauber" : `${mismatchCount} offen`;
    this.shadowRoot.querySelector(".count").className =
      "count " + (mismatchCount === 0 ? "ok" : "warn");

    const shadowLabel = this.shadowRoot.querySelector(".shadow-toggle .badge");
    if (shadowLabel) {
      shadowLabel.textContent = shadowCount > 0 ? `(${shadowCount})` : "";
    }

    // Sort-Indikatoren in den Headern aktualisieren
    this.shadowRoot.querySelectorAll("th[data-sort]").forEach((th) => {
      const ind = th.querySelector(".sort-ind");
      if (!ind) return;
      if (th.dataset.sort === this._sortBy) {
        ind.textContent = this._sortDir === "desc" ? "▼" : "▲";
        th.classList.add("sorted");
      } else {
        ind.textContent = "";
        th.classList.remove("sorted");
      }
    });

    // Treffer-Count im Filter-Hint
    const hint = this.shadowRoot.querySelector(".filter-hint");
    if (hint) {
      const total = entries.length;
      hint.textContent = visible.length === total ? "" : `${visible.length}/${total}`;
    }
  }

  _baseHtml() {
    return `
      <ha-card>
        <div class="header">
          <div class="title">UniFi Alias Audit</div>
          <span class="count">…</span>
          <div class="mode-toggle" role="group">
            <button data-mode="audit" class="mode-btn active">Audit</button>
            <button data-mode="hygiene" class="mode-btn">Hygiene</button>
          </div>
          <label class="filter audit-only">
            <input type="checkbox" id="only-mm" />
            nur Mismatches
          </label>
          <label class="filter shadow-toggle audit-only" title="HA-Devices die nur durch die UniFi-Integration existieren (kein Shelly/ESPHome/etc., kein name_by_user)">
            <input type="checkbox" id="show-shadow" />
            UniFi-Schatten anzeigen <span class="badge"></span>
          </label>
          <label class="filter audit-only" title="Hostname + lokaler DNS-Record des Clients, mit eigenem Sync-Knopf. Ein Klick schreibt beides und legt bei Bedarf die nötige DHCP-Reservation an — wirkt also über die Card hinaus, deshalb getrennt vom Alias.">
            <input type="checkbox" id="show-hostname" />
            Hostnamen + DNS
          </label>
          <input type="search" class="search" placeholder="filter…" autocomplete="off" />
          <span class="filter-hint"></span>
          <button class="refresh" title="Refresh">⟳</button>
        </div>
        <div class="table-wrap">
          <table>
            <thead></thead>
            <tbody></tbody>
          </table>
        </div>
        <style>${this._css()}</style>
      </ha-card>
    `;
  }

  _renderThead() {
    const thead = this.shadowRoot.querySelector("thead");
    if (this._mode === "hygiene") {
      thead.innerHTML = `
        <tr>
          <th data-sort="ha_name" class="sortable">Identifikation <span class="sort-ind"></span></th>
          <th>MAC</th>
          <th data-sort="last_seen" class="sortable">Last Seen <span class="sort-ind"></span></th>
          <th>Verbindung</th>
          <th>Verlust beim Forget</th>
          <th></th>
        </tr>
      `;
    } else {
      thead.innerHTML = `
        <tr>
          <th data-sort="ha_name" class="sortable">HA-Name <span class="sort-ind"></span></th>
          <th></th>
          <th data-sort="unifi_alias" class="sortable">UniFi-Alias <span class="sort-ind"></span></th>
          ${this._showHostname ? '<th></th><th data-sort="unifi_hostname" class="sortable">Hostname / DNS <span class="sort-ind"></span></th>' : ""}
          <th></th>
          <th data-sort="device_name" class="sortable">Geräte-Name <span class="sort-ind"></span></th>
        </tr>
      `;
    }
    // Mode-Buttons aktiv-State
    this.shadowRoot.querySelectorAll(".mode-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.mode === this._mode);
    });
    // Audit-spezifische Filter ausblenden im Hygiene-Modus
    this.shadowRoot.querySelectorAll(".audit-only").forEach((el) => {
      el.style.display = this._mode === "hygiene" ? "none" : "";
    });
  }

  _renderRowHygiene(e) {
    const tr = document.createElement("tr");
    tr.className = "hygiene-row";

    // 1) Identifikation: HA-Name → UniFi-Alias → Hostname → MAC
    const idTd = document.createElement("td");
    idTd.className = "name";
    const display = e.ha_name || e.unifi_alias || e.unifi_hostname || "(unbekannt)";
    idTd.textContent = display;
    if (!e.ha_known) idTd.classList.add("orphan");
    tr.appendChild(idTd);

    // 2) MAC
    const macTd = document.createElement("td");
    macTd.className = "mono";
    macTd.textContent = e.mac;
    tr.appendChild(macTd);

    // 3) Last Seen
    const lsTd = document.createElement("td");
    lsTd.className = "lastseen";
    if (e.last_seen) {
      const lsDate = new Date(e.last_seen);
      const days = Math.floor((Date.now() - lsDate.getTime()) / 86400000);
      lsTd.textContent = days === 0 ? "heute" : `${days}d`;
      lsTd.title = lsDate.toLocaleString();
      if (days > 60) lsTd.classList.add("very-old");
      else if (days > 30) lsTd.classList.add("old");
    } else {
      lsTd.textContent = "—";
      lsTd.classList.add("empty");
    }
    tr.appendChild(lsTd);

    // 4) Verbindung
    const connTd = document.createElement("td");
    connTd.className = "conn";
    if (e.is_wired === true) {
      connTd.textContent = "wired";
      connTd.classList.add("wired");
    } else if (e.is_wired === false) {
      connTd.textContent = "wifi";
      connTd.classList.add("wifi");
    } else {
      connTd.textContent = "—";
    }
    tr.appendChild(connTd);

    // 5) Verlust-Warnungen
    const warnTd = document.createElement("td");
    warnTd.className = "warnings";
    const warnings = [];
    if (e.use_fixedip) warnings.push("⚠ Fixed-IP");
    if (e.unifi_alias) warnings.push("Alias");
    if (warnings.length === 0) {
      warnTd.textContent = "—";
      warnTd.classList.add("safe");
    } else {
      warnTd.textContent = warnings.join(", ");
      if (e.use_fixedip) warnTd.classList.add("warn-fixedip");
    }
    tr.appendChild(warnTd);

    // 6) Forget-Button
    const actTd = document.createElement("td");
    actTd.className = "actions";
    // Hostname frei setzen — für reine UniFi-Clients gibt es keinen HA-Namen
    // als Quelle, und gerade die melden sich unter Müll-Namen (Kameras mit
    // dynamic.cust.…, Geräte mit fremdem Legacy-Namen).
    const hostBtn = document.createElement("button");
    hostBtn.className = "host-btn";
    hostBtn.textContent = "✎ host";
    hostBtn.title = e.unifi_hostname
      ? `Hostname "${e.unifi_hostname}" überschreiben`
      : "Hostname setzen";
    hostBtn.dataset.action = "set_hostname_prompt";
    hostBtn.dataset.mac = e.mac;
    hostBtn.dataset.hostname = e.unifi_hostname || "";
    actTd.appendChild(hostBtn);

    const btn = document.createElement("button");
    btn.className = "forget-btn";
    btn.textContent = "× forget";
    btn.title = "UniFi-Client vergessen — siehe Confirm-Dialog";
    btn.dataset.action = "forget_unifi_confirm";
    btn.dataset.mac = e.mac;
    btn.dataset.alias = e.unifi_alias || "";
    btn.dataset.hostname = e.unifi_hostname || "";
    btn.dataset.fixedip = e.use_fixedip ? "1" : "";
    actTd.appendChild(btn);
    tr.appendChild(actTd);

    return tr;
  }

  _wireHeader() {
    this.shadowRoot.querySelector(".refresh").addEventListener("click", () => {
      this._hass.callService("uniali", "refresh", {});
    });
    this.shadowRoot.querySelector("#only-mm").addEventListener("change", (ev) => {
      this._showOnlyMismatches = ev.target.checked;
      this._render();
    });
    this.shadowRoot.querySelector("#show-shadow").addEventListener("change", (ev) => {
      this._showShadows = ev.target.checked;
      this._render();
    });
    this.shadowRoot.querySelector("#show-hostname").addEventListener("change", (ev) => {
      this._showHostname = ev.target.checked;
      this._render();
    });
    const search = this.shadowRoot.querySelector(".search");
    search.addEventListener("input", (ev) => {
      this._search = ev.target.value.trim();
      this._render();
    });
    // Sort: Event-Delegation auf thead, weil thead-HTML beim Mode-Wechsel
    // neu gerendert wird und einzelne th-Listener verschwinden würden.
    this.shadowRoot.querySelector("thead").addEventListener("click", (ev) => {
      const th = ev.target.closest("th[data-sort]");
      if (!th) return;
      const key = th.dataset.sort;
      if (this._sortBy !== key) {
        this._sortBy = key;
        this._sortDir = "asc";
      } else if (this._sortDir === "asc") {
        this._sortDir = "desc";
      } else {
        this._sortBy = null;
        this._sortDir = "asc";
      }
      this._render();
    });
    // Event-Delegation: ein Listener auf tbody überlebt jedes Re-Render
    // (sonst gehen Klicks während Re-Render verloren).
    this.shadowRoot.querySelector("tbody").addEventListener("click", (ev) => {
      const btn = ev.target.closest("button[data-action]");
      if (!btn) return;
      const action = btn.dataset.action;
      const mac = btn.dataset.mac;
      if (!action || !mac) return;
      if (action === "set_hostname_prompt") {
        const aktuell = btn.dataset.hostname;
        const eingabe = window.prompt(
          "Neuer UniFi-Hostname für " + mac + "\n\n" +
            "Wird DNS-tauglich normalisiert (klein, Umlaute ausgeschrieben,\n" +
            "Trenner zu \"-\"). Setzt zusätzlich einen lokalen DNS-Record\n" +
            "und legt dafür bei Bedarf eine DHCP-Reservation auf die\n" +
            "aktuelle IP an.",
          aktuell
        );
        if (eingabe && eingabe.trim() && eingabe.trim() !== aktuell) {
          this._hass.callService("uniali", "sync_hostname", {
            mac,
            hostname: eingabe.trim(),
          });
        }
        return;
      }
      if (action === "set_ignore") {
        this._hass.callService("uniali", "set_ignore", {
          mac,
          ignore: btn.dataset.ignore === "1",
        });
        return;
      }
      if (action === "forget_unifi_confirm") {
        const alias = btn.dataset.alias;
        const hostname = btn.dataset.hostname;
        const fixedip = btn.dataset.fixedip === "1";
        const lines = [
          `UniFi-Client vergessen?`,
          ``,
          `MAC: ${mac}`,
          hostname ? `Hostname: ${hostname}` : null,
          alias ? `Alias: "${alias}" → wird gelöscht` : null,
          fixedip ? `⚠ Fixed-IP-Reservation → wird aufgehoben, neue IP beim Reconnect` : null,
        ].filter(Boolean);
        if (window.confirm(lines.join("\n"))) {
          this._hass.callService("uniali", "forget_unifi", { mac });
        }
        return;
      }
      this._hass.callService("uniali", action, { mac });
    });
    // Mode-Toggle (Audit ↔ Hygiene)
    this.shadowRoot.querySelectorAll(".mode-btn").forEach((b) => {
      b.addEventListener("click", () => {
        const next = b.dataset.mode;
        if (this._mode === next) return;
        this._mode = next;
        // Sort + Search reset beim Mode-Wechsel — Spalten unterscheiden sich
        this._sortBy = null;
        this._search = "";
        const searchEl = this.shadowRoot.querySelector(".search");
        if (searchEl) searchEl.value = "";
        this._render();
      });
    });
  }

  _renderRow(e) {
    const tr = document.createElement("tr");
    if (e.ignored) {
      tr.classList.add("ignored");
      tr.title = "stummgeschaltet — zählt nicht als Mismatch";
    }
    if (e.is_shadow) {
      tr.classList.add("shadow");
      tr.title = "UniFi-Schatten — kein echtes HA-Device (nur device_tracker der UniFi-Integration)";
    }
    tr.appendChild(this._cellHa(e));
    tr.appendChild(this._arrowUnifi(e));
    tr.appendChild(this._cellUnifi(e));
    if (this._showHostname) {
      tr.appendChild(this._arrowHostname(e));
      tr.appendChild(this._cellHostname(e));
    }
    tr.appendChild(this._arrowDevice(e));
    tr.appendChild(this._cellDevice(e));
    return tr;
  }

  _cellHa(e) {
    const td = document.createElement("td");
    td.className = "name";
    if (e.ha_name && e.device_id) {
      const a = document.createElement("a");
      a.href = `/config/devices/device/${e.device_id}`;
      a.textContent = e.ha_name;
      a.title = "HA-Geräteseite öffnen";
      a.className = "device-link";
      td.appendChild(a);
    } else {
      td.textContent = e.ha_name || "—";
      if (!e.ha_name) td.classList.add("empty");
    }
    // Stummschalten: nimmt die Zeile aus Zähler und Mismatch-Filter, lässt
    // sie aber stehen. Für Abweichungen, die man kennt und bewusst so lässt.
    const mute = document.createElement("button");
    mute.className = e.ignored ? "mute-btn on" : "mute-btn";
    mute.textContent = e.ignored ? "🔕" : "🔔";
    mute.title = e.ignored
      ? "Stummgeschaltet — klicken, um wieder mitzuzählen"
      : "Zeile stummschalten (bleibt sichtbar, zählt nicht mehr als Mismatch)";
    mute.dataset.action = "set_ignore";
    mute.dataset.mac = e.mac;
    mute.dataset.ignore = e.ignored ? "" : "1";
    td.appendChild(mute);
    return td;
  }

  _cellDevice(e) {
    const td = document.createElement("td");
    td.className = "name device";
    // Read-only Quelle = device_name kommt nicht vom Live-Adapter sondern aus
    // dem HA-Registry (aktuell: ESPHome-YAML-Name). Kein Web-Link, weil ESPs
    // ohne `web_server:` keine UI haben — das gäbe nur tote Klicks.
    const readOnly = e.device_name && !e.adapter_id;
    // Geräte-Name als Link auf die Web-UI des Geräts (http://<ip>/) wenn IP
    // bekannt — analog zum „Visit"-Knopf in der HA-Shelly-Komponente.
    if (e.device_name && e.device_ip && !readOnly) {
      const a = document.createElement("a");
      a.href = `http://${e.device_ip}/`;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = e.device_name;
      a.title = `Web-UI öffnen: http://${e.device_ip}/`;
      a.className = "device-link";
      td.appendChild(a);
    } else {
      td.textContent = e.device_name || "—";
      if (!e.device_name) td.classList.add("empty");
    }
    if (readOnly) {
      const tag = document.createElement("span");
      tag.className = "iface-badge esphome";
      tag.textContent = "ESP";
      tag.title = "ESPHome-YAML-Name (read-only — nur per Re-Flash änderbar)";
      td.appendChild(tag);
    }
    if (e.interfaces) {
      const wifi = !!e.interfaces.wifi;
      const eth = !!e.interfaces.eth;
      if (wifi || eth) {
        const badge = document.createElement("span");
        badge.className = "iface-badge";
        if (wifi && eth) {
          badge.textContent = "ETH+WLAN";
          badge.classList.add("dual");
          badge.title = "Beide Interfaces aktiv — UniFi sieht das Gerät doppelt (zwei MACs)";
        } else if (eth) {
          badge.textContent = "ETH";
          badge.classList.add("eth");
          badge.title = "nur Ethernet aktiv";
        } else {
          badge.textContent = "WLAN";
          badge.classList.add("wifi");
          badge.title = "nur WLAN aktiv";
        }
        td.appendChild(badge);
      }
    }
    return td;
  }

  _cell(text, cls) {
    const td = document.createElement("td");
    td.className = cls || "";
    td.textContent = text || "—";
    if (!text) td.classList.add("empty");
    return td;
  }

  // Spalte 2: Alias bevorzugt, sonst DHCP-Hostname als Fallback markiert
  _cellUnifi(e) {
    const td = document.createElement("td");
    td.className = "name";
    if (e.unifi_alias) {
      td.textContent = e.unifi_alias;
    } else if (e.unifi_hostname) {
      td.textContent = e.unifi_hostname;
      td.classList.add("dhcp");
      td.title = "DHCP-Hostname (kein expliziter UniFi-Alias gesetzt)";
      const tag = document.createElement("span");
      tag.className = "dhcp-tag";
      tag.textContent = "DHCP";
      td.appendChild(tag);
    } else {
      td.textContent = "—";
      td.classList.add("empty");
    }
    return td;
  }

  _arrowUnifi(e) {
    const td = document.createElement("td");
    td.className = "arrow";
    if (e.conflict_unifi) {
      td.textContent = "⚠";
      td.classList.add("warn");
      td.title = `Alias "${e.ha_name}" bereits an MAC ${e.conflict_unifi} vergeben — bitte zuerst dort auflösen.`;
    } else if (e.sync_unifi_possible) {
      const willOverwrite =
        e.unifi_alias && e.unifi_alias !== e.unifi_hostname;
      const btn = document.createElement("button");
      btn.className = willOverwrite ? "sync-btn overwrite" : "sync-btn";
      btn.textContent = willOverwrite ? "⚠⇨" : "⇨";
      btn.title = willOverwrite
        ? `Achtung: bestehender UniFi-Alias "${e.unifi_alias}" wird durch "${e.ha_name}" ersetzt`
        : `HA-Name "${e.ha_name}" als UniFi-Alias setzen`;
      btn.dataset.action = "sync_unifi";
      btn.dataset.mac = e.mac;
      td.appendChild(btn);
    } else if (e.in_sync_unifi) {
      td.textContent = "✓";
      td.classList.add("ok");
      td.title = "in sync";
    } else {
      td.textContent = "·";
      td.classList.add("idle");
    }
    return td;
  }

  // Hostname-Spalte (optional): zwei Zeilen. Oben der Name, den UniFi kennt
  // (vom Gerät gemeldet oder von uns gesetzt), darunter der lokale DNS-Record
  // — der einzige der beiden Werte, der zuverlässig hält.
  _cellHostname(e) {
    const td = document.createElement("td");
    td.className = "name hostcell";

    const oben = document.createElement("div");
    oben.className = "host-line";
    if (e.unifi_hostname) {
      oben.textContent = e.unifi_hostname;
    } else {
      oben.textContent = "—";
      oben.classList.add("empty");
    }
    if (e.hostname_volatile) {
      const tag = document.createElement("span");
      tag.className = "iface-badge volatile";
      tag.textContent = "flüchtig";
      tag.title =
        "uniali hat den Hostnamen hier schon gesetzt, UniFi zeigt wieder " +
        "einen anderen: das Gerät meldet seinen Namen per DHCP selbst und " +
        "drückt ihn bei jedem Lease durch. Zählt deshalb nicht als Mismatch " +
        "— der DNS-Record darunter hält.";
      oben.appendChild(tag);
    }
    td.appendChild(oben);

    const unten = document.createElement("div");
    unten.className = "dns-line";
    if (e.unifi_dns_record) {
      unten.textContent = e.unifi_dns_record;
      unten.title = "Lokaler DNS-Record (bleibt bestehen)";
    } else if (e.dns_target) {
      unten.textContent = "kein DNS-Record";
      unten.classList.add("empty");
      unten.title = `Ein Klick würde ${e.dns_target} anlegen`;
    } else {
      unten.textContent = "";
      unten.title = "Keine DNS-Domain bekannt — in den uniali-Optionen setzen";
    }
    td.appendChild(unten);
    return td;
  }

  _arrowHostname(e) {
    const td = document.createElement("td");
    td.className = "arrow";
    if (e.sync_hostname_possible) {
      const zeilen = [
        `Hostname "${e.unifi_hostname || "—"}" → "${e.hostname_target}"`,
      ];
      // Ein von Hand gepflegter DNS-Record (alarmb.sood4.ch für einen Client,
      // der in HA anders heisst) ist kein Versehen — den darf ein Klick nicht
      // stillschweigend wegräumen. Gleiche Warnlogik wie in der Alias-Spalte.
      const dnsUeberschreibt =
        e.unifi_dns_record && e.dns_target && !e.in_sync_dns;
      if (e.dns_target && !e.in_sync_dns) {
        zeilen.push(
          dnsUeberschreibt
            ? `⚠ bestehender DNS-Record "${e.unifi_dns_record}" wird durch ${e.dns_target} ersetzt`
            : `DNS-Record → ${e.dns_target}`
        );
        if (!e.use_fixedip) {
          zeilen.push(
            e.unifi_ip
              ? `⚠ legt dafür eine DHCP-Reservation auf ${e.unifi_ip} an`
              : "⚠ Client offline — ohne IP kein DNS-Record, nur der Hostname"
          );
        }
      } else if (!e.dns_target) {
        zeilen.push("(kein DNS-Record — keine Domain in den Optionen)");
      }
      const btn = document.createElement("button");
      btn.className = "sync-btn overwrite";
      btn.textContent = dnsUeberschreibt ? "⚠⇨" : "⇨";
      btn.title = zeilen.join("\n");
      btn.dataset.action = "sync_hostname";
      btn.dataset.mac = e.mac;
      td.appendChild(btn);
    } else if (e.ha_known && (e.in_sync_dns || e.in_sync_hostname)) {
      td.textContent = "✓";
      td.classList.add("ok");
      td.title = "in sync (Vergleich ohne Gross-/Kleinschreibung und Trennzeichen)";
    } else {
      td.textContent = "·";
      td.classList.add("idle");
      td.title = e.ha_known ? "" : "Kein HA-Name als Quelle";
    }
    return td;
  }

  _arrowDevice(e) {
    const td = document.createElement("td");
    td.className = "arrow";
    if (e.sync_device_possible) {
      const btn = document.createElement("button");
      btn.className = "sync-btn";
      btn.textContent = "⇨";
      btn.title = `HA-Name "${e.ha_name}" auf Gerät schreiben (${e.adapter_id})`;
      btn.dataset.action = "sync_device";
      btn.dataset.mac = e.mac;
      td.appendChild(btn);
    } else if (e.in_sync_device) {
      td.textContent = "✓";
      td.classList.add("ok");
      td.title = e.adapter_id ? "in sync" : "in sync (ESPHome-YAML, read-only)";
    } else if (e.adapter_id === null || e.adapter_id === undefined) {
      if (e.device_name) {
        // Read-only Quelle (ESPHome-YAML) und Namen unterscheiden sich —
        // kein Sync-Knopf, weil das nur per Re-Flash auf dem ESP geht.
        td.textContent = "≠";
        td.classList.add("warn");
        td.title = "ESPHome-YAML-Name unterscheidet sich vom HA-Friendly-Name — Re-Flash auf dem ESP nötig, nicht von HA aus änderbar";
      } else {
        td.textContent = "—";
        td.classList.add("idle");
        td.title = "Kein Adapter für dieses Gerät";
      }
    } else {
      td.textContent = "·";
      td.classList.add("idle");
      td.title = e.in_sync_unifi ? "Gerät offline?" : "Erst Spalte 1 ↔ 2 syncen";
    }
    return td;
  }

  _renderError(msg) {
    this.shadowRoot.innerHTML = `<ha-card><div style="padding:16px;color:var(--error-color)">${msg}</div></ha-card>`;
  }

  _css() {
    return `
      .header {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 12px 16px 8px;
      }
      .title { font-weight: 600; flex: 1; }
      .count { font-size: 0.85em; padding: 2px 8px; border-radius: 10px; }
      .count.ok { background: var(--label-badge-green, #4caf50); color: #fff; }
      .count.warn { background: var(--label-badge-yellow, #ffa600); color: #000; }
      .filter { font-size: 0.85em; cursor: pointer; user-select: none; }
      .refresh {
        background: none; border: none; cursor: pointer;
        font-size: 1.8em; line-height: 1; padding: 4px 10px;
        border-radius: 50%; color: var(--primary-text-color);
      }
      .refresh:hover { background: var(--secondary-background-color); color: var(--primary-color); }
      .table-wrap { overflow-x: auto; padding: 0 8px 12px; }
      table { width: 100%; border-collapse: collapse; }
      th, td { padding: 4px 8px; text-align: left; }
      th { font-weight: 500; font-size: 0.8em; opacity: 0.7; border-bottom: 1px solid var(--divider-color); }
      th.sortable { cursor: pointer; user-select: none; }
      th.sortable:hover { opacity: 1; }
      th.sorted { opacity: 1; color: var(--primary-color); }
      .sort-ind { font-size: 0.7em; margin-left: 2px; }
      .search {
        background: var(--secondary-background-color); color: var(--primary-text-color);
        border: 1px solid var(--divider-color); border-radius: 4px;
        padding: 2px 8px; font-size: 0.85em; min-width: 140px;
      }
      .search:focus { outline: 1px solid var(--primary-color); }
      .filter-hint { font-size: 0.75em; opacity: 0.6; min-width: 50px; }
      tbody tr { border-bottom: 1px solid var(--divider-color); }
      tbody tr:hover { background: var(--secondary-background-color); }
      tbody tr.shadow { opacity: 0.55; font-style: italic; }
      .shadow-toggle .badge { opacity: 0.7; font-size: 0.85em; margin-left: 2px; }
      .iface-badge {
        display: inline-block; margin-left: 8px; padding: 1px 6px;
        border-radius: 6px; font-size: 0.65em; font-style: normal;
        font-family: var(--primary-font-family, sans-serif);
        vertical-align: middle; letter-spacing: 0.03em;
      }
      .iface-badge.eth  { background: rgba(76, 175, 80, 0.18); color: var(--success-color, #2e7d32); }
      .iface-badge.wifi { background: rgba(33, 150, 243, 0.18); color: var(--info-color, #1565c0); }
      .iface-badge.dual { background: rgba(255, 166, 0, 0.22); color: var(--warning-color, #c66900); font-weight: 600; }
      .iface-badge.esphome { background: rgba(156, 39, 176, 0.18); color: var(--accent-color, #7b1fa2); font-weight: 600; }
      .iface-badge.volatile { background: rgba(255, 166, 0, 0.18); color: var(--warning-color, #c66900); }
      /* Hostname-Zelle: gemeldeter Name oben, DNS-Record klein darunter. */
      .hostcell .host-line { display: flex; align-items: center; gap: 4px; }
      .hostcell .dns-line {
        font-size: 0.82em;
        opacity: 0.75;
        font-family: var(--code-font-family, monospace);
      }
      .hostcell .dns-line.empty { opacity: 0.4; font-style: italic; }
      /* Stummschalten: dezent, bis man mit der Maus draufgeht. */
      .mute-btn {
        border: none;
        background: none;
        cursor: pointer;
        font-size: 0.85em;
        opacity: 0.22;
        padding: 0 2px;
        margin-left: 4px;
        line-height: 1;
      }
      .mute-btn:hover { opacity: 1; }
      .mute-btn.on { opacity: 0.9; }
      tbody tr.ignored { opacity: 0.5; }
      tbody tr.ignored .mute-btn { opacity: 1; }
      .device-link { color: var(--primary-color); text-decoration: none; }
      .device-link:hover { text-decoration: underline; }
      /* Mode-Toggle */
      .mode-toggle { display: inline-flex; border: 1px solid var(--divider-color); border-radius: 4px; overflow: hidden; }
      .mode-btn {
        background: transparent; color: var(--primary-text-color);
        border: none; padding: 3px 10px; cursor: pointer;
        font-size: 0.85em; line-height: 1.4;
      }
      .mode-btn:hover { background: var(--secondary-background-color); }
      .mode-btn.active { background: var(--primary-color); color: var(--text-primary-color, #fff); }
      /* Hygiene-Modus */
      tr.hygiene-row td.name.orphan { font-style: italic; opacity: 0.75; }
      td.mono { font-family: var(--code-font-family, monospace); font-size: 0.85em; opacity: 0.75; }
      td.lastseen { font-variant-numeric: tabular-nums; font-size: 0.9em; }
      td.lastseen.old { color: var(--warning-color, #ffa600); }
      td.lastseen.very-old { color: var(--error-color, #db4437); font-weight: 600; }
      td.conn { font-size: 0.8em; opacity: 0.8; }
      td.conn.wired { color: var(--success-color, #2e7d32); }
      td.conn.wifi  { color: var(--info-color, #1565c0); }
      td.warnings { font-size: 0.85em; }
      td.warnings.safe { opacity: 0.4; }
      td.warnings.warn-fixedip { color: var(--warning-color, #ffa600); font-weight: 600; }
      .forget-btn {
        background: transparent; color: var(--error-color, #db4437);
        border: 1px solid var(--error-color, #db4437); border-radius: 4px;
        padding: 2px 8px; cursor: pointer; font-size: 0.85em;
      }
      .forget-btn:hover { background: var(--error-color, #db4437); color: #fff; }
      /* Hostname-Knopf bewusst neutral statt rot — er ändert etwas, löscht
         aber nichts. Der Forget daneben soll die alarmierende Farbe behalten. */
      .host-btn {
        background: transparent; color: var(--primary-text-color);
        border: 1px solid var(--divider-color); border-radius: 4px;
        padding: 2px 8px; cursor: pointer; font-size: 0.85em; margin-right: 6px;
      }
      .host-btn:hover { border-color: var(--primary-color); color: var(--primary-color); }
      td.name { font-family: var(--code-font-family, monospace); font-size: 0.9em; }
      td.name.empty { opacity: 0.4; font-style: italic; }
      td.name.device { opacity: 0.85; }
      td.name.dhcp { opacity: 0.7; font-style: italic; }
      .dhcp-tag {
        display: inline-block; margin-left: 6px; padding: 1px 6px;
        border-radius: 6px; font-size: 0.65em; font-style: normal;
        background: var(--secondary-background-color); opacity: 0.8;
        vertical-align: middle;
      }
      td.arrow { text-align: center; width: 32px; font-size: 1.1em; }
      td.arrow.ok { color: var(--success-color, #4caf50); }
      td.arrow.warn { color: var(--warning-color, #ffa600); cursor: help; }
      td.arrow.idle { opacity: 0.3; }
      .sync-btn {
        background: var(--primary-color); color: #fff; border: none;
        border-radius: 4px; padding: 2px 8px; cursor: pointer; font-size: 1em;
      }
      .sync-btn:hover { opacity: 0.85; }
      .sync-btn.overwrite {
        background: var(--warning-color, #ffa600); color: #000;
        font-weight: 600;
      }
    `;
  }
}

customElements.define("uniali-card", UnialiCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "uniali-card",
  name: "uniali — UniFi Alias Audit",
  description:
    "3-Spalten-Audit: HA-Name ↔ UniFi-Alias ↔ Geräte-Name, mit per-Row-Sync.",
});
