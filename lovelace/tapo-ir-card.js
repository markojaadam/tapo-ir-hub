/**
 * Tapo IR Card — a custom Lovelace card for the `tapo_ir` integration.
 *
 * It auto-discovers every Tapo IR hub configured through the integration and
 * renders each child remote as its own panel, with one tappable button per
 * stored IR key. Nothing is hardcoded: devices, names, keys and icons are read
 * live from Home Assistant's entity/device registry, so the same card works for
 * any user's hub and remotes.
 *
 * Layouts:
 *   - "grid"   (default) responsive button grid, configurable columns.
 *   - "remote" arranges recognised keys (power/dpad/rockers) into a handset
 *              style, with the rest in a grid.
 *
 * Drop this file in /config/www/ and add it as a dashboard resource of type
 * "JavaScript Module". See README.md for full configuration.
 */

const CARD_VERSION = "1.0.0";

/* eslint-disable no-console */
console.info(
  `%c TAPO-IR-CARD %c v${CARD_VERSION} `,
  "color:white;background:#1f6feb;font-weight:700;border-radius:3px 0 0 3px;padding:2px 4px",
  "color:#1f6feb;background:#e8f0ff;border-radius:0 3px 3px 0;padding:2px 4px"
);

const DEFAULTS = Object.freeze({
  title: undefined,
  layout: "grid", // "grid" | "remote"
  columns: 3,
  show_hub: true, // hub header (name, diagnostics, rescan)
  show_diagnostics: true, // discovered-count + last-scan chips
  show_rescan: true, // the hub Rescan button
  collapsible: false, // each remote panel can collapse
  default_collapsed: false,
  show_empty: false, // render hubs that currently expose no remotes
  hub: undefined, // filter to one hub (by name or device id)
  include: undefined, // only these remotes (name or device id)
  exclude: undefined, // hide these remotes (name or device id)
});

/* ------------------------------------------------------------------ helpers */

function slugify(value) {
  return (value || "")
    .toString()
    .trim()
    .toLowerCase()
    .replace(/\+/g, " plus ")
    .replace(/-/g, " minus ")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function asList(value) {
  if (value === undefined || value === null) return undefined;
  return (Array.isArray(value) ? value : [value]).map((v) =>
    v.toString().toLowerCase()
  );
}

// Map a key slug to a "role" for the remote layout.
const ROLE_BY_SLUG = {
  up: "up",
  down: "down",
  left: "left",
  right: "right",
  ok: "center",
  select: "center",
  enter: "center",
  plus: "vol_up",
  volume_up: "vol_up",
  vol_plus: "vol_up",
  minus: "vol_down",
  volume_down: "vol_down",
  vol_minus: "vol_down",
  channel_up: "ch_up",
  ch_plus: "ch_up",
  channel_down: "ch_down",
  ch_minus: "ch_down",
  hi: "vol_up",
  lo: "vol_down",
};

const TOP_ROW_SLUGS = new Set([
  "power",
  "source",
  "input",
  "back",
  "settings",
  "menu",
  "home",
  "mute",
]);

/* -------------------------------------------------------------------- card */

class TapoIrCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = undefined;
    this._config = { ...DEFAULTS };
    this._sig = null; // structural signature; re-render only when it changes
    this._collapsed = new Set(); // device_ids currently collapsed
    this._collapseInit = false;
    this._built = false;
    this._error = "";
  }

  static getConfigElement() {
    return document.createElement("tapo-ir-card-editor");
  }

  static getStubConfig() {
    return { layout: "grid", columns: 3 };
  }

  setConfig(config) {
    this._config = { ...DEFAULTS, ...(config || {}) };
    this._config.columns = Math.max(1, Math.min(6, (this._config.columns | 0) || 3));
    this._include = asList(this._config.include);
    this._exclude = asList(this._config.exclude);
    this._hubFilter = asList(this._config.hub);
    this._sig = null; // force rebuild
    this._collapseInit = false;
    if (this._hass) this._update();
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  getCardSize() {
    const model = this._discover();
    let rows = 1;
    for (const hub of model) {
      rows += 1; // hub header
      for (const child of hub.children)
        rows += 1 + Math.ceil(child.keys.length / 3);
    }
    return Math.max(2, rows);
  }

  /* --------------------------------------------------------------- discovery */

  _discover() {
    const hass = this._hass;
    if (!hass || !hass.entities || !hass.devices) return [];

    const byDevice = new Map();
    for (const ent of Object.values(hass.entities)) {
      if (ent.platform !== "tapo_ir") continue;
      if (ent.hidden_by || ent.disabled_by) continue;
      const did = ent.device_id;
      if (!did) continue;
      if (!byDevice.has(did)) byDevice.set(did, []);
      byDevice.get(did).push(ent);
    }
    if (byDevice.size === 0) return [];

    const deviceName = (did) => {
      const d = hass.devices[did] || {};
      return d.name_by_user || d.name || "Tapo device";
    };
    const matches = (filter, did) =>
      !filter ||
      filter.includes((did || "").toLowerCase()) ||
      filter.includes(deviceName(did).toLowerCase());

    // Classify each device as a hub (has a sensor or rescan button) or a child.
    const hubs = new Map();
    const children = new Map();
    for (const [did, ents] of byDevice) {
      const isHub = ents.some(
        (e) =>
          e.entity_id.startsWith("sensor.") ||
          e.entity_id.endsWith("_rescan") ||
          /_rescan$/.test(e.unique_id || "")
      );
      (isHub ? hubs : children).set(did, ents);
    }
    // Hidden diagnostic entities must not hide their hub's child remotes.
    for (const childId of children.keys()) {
      const parentId = hass.devices[childId]?.via_device_id;
      if (parentId && !hubs.has(parentId) && !children.has(parentId)) {
        hubs.set(parentId, []);
      }
    }

    const buildKeys = (did, ents) => {
      const dName = deviceName(did);
      const keys = [];
      for (const ent of ents) {
        if (!ent.entity_id.startsWith("button.")) continue;
        const st = hass.states[ent.entity_id];
        let label = (st && st.attributes.friendly_name) || ent.entity_id;
        if (label.toLowerCase().startsWith(dName.toLowerCase() + " ")) {
          label = label.slice(dName.length + 1);
        }
        keys.push({
          entity_id: ent.entity_id,
          label,
          slug: slugify(label),
          icon: (st && st.attributes.icon) || "mdi:remote",
        });
      }
      keys.sort((a, b) => a.label.localeCompare(b.label));
      return { device_id: did, name: dName, keys };
    };

    // Build the hub list (optionally filtered).
    const hubList = [];
    const hubIds = [...hubs.keys()];
    for (const [hid, hents] of hubs) {
      if (!matches(this._hubFilter, hid)) continue;
      const rescan = hents.find(
        (e) =>
          e.entity_id.startsWith("button.") &&
          (/_rescan$/.test(e.unique_id || "") || /rescan/.test(e.entity_id))
      );
      const sensors = hents
        .filter((e) => e.entity_id.startsWith("sensor."))
        .map((e) => e.entity_id);
      hubList.push({
        device_id: hid,
        name: deviceName(hid),
        rescan: rescan && rescan.entity_id,
        sensors,
        children: [],
      });
    }
    if (hubList.length === 0 && hubIds.length === 0) {
      // No hub device detected but we still have child buttons — synthesize one.
      hubList.push({
        device_id: "__virtual__",
        name: "Tapo IR",
        rescan: null,
        sensors: [],
        children: [],
      });
    }

    // Attach children to their hub (via_device_id), falling back to the lone hub.
    for (const [cid, cents] of children) {
      if (!matches(this._include, cid)) continue;
      if (this._exclude && matches(this._exclude, cid)) continue;
      const built = buildKeys(cid, cents);
      if (built.keys.length === 0) continue;

      const dev = hass.devices[cid] || {};
      const target =
        hubList.find((h) => h.device_id === dev.via_device_id) ||
        (!dev.via_device_id && hubList.length === 1 && hubIds.length <= 1 ? hubList[0] : null);
      if (!target) continue;
      if (!matches(this._hubFilter, target.device_id)) continue;
      target.children.push(built);
    }

    for (const hub of hubList) {
      hub.children.sort((a, b) => a.name.localeCompare(b.name));
    }
    return this._config.show_empty
      ? hubList
      : hubList.filter((h) => h.children.length > 0 || h.sensors.length > 0);
  }

  /* ----------------------------------------------------------------- render */

  _update() {
    const model = this._discover();
    if (this._config.collapsible && this._config.default_collapsed && !this._collapseInit) {
      for (const hub of model)
        for (const child of hub.children) this._collapsed.add(child.device_id);
      this._collapseInit = true;
    }
    const sig = JSON.stringify(
      model.map((h) => [
        h.device_id,
        h.name,
        h.rescan,
        h.sensors,
        h.children.map((c) => [c.device_id, c.name, c.keys]),
      ])
    );
    if (sig !== this._sig || !this._built) {
      this._sig = sig;
      this._renderStructure(model);
      this._built = true;
    } else {
      this._refreshStates();
    }
  }

  _renderStructure(model) {
    const c = this._config;

    if (model.length === 0) {
      this.shadowRoot.innerHTML = `
        ${this._styles()}
        <ha-card>
          <div class="empty">
            <ha-icon icon="mdi:remote-off"></ha-icon>
            <div>No Tapo IR devices found.</div>
            <div class="hint">Add the <b>Tapo IR Hub</b> integration, then reload this dashboard.</div>
          </div>
        </ha-card>`;
      return;
    }

    const sections = model.map((hub) => this._renderHub(hub)).join("");
    this.shadowRoot.innerHTML = `
      ${this._styles()}
      <ha-card>
        ${c.title ? `<h1 class="card-header">${esc(c.title)}</h1>` : ""}
        <div class="action-error" role="alert">${esc(this._error)}</div>
        ${sections}
      </ha-card>`;

    // Single delegated click handler for every actionable element.
    const card = this.shadowRoot.querySelector("ha-card");
    card.addEventListener("click", (ev) => this._onClick(ev));
    this._refreshStates();
  }

  _renderHub(hub) {
    const c = this._config;
    const head =
      c.show_hub && hub.device_id !== "__virtual__"
        ? `
        <div class="hub">
          <div class="hub-title">
            <ha-icon icon="mdi:remote"></ha-icon>
            <span>${esc(hub.name)}</span>
          </div>
          <div class="hub-actions">
            ${c.show_diagnostics ? this._renderChips(hub) : ""}
            ${
              c.show_rescan && hub.rescan
                ? `<button class="rescan" data-action="press" data-entity="${esc(
                    hub.rescan
                  )}" title="Rescan devices"><ha-icon icon="mdi:magnify-scan"></ha-icon></button>`
                : ""
            }
          </div>
        </div>`
        : "";

    const children = hub.children.map((ch) => this._renderChild(ch)).join("");
    const empty =
      hub.children.length === 0
        ? `<div class="empty small">No remotes on this hub yet.</div>`
        : "";
    return `<div class="hub-block">${head}${children}${empty}</div>`;
  }

  _renderChips(hub) {
    const chips = [];
    for (const sid of hub.sensors) {
      chips.push(
        `<span class="chip" data-entity="${esc(
          sid
        )}"><ha-icon class="chip-icon" icon="mdi:information-outline"></ha-icon><span class="chip-text">—</span></span>`
      );
    }
    return `<div class="chips">${chips.join("")}</div>`;
  }

  _renderChild(child) {
    const c = this._config;
    const collapsed = c.collapsible && this._collapsed.has(child.device_id);
    const body =
      c.layout === "remote" ? this._renderRemote(child) : this._renderGrid(child);
    const toggle = c.collapsible
      ? `<ha-icon class="chevron" icon="mdi:chevron-${
          collapsed ? "down" : "up"
        }"></ha-icon>`
      : "";
    const header = `
      <div class="remote-head${c.collapsible ? " clickable" : ""}" ${
      c.collapsible ? `data-action="toggle" data-device="${esc(child.device_id)}"` : ""
    }>
        <span class="remote-name">${esc(child.name)}</span>
        <span class="remote-meta">${child.keys.length} keys</span>
        ${toggle}
      </div>`;
    return `
      <div class="remote" data-device="${esc(child.device_id)}">
        ${header}
        <div class="remote-body${collapsed ? " hidden" : ""}">${body}</div>
      </div>`;
  }

  _renderGrid(child) {
    const cols = this._config.columns;
    const btns = child.keys.map((k) => this._keyButton(k)).join("");
    return `<div class="grid" style="grid-template-columns:repeat(${cols},1fr)">${btns}</div>`;
  }

  _keyButton(k, cls = "") {
    return `
      <button class="key ${cls}" data-action="press" data-entity="${esc(
      k.entity_id
    )}" title="${esc(k.label)}">
        <ha-icon icon="${esc(k.icon)}"></ha-icon>
        <span class="key-label">${esc(k.label)}</span>
      </button>`;
  }

  // Handset-style arrangement: top utility row, D-pad cluster, rockers, rest.
  _renderRemote(child) {
    const byRole = {};
    const top = [];
    const rest = [];
    for (const k of child.keys) {
      const role = ROLE_BY_SLUG[k.slug];
      if (role && !byRole[role]) byRole[role] = k;
      else if (TOP_ROW_SLUGS.has(k.slug)) top.push(k);
      else rest.push(k);
    }

    const hasDpad =
      byRole.up || byRole.down || byRole.left || byRole.right || byRole.center;
    const hasRocker =
      byRole.vol_up || byRole.vol_down || byRole.ch_up || byRole.ch_down;
    if (!hasDpad && !hasRocker) return this._renderGrid(child); // nothing special → grid

    const slot = (role, icon) =>
      byRole[role]
        ? this._keyButton(
            { ...byRole[role], icon: byRole[role].icon || icon },
            "round"
          )
        : `<span class="slot-empty"></span>`;

    const topRow = top.length
      ? `<div class="remote-top">${top
          .map((k) => this._keyButton(k, "pill"))
          .join("")}</div>`
      : "";

    const dpad = hasDpad
      ? `
      <div class="dpad">
        <span class="slot-empty"></span>${slot("up", "mdi:chevron-up")}<span class="slot-empty"></span>
        ${slot("left", "mdi:chevron-left")}${slot(
          "center",
          "mdi:checkbox-blank-circle"
        )}${slot("right", "mdi:chevron-right")}
        <span class="slot-empty"></span>${slot(
          "down",
          "mdi:chevron-down"
        )}<span class="slot-empty"></span>
      </div>`
      : "";

    const rocker = (up, down, upIcon, downIcon, label) =>
      byRole[up] || byRole[down]
        ? `<div class="rocker"><span class="rocker-label">${label}</span>${slot(
            up,
            upIcon
          )}${slot(down, downIcon)}</div>`
        : "";

    const rockers = hasRocker
      ? `<div class="rockers">
          ${rocker("vol_up", "vol_down", "mdi:plus", "mdi:minus", "Vol")}
          ${rocker("ch_up", "ch_down", "mdi:chevron-up", "mdi:chevron-down", "Ch")}
        </div>`
      : "";

    const middle =
      dpad || rockers ? `<div class="remote-middle">${dpad}${rockers}</div>` : "";

    const cols = this._config.columns;
    const restGrid = rest.length
      ? `<div class="grid" style="grid-template-columns:repeat(${cols},1fr)">${rest
          .map((k) => this._keyButton(k))
          .join("")}</div>`
      : "";

    return `${topRow}${middle}${restGrid}`;
  }

  /* ------------------------------------------------------------ interaction */

  async _onClick(ev) {
    const path = ev.composedPath();
    const el = path.find((n) => n.dataset && n.dataset.action);
    if (!el) {
      // tapping a diagnostic chip opens its more-info dialog
      const chip = path.find(
        (n) => n.classList && n.classList.contains("chip")
      );
      if (chip && chip.dataset.entity) this._moreInfo(chip.dataset.entity);
      return;
    }
    const action = el.dataset.action;
    if (action === "press") {
      const entity = el.dataset.entity;
      if (!entity || el.disabled) return;
      try {
        await this._hass.callService("button", "press", { entity_id: entity });
        this._error = "";
        this._pulse(el);
      } catch (error) {
        this._error = error?.message || "The IR button request failed.";
      }
      const notice = this.shadowRoot.querySelector(".action-error");
      if (notice) notice.textContent = this._error;
    } else if (action === "toggle") {
      const did = el.dataset.device;
      if (this._collapsed.has(did)) this._collapsed.delete(did);
      else this._collapsed.add(did);
      const body = this.shadowRoot.querySelector(
        `.remote[data-device="${cssEsc(did)}"] .remote-body`
      );
      const chevron = el.querySelector(".chevron");
      if (body) body.classList.toggle("hidden");
      if (chevron)
        chevron.setAttribute(
          "icon",
          body && body.classList.contains("hidden")
            ? "mdi:chevron-down"
            : "mdi:chevron-up"
        );
    }
  }

  _pulse(el) {
    el.classList.remove("pressed");
    void el.offsetWidth; // restart the animation on rapid taps
    el.classList.add("pressed");
    setTimeout(() => el.classList.remove("pressed"), 280);
  }

  _moreInfo(entityId) {
    const ev = new CustomEvent("hass-more-info", {
      bubbles: true,
      composed: true,
      detail: { entityId },
    });
    this.dispatchEvent(ev);
  }

  _refreshStates() {
    const root = this.shadowRoot;
    if (!root || !this._hass) return;
    for (const btn of root.querySelectorAll("button.key, button.rescan")) {
      const st = this._hass.states[btn.dataset.entity];
      btn.toggleAttribute("disabled", !st || st.state === "unavailable");
    }
    for (const chip of root.querySelectorAll(".chip")) {
      const st = this._hass.states[chip.dataset.entity];
      const txt = chip.querySelector(".chip-text");
      const ico = chip.querySelector(".chip-icon");
      if (!st || !txt) continue;
      const attrs = st.attributes || {};
      let value = st.state;
      if (attrs.device_class === "timestamp" && value && value !== "unknown") {
        try {
          value = new Date(value).toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          });
        } catch (e) {
          /* keep raw */
        }
      }
      txt.textContent = value;
      chip.setAttribute("title", `${attrs.friendly_name || chip.dataset.entity}: ${st.state}`);
      if (ico && attrs.icon) ico.setAttribute("icon", attrs.icon);
    }
  }

  /* ------------------------------------------------------------------ style */

  _styles() {
    return `
      <style>
        :host { --tir-radius: 14px; }
        ha-card { padding: 12px; }
        .card-header { padding: 4px 4px 8px; margin: 0; font-size: 1.4em; }

        .hub-block + .hub-block { margin-top: 18px; }
        .hub {
          display: flex; align-items: center; justify-content: space-between;
          gap: 8px; padding: 4px 4px 10px; flex-wrap: wrap;
        }
        .hub-title { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 1.05em; }
        .hub-title ha-icon { color: var(--primary-color); }
        .hub-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

        .chips { display: flex; gap: 6px; flex-wrap: wrap; }
        .chip {
          display: inline-flex; align-items: center; gap: 4px; cursor: pointer;
          padding: 3px 9px; border-radius: 999px; font-size: 0.82em;
          background: var(--secondary-background-color);
          color: var(--secondary-text-color);
        }
        .chip-icon { --mdc-icon-size: 16px; }

        .rescan {
          display: inline-flex; align-items: center; justify-content: center;
          border: none; cursor: pointer; border-radius: 999px;
          width: 34px; height: 34px; color: var(--primary-color);
          background: var(--secondary-background-color);
        }
        .rescan:hover { background: var(--primary-color); color: var(--text-primary-color); }

        .remote { margin: 6px 0 12px; }
        .remote-head {
          display: flex; align-items: center; gap: 8px;
          padding: 4px 2px; color: var(--primary-text-color);
        }
        .remote-head.clickable { cursor: pointer; user-select: none; }
        .remote-name { font-weight: 600; }
        .remote-meta { color: var(--secondary-text-color); font-size: 0.8em; }
        .chevron { margin-left: auto; color: var(--secondary-text-color); }

        .remote-body { margin-top: 6px; }
        .remote-body.hidden { display: none; }

        .grid { display: grid; gap: 8px; }
        .key {
          display: flex; flex-direction: column; align-items: center; justify-content: center;
          gap: 4px; min-height: 64px; padding: 10px 6px; cursor: pointer;
          border: 1px solid var(--divider-color); border-radius: var(--tir-radius);
          background: var(--card-background-color); color: var(--primary-text-color);
          transition: transform .05s ease, background .15s ease, box-shadow .15s ease;
        }
        .key ha-icon { --mdc-icon-size: 26px; color: var(--primary-color); }
        .key-label { font-size: 0.8em; text-align: center; line-height: 1.1; }
        .key:hover { background: var(--secondary-background-color); }
        .key:active { transform: scale(.96); }
        .key[disabled] { opacity: .4; cursor: not-allowed; }
        .key.pressed, .rescan.pressed {
          background: var(--primary-color); color: var(--text-primary-color);
          box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary-color) 35%, transparent);
        }
        .key.pressed ha-icon { color: var(--text-primary-color); }

        .remote-top { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-bottom: 12px; }
        .key.pill { flex-direction: row; min-height: 42px; padding: 8px 14px; border-radius: 999px; }
        .key.pill ha-icon { --mdc-icon-size: 20px; }

        .remote-middle { display: flex; gap: 16px; align-items: center; justify-content: center; flex-wrap: wrap; margin-bottom: 12px; }
        .dpad { display: grid; grid-template-columns: repeat(3, 56px); grid-template-rows: repeat(3, 56px); gap: 6px; }
        .rockers { display: flex; gap: 14px; }
        .rocker { display: flex; flex-direction: column; align-items: center; gap: 6px; }
        .rocker-label { font-size: .75em; color: var(--secondary-text-color); }
        .key.round {
          flex-direction: column; min-height: 0; width: 56px; height: 56px; padding: 0;
          border-radius: 50%;
        }
        .key.round .key-label { display: none; }
        .key.round ha-icon { --mdc-icon-size: 24px; }
        .slot-empty { width: 56px; height: 56px; }

        .empty { text-align: center; padding: 28px 12px; color: var(--secondary-text-color); }
        .empty ha-icon { --mdc-icon-size: 40px; opacity: .6; }
        .empty .hint { font-size: .85em; margin-top: 6px; }
        .empty.small { padding: 10px; font-size: .85em; }
      </style>`;
  }
}

/* ----------------------------------------------------------- escape helpers */

function esc(value) {
  return (value === undefined || value === null ? "" : String(value)).replace(
    /[&<>"']/g,
    (ch) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      }[ch])
  );
}

function cssEsc(value) {
  if (window.CSS && CSS.escape) return CSS.escape(value);
  return String(value).replace(/["\\]/g, "\\$&");
}

/* ------------------------------------------------------------------ editor */

const EDITOR_SCHEMA = [
  { name: "title", selector: { text: {} } },
  {
    name: "layout",
    selector: {
      select: {
        mode: "dropdown",
        options: [
          { value: "grid", label: "Grid" },
          { value: "remote", label: "Remote (handset)" },
        ],
      },
    },
  },
  { name: "columns", selector: { number: { min: 1, max: 6, mode: "slider", step: 1 } } },
  { name: "hub", selector: { text: {} } },
  {
    type: "grid",
    name: "",
    schema: [
      { name: "show_hub", selector: { boolean: {} } },
      { name: "show_diagnostics", selector: { boolean: {} } },
      { name: "show_rescan", selector: { boolean: {} } },
      { name: "collapsible", selector: { boolean: {} } },
      { name: "default_collapsed", selector: { boolean: {} } },
      { name: "show_empty", selector: { boolean: {} } },
    ],
  },
];

const EDITOR_LABELS = {
  title: "Card title (optional)",
  layout: "Layout",
  columns: "Grid columns",
  hub: "Limit to hub (name or device id, optional)",
  show_hub: "Show hub header",
  show_diagnostics: "Show diagnostics",
  show_rescan: "Show rescan button",
  collapsible: "Collapsible remotes",
  default_collapsed: "Collapsed by default",
  show_empty: "Show empty hubs",
};

class TapoIrCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._rendered = false;
  }

  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._form) this._form.hass = hass;
  }

  _render() {
    if (!this._rendered) {
      this.shadowRoot.innerHTML = "";
      this._form = document.createElement("ha-form");
      this._form.schema = EDITOR_SCHEMA;
      this._form.computeLabel = (s) => EDITOR_LABELS[s.name] || s.name;
      this._form.addEventListener("value-changed", (ev) => {
        ev.stopPropagation();
        this.dispatchEvent(
          new CustomEvent("config-changed", {
            detail: { config: ev.detail.value },
            bubbles: true,
            composed: true,
          })
        );
      });
      this.shadowRoot.appendChild(this._form);
      this._rendered = true;
    }
    if (this._hass) this._form.hass = this._hass;
    this._form.data = { ...DEFAULTS, ...this._config };
  }
}

/* --------------------------------------------------------------- registration */

if (!customElements.get("tapo-ir-card")) {
  customElements.define("tapo-ir-card", TapoIrCard);
}
if (!customElements.get("tapo-ir-card-editor")) {
  customElements.define("tapo-ir-card-editor", TapoIrCardEditor);
}

window.customCards = window.customCards || [];
window.customCards.push({
  type: "tapo-ir-card",
  name: "Tapo IR Card",
  description:
    "Auto-discovers Tapo IR hubs and renders each remote's keys as tappable buttons.",
  preview: true,
  documentationURL: "https://github.com/Loadst0ne/tapo-ir-hub",
});
