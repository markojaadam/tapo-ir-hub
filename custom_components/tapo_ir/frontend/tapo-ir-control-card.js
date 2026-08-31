const CARD_VERSION = "2.0.2";
const NEW_REMOTE = "__new_remote__";
const NEW_BUTTON = "__new_button__";

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function codePreview(code) {
  if (!code) return '<div class="empty">Save or preview a code to visualize it.</div>';
  let parsed;
  try {
    parsed = JSON.parse(code);
  } catch (_error) {
    return '<div class="error">The code is not valid JSON.</div>';
  }
  if (!Number.isInteger(parsed.pwm) || typeof parsed.pulse !== "string") {
    if (typeof parsed.protocol_name === "string" && Number.isInteger(parsed.pwm)) {
      return `
        <div class="reference">
          <ha-icon icon="mdi:link-variant"></ha-icon>
          <strong>${escapeHtml(parsed.protocol_name)}</strong>
          <span>Vendor protocol reference - PWM ${escapeHtml(parsed.pwm)}</span>
        </div>
        <div class="wave-meta">This built-in code is addressable by name, but the hub does not expose its waveform. Learn or paste a waveform before saving changes.</div>
      `;
    }
    return '<div class="error">Expected {"pwm":number,"pulse":"..."}.</div>';
  }

  const numeric = parsed.pulse
    .trim()
    .split(/[\s,;]+/)
    .filter(Boolean)
    .map(Number);
  const isNumeric =
    numeric.length > 1 && numeric.every((value) => Number.isFinite(value));
  const samples = isNumeric
    ? numeric.slice(0, 500).map((value) => Math.abs(value))
    : [...parsed.pulse.slice(0, 500)].map((value) => value.charCodeAt(0));
  if (!samples.length) return '<div class="error">The pulse data is empty.</div>';

  const sorted = [...samples].sort((left, right) => left - right);
  const ceiling = Math.max(1, sorted[Math.floor(sorted.length * 0.95)] || 1);
  const width = 760;
  const height = 110;
  const step = width / Math.max(samples.length, 1);
  let path = `M 0 ${height / 2}`;
  samples.forEach((sample, index) => {
    const x = Math.min(width, (index + 1) * step);
    const amplitude = Math.min(1, sample / ceiling) * 44;
    const y = index % 2 === 0 ? height / 2 - amplitude : height / 2 + amplitude;
    path += ` L ${x.toFixed(2)} ${y.toFixed(2)}`;
  });
  const mode = isNumeric ? "numeric pulse train" : "encoded pulse bytes";
  return `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="IR waveform">
      <line x1="0" y1="${height / 2}" x2="${width}" y2="${height / 2}"></line>
      <path d="${path}"></path>
    </svg>
    <div class="wave-meta">PWM ${escapeHtml(parsed.pwm)} - ${mode} - ${samples.length} samples shown</div>
  `;
}

class TapoIrControlCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = undefined;
    this._loaded = false;
    this._loading = false;
    this._hubs = [];
    this._selectedRemote = NEW_REMOTE;
    this._selectedButton = NEW_BUTTON;
    this._selectedHub = "";
    this._newRemoteName = "";
    this._draftRows = [this._newRow()];
    this._rowEdits = new Map();
    this._previews = new Map();
    this._message = "";
    this._error = "";
    this._learningRow = null;
    this.shadowRoot.addEventListener("change", (event) => this._onChange(event));
    this.shadowRoot.addEventListener("input", (event) => this._onInput(event));
    this.shadowRoot.addEventListener("click", (event) => this._onClick(event));
  }

  static getStubConfig() {
    return { title: "Tapo IR Control Panel" };
  }

  setConfig(config) {
    this._config = { title: "Tapo IR Control Panel", ...(config || {}) };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._loaded && !this._loading) this._load();
  }

  getCardSize() {
    return 8;
  }

  _newRow() {
    return {
      id: `draft-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      label: "",
      code: "",
      trim_silence: false,
    };
  }

  async _call(message) {
    if (!this._hass) throw new Error("Home Assistant is not connected");
    return this._hass.connection.sendMessagePromise(message);
  }

  async _load() {
    this._loading = true;
    this._error = "";
    this._render();
    try {
      const result = await this._call({ type: "tapo_ir/remotes/list" });
      this._hubs = result.hubs || [];
      if (!this._selectedHub && this._hubs.length) {
        this._selectedHub = this._hubs[0].entry_id;
      }
      const remotes = this._remotes();
      if (
        this._selectedRemote !== NEW_REMOTE &&
        !remotes.some((item) => item.remote.device_id === this._selectedRemote)
      ) {
        this._selectedRemote = remotes[0]?.remote.device_id || NEW_REMOTE;
      }
      this._loaded = true;
    } catch (error) {
      this._error = this._errorText(error);
    } finally {
      this._loading = false;
      this._render();
    }
  }

  _errorText(error) {
    return (
      error?.message ||
      error?.error?.message ||
      (typeof error === "string" ? error : "The request failed")
    );
  }

  _remotes() {
    return this._hubs.flatMap((hub) =>
      (hub.remotes || []).map((remote) => ({ hub, remote }))
    );
  }

  _remote() {
    return this._remotes().find(
      (item) => item.remote.device_id === this._selectedRemote
    );
  }

  _button() {
    return (this._remote()?.remote.keys || []).find(
      (key) => key.name === this._selectedButton
    );
  }

  _learningAnchor() {
    if (this._selectedRemote !== NEW_REMOTE) {
      return { remote_device_id: this._selectedRemote };
    }
    return this._selectedHub ? { entry_id: this._selectedHub } : null;
  }

  _render() {
    if (!this.shadowRoot) return;
    const title = escapeHtml(this._config.title || "Tapo IR Control Panel");
    const status = this._error
      ? `<div class="notice error">${escapeHtml(this._error)}</div>`
      : this._message
        ? `<div class="notice success">${escapeHtml(this._message)}</div>`
        : "";
    const body = this._loading
      ? '<div class="loading">Loading Tapo IR remotes...</div>'
      : this._hubs.length
        ? this._renderEditor()
        : '<div class="empty">No loaded Tapo IR hubs were found.</div>';

    this.shadowRoot.innerHTML = `
      <ha-card>
        <div class="header">
          <div>
            <h2>${title}</h2>
            <div class="subtitle">Edit and learn codes without transmitting them</div>
          </div>
          <button class="icon" data-action="reload" title="Reload from hub" aria-label="Reload from hub">
            <ha-icon icon="mdi:database-refresh-outline"></ha-icon>
          </button>
        </div>
        ${status}
        ${body}
      </ha-card>
      ${this._styles()}
    `;
  }

  _renderEditor() {
    const options = this._remotes()
      .map(
        ({ hub, remote }) =>
          `<option value="${escapeHtml(remote.device_id)}" ${
            remote.device_id === this._selectedRemote ? "selected" : ""
          }>${escapeHtml(remote.name)} - ${escapeHtml(hub.name)}</option>`
      )
      .join("");
    return `
      <section class="picker">
        <label for="remote-select">Remote / device</label>
        <div class="inline">
          <select id="remote-select" data-field="remote" ${
            this._learningRow ? "disabled" : ""
          }>
            ${options}
            <option value="${NEW_REMOTE}" ${
              this._selectedRemote === NEW_REMOTE ? "selected" : ""
            }>+ New Remote</option>
          </select>
          ${this._learnButton("remote")}
        </div>
      </section>
      ${
        this._selectedRemote === NEW_REMOTE
          ? this._renderNewRemote()
          : this._renderExistingRemote()
      }
    `;
  }

  _renderNewRemote() {
    const hubs = this._hubs
      .map(
        (hub) =>
          `<option value="${escapeHtml(hub.entry_id)}" ${
            hub.entry_id === this._selectedHub ? "selected" : ""
          }>${escapeHtml(hub.name)}</option>`
      )
      .join("");
    return `
      <section class="remote-editor">
        <div class="field-grid">
          <label>Target hub
            <select data-field="hub" ${this._learningRow ? "disabled" : ""}>${hubs}</select>
          </label>
          <label>New remote name
            <input data-field="new-remote-name" maxlength="64" value="${escapeHtml(
              this._newRemoteName
            )}" placeholder="Living Room TV">
          </label>
        </div>
        <div class="hint">The remote is created only when its first valid button is saved.</div>
        ${this._draftRows.map((row) => this._renderRow(row, true)).join("")}
      </section>
    `;
  }

  _renderExistingRemote() {
    const selected = this._remote();
    if (!selected) return '<div class="empty">Select a remote.</div>';
    const remote = selected.remote;
    const buttons = (remote.keys || [])
      .map(
        (key) =>
          `<option value="${escapeHtml(key.name)}" ${
            key.name === this._selectedButton ? "selected" : ""
          }>${escapeHtml(key.label)}</option>`
      )
      .join("");
    const chosen = this._button();
    const savedRowId = chosen ? `saved-${chosen.name}` : "";
    const edited = this._rowEdits.get(savedRowId) || {};
    const rows =
      this._selectedButton === NEW_BUTTON
        ? this._draftRows.map((row) => this._renderRow(row, false)).join("")
        : chosen
          ? this._renderRow(
              {
                id: savedRowId,
                label: edited.label ?? chosen.label,
                code: edited.code ?? chosen.code,
                code_format: chosen.code_format,
                key_reference: chosen.name,
                trim_silence: edited.trim_silence ?? false,
              },
              false
            )
          : "";
    return `
      <section class="remote-editor">
        <label>Remote name</label>
        <div class="inline">
          <input data-field="remote-name" maxlength="64" value="${escapeHtml(remote.name)}">
          <button class="icon" data-action="rename" title="Save remote name" aria-label="Save remote name">
            <ha-icon icon="mdi:content-save"></ha-icon>
          </button>
          ${this._learnButton("remote")}
        </div>
        <label for="button-select">Button / entity</label>
        <div class="inline">
          <select id="button-select" data-field="button" ${
            this._learningRow ? "disabled" : ""
          }>
            ${buttons}
            <option value="${NEW_BUTTON}" ${
              this._selectedButton === NEW_BUTTON ? "selected" : ""
            }>+ New Button</option>
          </select>
          ${this._learnButton("button")}
        </div>
        ${rows}
      </section>
    `;
  }

  _renderRow(row, creatingRemote) {
    const preview = this._previews.get(row.id);
    const visualCode = preview ?? (row.key_reference ? row.code : "");
    const learning = this._learningRow === row.id;
    return `
      <article class="code-row" data-row="${escapeHtml(row.id)}" data-key="${escapeHtml(
        row.key_reference || ""
      )}">
        <div class="row-title">${creatingRemote ? "Initial button" : row.key_reference ? "Saved button" : "New button"}</div>
        ${
          row.code_format === "protocol_reference"
            ? '<div class="hint">The hub exposes this built-in key by protocol name only. It remains fully usable, but needs a learned or pasted waveform before its code can be replaced.</div>'
            : ""
        }
        <label>Button name
          <input data-row-field="label" maxlength="64" value="${escapeHtml(
            row.label
          )}" placeholder="Power">
        </label>
        <label>IR code
          <textarea data-row-field="code" spellcheck="false" placeholder='{"pwm":26,"pulse":"..."}'>${escapeHtml(
            row.code
          )}</textarea>
        </label>
        <div class="row-actions">
          <button class="icon primary" data-action="save-row" title="Save code" aria-label="Save code">
            <ha-icon icon="mdi:content-save"></ha-icon>
          </button>
          <button class="icon" data-action="add-row" title="Add another button" aria-label="Add another button">
            <ha-icon icon="mdi:plus"></ha-icon>
          </button>
          <button class="icon" data-action="preview-row" title="Refresh visualization" aria-label="Refresh visualization">
            <ha-icon icon="mdi:refresh"></ha-icon>
          </button>
          ${this._learnButton(row.id)}
          ${
            learning
              ? `<button class="icon stop" data-action="stop-learn" title="Stop learning" aria-label="Stop learning">
                  <ha-icon icon="mdi:stop-circle-outline"></ha-icon>
                </button>`
              : ""
          }
          <label class="trim">
            <input type="checkbox" data-row-field="trim_silence" ${
              row.trim_silence ? "checked" : ""
            }>
            Trim explicit zero padding
          </label>
        </div>
        <div class="wave">${codePreview(visualCode)}</div>
      </article>
    `;
  }

  _learnButton(target) {
    const disabled = this._learningAnchor() ? "" : "disabled";
    return `
      <button class="icon learn" data-action="learn" data-target="${escapeHtml(
        target
      )}" title="Learn IR code" aria-label="Learn IR code" ${disabled}>
        <ha-icon icon="mdi:brain"></ha-icon>
      </button>
    `;
  }

  _rowElement(target) {
    return target.closest(".code-row");
  }

  _rowState(element) {
    return {
      id: element.dataset.row,
      key_reference: element.dataset.key || undefined,
      label: element.querySelector('[data-row-field="label"]').value,
      code: element.querySelector('[data-row-field="code"]').value,
      trim_silence: element.querySelector('[data-row-field="trim_silence"]').checked,
    };
  }

  _updateDraft(row) {
    const index = this._draftRows.findIndex((item) => item.id === row.id);
    if (index >= 0) this._draftRows[index] = { ...this._draftRows[index], ...row };
  }

  _rememberRow(row) {
    if (row.id.startsWith("draft-")) this._updateDraft(row);
    else this._rowEdits.set(row.id, row);
  }

  _onChange(event) {
    const field = event.target.dataset.field;
    if (field === "remote") {
      this._selectedRemote = event.target.value;
      this._selectedButton = NEW_BUTTON;
      this._draftRows = [this._newRow()];
      this._rowEdits.clear();
      this._previews.clear();
      this._render();
    } else if (field === "button") {
      this._selectedButton = event.target.value;
      this._draftRows = [this._newRow()];
      this._rowEdits.clear();
      this._previews.clear();
      this._render();
    } else if (field === "hub") {
      this._selectedHub = event.target.value;
    }
  }

  _onInput(event) {
    const field = event.target.dataset.field;
    if (field === "new-remote-name") this._newRemoteName = event.target.value;
    const rowElement = this._rowElement(event.target);
    if (rowElement) this._rememberRow(this._rowState(rowElement));
  }

  async _onClick(event) {
    const button = event.composedPath().find((item) => item?.dataset?.action);
    if (!button) return;
    const action = button.dataset.action;
    this._error = "";
    this._message = "";
    if (action === "reload") {
      await this._load();
      return;
    }
    if (action === "add-row") {
      const rowElement = this._rowElement(button);
      if (rowElement?.dataset.row.startsWith("draft-")) {
        this._updateDraft(this._rowState(rowElement));
      }
      this._draftRows.push(this._newRow());
      this._selectedButton = NEW_BUTTON;
      this._render();
      return;
    }
    if (action === "preview-row") {
      const row = this._rowState(this._rowElement(button));
      this._rememberRow(row);
      this._previews.set(row.id, row.code);
      this._render();
      return;
    }
    if (action === "save-row") {
      await this._saveRow(this._rowState(this._rowElement(button)));
      return;
    }
    if (action === "rename") {
      await this._renameRemote();
      return;
    }
    if (action === "learn") {
      await this._learn(button.dataset.target);
      return;
    }
    if (action === "stop-learn") {
      await this._stopLearning();
    }
  }

  async _saveRow(row) {
    try {
      let result;
      if (this._selectedRemote === NEW_REMOTE) {
        if (!this._newRemoteName.trim()) throw new Error("Enter a remote name");
        result = await this._call({
          type: "tapo_ir/remote/create",
          entry_id: this._selectedHub,
          name: this._newRemoteName,
          keys: [
            {
              label: row.label,
              code: row.code,
              trim_silence: row.trim_silence,
            },
          ],
        });
        this._selectedRemote = result.remote_device_id;
        this._selectedButton = NEW_BUTTON;
        this._newRemoteName = "";
      } else {
        result = await this._call({
          type: "tapo_ir/key/save",
          remote_device_id: this._selectedRemote,
          key_reference: row.key_reference,
          label: row.label,
          code: row.code,
          trim_silence: row.trim_silence,
        });
        this._selectedButton = result.key_name;
        this._rowEdits.delete(row.id);
        this._previews.set(`saved-${result.key_name}`, result.code);
      }
      this._message = "Saved and verified against the hub.";
      this._draftRows = [this._newRow()];
      await this._load();
    } catch (error) {
      this._error = this._errorText(error);
      this._render();
    }
  }

  async _renameRemote() {
    const input = this.shadowRoot.querySelector('[data-field="remote-name"]');
    try {
      await this._call({
        type: "tapo_ir/remote/rename",
        remote_device_id: this._selectedRemote,
        name: input.value,
      });
      this._message = "Remote name saved and verified.";
      await this._load();
    } catch (error) {
      this._error = this._errorText(error);
      this._render();
    }
  }

  _targetRow(target) {
    if (target && !["remote", "button"].includes(target)) {
      return this.shadowRoot.querySelector(`[data-row="${CSS.escape(target)}"]`);
    }
    let row = this.shadowRoot.querySelector(".code-row");
    if (!row && this._selectedButton !== NEW_BUTTON) {
      this._selectedButton = NEW_BUTTON;
      this._draftRows = [this._newRow()];
      this._render();
      row = this.shadowRoot.querySelector(".code-row");
    }
    return row;
  }

  async _learn(target) {
    const anchor = this._learningAnchor();
    const rowElement = this._targetRow(target);
    if (!anchor || !rowElement) {
      this._error = "Add or select a button row before learning.";
      this._render();
      return;
    }
    const row = this._rowState(rowElement);
    this._updateDraft(row);
    this._learningRow = row.id;
    this._message = "Learning for up to 30 seconds. Press the physical remote now.";
    this._render();
    try {
      const result = await this._call({
        type: "tapo_ir/learn",
        ...anchor,
        timeout: 30,
      });
      const current = row.id.startsWith("draft-")
        ? this._draftRows.find((item) => item.id === row.id) || row
        : this._rowEdits.get(row.id) || row;
      this._rememberRow({ ...current, code: result.code });
      this._previews.set(row.id, result.code);
      this._message = "Signal captured. Review the waveform, then save it.";
    } catch (error) {
      this._error = this._errorText(error);
    } finally {
      this._learningRow = null;
      this._render();
    }
  }

  async _stopLearning() {
    try {
      await this._call({ type: "tapo_ir/learn/stop" });
      this._message = "Learning stopped.";
    } catch (error) {
      this._error = this._errorText(error);
    }
    this._learningRow = null;
    this._render();
  }

  _styles() {
    return `
      <style>
        :host { display: block; }
        ha-card { padding: 16px; }
        h2 { margin: 0; font-size: 1.35rem; }
        .header, .inline, .row-actions { display: flex; align-items: center; gap: 8px; }
        .header { justify-content: space-between; margin-bottom: 14px; }
        .subtitle, .hint, .wave-meta { color: var(--secondary-text-color); font-size: .86rem; }
        .picker, .remote-editor { display: grid; gap: 10px; }
        .remote-editor { margin-top: 14px; }
        label { display: grid; gap: 5px; font-weight: 600; }
        select, input, textarea {
          box-sizing: border-box;
          width: 100%;
          color: var(--primary-text-color);
          background: var(--card-background-color);
          border: 1px solid var(--divider-color);
          border-radius: 6px;
          padding: 10px;
          font: inherit;
        }
        textarea { min-height: 94px; resize: vertical; font-family: var(--code-font-family, monospace); }
        .inline > select, .inline > input { flex: 1; }
        .field-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; }
        .code-row { border: 1px solid var(--divider-color); border-radius: 8px; padding: 12px; display: grid; gap: 10px; }
        .row-title { font-weight: 700; }
        button.icon {
          width: 40px; height: 40px; flex: 0 0 40px; border: 1px solid var(--divider-color);
          border-radius: 6px; color: var(--primary-text-color); background: var(--secondary-background-color);
          cursor: pointer;
        }
        button.icon:hover { background: var(--divider-color); }
        button.icon:disabled { opacity: .4; cursor: not-allowed; }
        button.primary { color: var(--primary-color); }
        button.learn { color: var(--accent-color, var(--primary-color)); }
        button.stop { color: var(--error-color); }
        .trim { display: flex; align-items: center; gap: 6px; font-size: .82rem; font-weight: 400; }
        .trim input { width: auto; }
        .notice { margin: 0 0 12px; padding: 10px; border-radius: 6px; }
        .notice.error, .error { color: var(--error-color); background: color-mix(in srgb, var(--error-color) 10%, transparent); }
        .notice.success { color: var(--success-color, #2e7d32); background: color-mix(in srgb, var(--success-color, #2e7d32) 10%, transparent); }
        .wave { min-height: 130px; border: 1px dashed var(--divider-color); border-radius: 6px; padding: 8px; overflow: hidden; }
        .wave svg { display: block; width: 100%; height: 110px; }
        .wave line { stroke: var(--divider-color); }
        .wave path { fill: none; stroke: var(--primary-color); stroke-width: 2; vector-effect: non-scaling-stroke; }
        .reference { min-height: 78px; display: flex; align-items: center; justify-content: center; gap: 8px; color: var(--primary-color); }
        .empty, .loading { padding: 18px; text-align: center; color: var(--secondary-text-color); }
        @media (max-width: 520px) {
          .row-actions { flex-wrap: wrap; }
          .trim { width: 100%; }
        }
      </style>
    `;
  }
}

if (!customElements.get("tapo-ir-control-card")) {
  customElements.define("tapo-ir-control-card", TapoIrControlCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "tapo-ir-control-card")) {
  window.customCards.push({
    type: "tapo-ir-control-card",
    name: "Tapo IR Control Panel",
    description: "Utility editor and learning panel for Tapo IR remotes",
    preview: false,
  });
}

console.info(`TAPO-IR-CONTROL-CARD v${CARD_VERSION}`);
