import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const registry = new Map();

class ShadowRoot {
  constructor() {
    this._innerHTML = "";
    this.renderCount = 0;
  }
  set innerHTML(value) {
    this._innerHTML = value;
    this.renderCount += 1;
  }
  get innerHTML() {
    return this._innerHTML;
  }
  addEventListener() {}
  querySelector() {
    return null;
  }
  querySelectorAll() {
    return [];
  }
}

class HTMLElement {
  constructor() {
    this.shadowRoot = null;
    this.events = [];
  }
  attachShadow() {
    this.shadowRoot = new ShadowRoot();
    return this.shadowRoot;
  }
  dispatchEvent(event) {
    this.events.push(event);
    return true;
  }
}

class CustomEvent {
  constructor(type, options) {
    this.type = type;
    Object.assign(this, options);
  }
}

const context = vm.createContext({
  console: { info() {} },
  HTMLElement,
  CustomEvent,
  customElements: {
    define(name, klass) {
      registry.set(name, klass);
    },
    get(name) {
      return registry.get(name);
    },
  },
  document: {
    createElement(name) {
      const Klass = registry.get(name);
      return Klass ? new Klass() : { localName: name };
    },
  },
  window: { customCards: [] },
  CSS: { escape: (value) => value },
  setTimeout,
  clearTimeout,
});

const source = fs.readFileSync(
  new URL(
    "../custom_components/tapo_ir/frontend/tapo-ir-control-card.js",
    import.meta.url
  ),
  "utf8"
);
vm.runInContext(source, context);

const Card = registry.get("tapo-ir-control-card");
const Editor = registry.get("tapo-ir-control-card-editor");
assert.ok(Card);
assert.ok(Editor);
assert.ok(Card.getConfigElement() instanceof Editor);

const stub = Card.getStubConfig();
assert.equal(stub.learn_timeout, 30);
assert.equal(stub.show_waveform, true);
assert.equal(stub.trim_silence, false);

const card = new Card();
card.setConfig({
  title: "IR Lab",
  learn_timeout: 999,
  show_waveform: false,
  trim_silence: true,
});
assert.equal(card._config.title, "IR Lab");
assert.equal(card._config.learn_timeout, 120);
assert.equal(card._config.show_waveform, false);
assert.equal(card._newRow().trim_silence, true);
card._hubs = [
  {
    entry_id: "hub-a",
    hub_id: "id-a",
    name: "Hub A",
    remotes: [{ device_id: "remote-a", name: "Remote A" }],
  },
  {
    entry_id: "hub-b",
    hub_id: "id-b",
    name: "Hub B",
    remotes: [{ device_id: "remote-b", name: "Remote B" }],
  },
];
card._loaded = true;
card.setConfig({
  default_hub: "hub-b",
  default_remote: "remote-b",
});
assert.equal(card._selectedHub, "hub-b");
assert.equal(card._selectedRemote, "remote-b");
assert.equal(card._learningAnchor().remote_device_id, "remote-b");

const editor = new Editor();
editor.setConfig({
  type: "custom:tapo-ir-control-card",
  title: "IR Lab",
});
editor._valueChanged({
  target: {
    dataset: { config: "learn_timeout" },
    type: "number",
    value: "45",
  },
});
assert.equal(editor.events.length, 1);
assert.equal(editor.events[0].type, "config-changed");
assert.equal(editor.events[0].detail.config.type, "custom:tapo-ir-control-card");
assert.equal(editor.events[0].detail.config.learn_timeout, 45);
assert.equal(editor.shadowRoot.renderCount, 1);
editor.setConfig(editor.events[0].detail.config);
assert.equal(editor.shadowRoot.renderCount, 1);

let optionLoads = 0;
editor._hubs = [];
editor._loaded = false;
editor.hass = {
  connection: {
    async sendMessagePromise() {
      optionLoads += 1;
      return { hubs: [] };
    },
  },
};
await new Promise((resolve) => setTimeout(resolve, 0));
editor.hass = editor._hass;
await new Promise((resolve) => setTimeout(resolve, 0));
assert.equal(optionLoads, 1);

const retryEditor = new Editor();
retryEditor.setConfig({ type: "custom:tapo-ir-control-card" });
let retryCalls = 0;
retryEditor.hass = {
  connection: {
    async sendMessagePromise() {
      retryCalls += 1;
      if (retryCalls === 1) throw new Error("temporary failure");
      return { hubs: [{ entry_id: "hub-a", name: "Hub A", remotes: [] }] };
    },
  },
};
await new Promise((resolve) => setTimeout(resolve, 0));
assert.equal(retryEditor._loaded, false);
retryEditor.hass = retryEditor._hass;
await new Promise((resolve) => setTimeout(resolve, 0));
assert.equal(retryCalls, 1, "failed discovery must not retry on every HA state update");
assert.match(retryEditor.shadowRoot.innerHTML, /temporary failure/);
retryEditor._retryAfter = 0;
retryEditor.hass = retryEditor._hass;
await new Promise((resolve) => setTimeout(resolve, 0));
assert.equal(retryCalls, 2);
assert.equal(retryEditor._loaded, true);

const saveCard = new Card();
saveCard.setConfig({});
saveCard._selectedRemote = "remote-a";
saveCard._call = async () => ({
  key_name: "Ab3dE7xQ",
  code: '{"pwm":26,"pulse":"1,2,3"}',
});
saveCard._load = async () => {};
await saveCard._saveRow({
  id: "draft-source",
  label: "Source",
  code: '{"pwm":26,"pulse":"1,2,3"}',
  trim_silence: false,
});
assert.equal(saveCard._selectedButton, "Ab3dE7xQ");
assert.equal(
  saveCard._rowEdits.get("saved-Ab3dE7xQ").code,
  '{"pwm":26,"pulse":"1,2,3"}'
);

const navigationCard = new Card();
navigationCard.setConfig({
  default_hub: "hub-a",
  default_remote: "remote-default",
});
navigationCard._hubs = [
  {
    entry_id: "hub-a",
    hub_id: "id-a",
    name: "Hub A",
    remotes: [
      { device_id: "remote-default", name: "Default", keys: [] },
      { device_id: "remote-active", name: "Active", keys: [] },
    ],
  },
];
navigationCard._loaded = true;
navigationCard._selectedHub = "hub-a";
navigationCard._selectedRemote = "remote-active";
navigationCard._call = async (message) =>
  message.type === "tapo_ir/remotes/list"
    ? { hubs: navigationCard._hubs }
    : { key_name: "Ab3dE7xQ", code: '{"pwm":26,"pulse":"1,2,3"}' };
await navigationCard._saveRow({
  id: "draft-source",
  label: "Source",
  code: '{"pwm":26,"pulse":"1,2,3"}',
  trim_silence: false,
});
assert.equal(navigationCard._selectedRemote, "remote-active");

for (const invalid of ["null", "[]", "3", '{"pwm":0,"pulse":"1,2"}', '{"pwm":26,"pulse":"  "}']) {
  assert.match(vm.runInContext(`codePreview(${JSON.stringify(invalid)})`, context), /class="error"/);
}
const initial = new Card();
initial.setConfig({ trim_silence: true, learn_timeout: 45.7 });
assert.equal(initial._draftRows[0].trim_silence, true);
assert.equal(initial._config.learn_timeout, 45);
assert.throws(() => initial.setConfig({ show_waveform: "false" }), /boolean/);

const drafts = new Card();
drafts.setConfig({});
drafts._selectedRemote = "remote-a";
drafts._draftRows = [
  { id: "draft-one", label: "One", code: '{"pwm":26,"pulse":"1,2"}' },
  { id: "draft-two", label: "Two", code: '{"pwm":26,"pulse":"3,4"}' },
];
let resolveSave;
let saveCalls = 0;
drafts._call = () => { saveCalls++; return new Promise((resolve) => { resolveSave = resolve; }); };
drafts._load = async () => {};
const saving = drafts._saveRow(drafts._draftRows[0]);
await drafts._saveRow(drafts._draftRows[0]);
assert.equal(saveCalls, 1, "double-click must not duplicate a write");
resolveSave({ key_name: "saved-one", code: '{"pwm":26,"pulse":"1,2"}', waveform_verified: false });
await saving;
assert.equal(drafts._draftRows.length, 1);
assert.equal(drafts._draftRows[0].label, "Two");
assert.equal(drafts._selectedButton, "__new_button__");
assert.match(drafts._message, /does not expose/);

const creating = new Card();
creating.setConfig({});
creating._selectedHub = "hub-a";
creating._newRemoteName = "New TV";
creating._call = async () => ({
  remote_device_id: "created", keys: [{ key_name: "vendor-key", code: '{"pwm":26,"pulse":"100,200"}', waveform_verified: false }],
});
creating._load = async () => {};
await creating._saveRow({ id: creating._draftRows[0].id, label: "Source", code: '{"pwm":26,"pulse":"100,200"}' });
assert.equal(creating._selectedButton, "vendor-key");
assert.equal(creating._previews.get("saved-vendor-key"), '{"pwm":26,"pulse":"100,200"}');

card._rowEdits.set("saved-power", { label: "Wrong remote" });
card._previews.set("saved-power", "old-code");
card.setConfig({ default_hub: "hub-a", default_remote: "remote-a" });
assert.equal(card._rowEdits.size, 0);
assert.equal(card._previews.size, 0);
const unknownEditor = new Editor();
unknownEditor.setConfig({ default_hub: "offline-hub", default_remote: "Named Remote" });
assert.match(unknownEditor.shadowRoot.innerHTML, /Configured: offline-hub/);
assert.match(unknownEditor.shadowRoot.innerHTML, /Configured: Named Remote/);

let stopped;
drafts._learningRow = "draft-two";
drafts._call = async (message) => { stopped = message; return {}; };
await drafts._stopLearning();
assert.equal(stopped.remote_device_id, "remote-a");
assert.equal(drafts._learningRow, "draft-two", "only the capture completion may unlock selection");

const deleting = new Card();
deleting.setConfig({});
deleting._loaded = true;
deleting._hubs = [{
  entry_id: "hub-a", name: "Hub A", remotes: [{
    device_id: "remote-a", name: "TV", keys: [
      { name: "vendor-source", label: "Source", code: "" },
      { name: "power", label: "Power", code: "" },
    ],
  }],
}];
deleting._selectedRemote = "remote-a";
deleting._selectedButton = "vendor-source";
const deletingRow = { id: "saved-vendor-source", key_reference: "vendor-source", label: "Unsaved label", code: "unsaved code" };
deleting._rowEdits.set(deletingRow.id, deletingRow);
deleting._previews.set(deletingRow.id, deletingRow.code);
deleting._draftRows = [{ id: "draft-keep", label: "Keep me", code: "draft code" }];
assert.match(deleting._renderRow(deletingRow, false), /data-action="delete-row"/);
assert.match(deleting._renderRow(deletingRow, false), /aria-label="Delete saved button"/);
assert.match(deleting._renderRow(deleting._draftRows[0], true), /aria-label="Remove draft"/);
const deleteCalls = [];
let resolveDelete;
deleting._call = (message) => {
  deleteCalls.push(message);
  return new Promise((resolve) => { resolveDelete = resolve; });
};
deleting._load = async () => {};
let confirmations = 0;
context.window.confirm = (text) => {
  confirmations++;
  assert.match(text, /"Source" from "TV"/, "confirm saved identity, not an edited label");
  return false;
};
await deleting._deleteRow(deletingRow);
assert.equal(deleteCalls.length, 0, "cancel must never write");
assert.equal(deleting._rowEdits.get(deletingRow.id).code, "unsaved code");
context.window.confirm = () => { confirmations++; return true; };
deleting._learningRow = "draft-keep";
await deleting._deleteRow(deletingRow);
assert.equal(confirmations, 1, "learning must block deletion before confirmation");
deleting._learningRow = null;
const deleteButton = { dataset: { action: "delete-row" } };
deleting._rowElement = () => ({});
deleting._rowState = () => deletingRow;
const pendingDelete = deleting._onClick({ composedPath: () => [deleteButton] });
assert.equal(deleting._busy, true);
await deleting._deleteRow(deletingRow);
assert.equal(deleteCalls.length, 1, "double-click must not duplicate deletion");
assert.deepEqual(JSON.parse(JSON.stringify(deleteCalls[0])), {
  type: "tapo_ir/key/delete", remote_device_id: "remote-a",
  key_reference: "vendor-source", confirmation: "DELETE",
});
resolveDelete({ deleted_key_name: "vendor-source", verified: true });
await pendingDelete;
assert.equal(deleting._busy, false);
assert.equal(deleting._rowEdits.has(deletingRow.id), false);
assert.equal(deleting._previews.has(deletingRow.id), false);
assert.equal(deleting._remote().remote.keys[0].name, "power");
assert.equal(deleting._draftRows[0].label, "Keep me");
assert.equal(deleting._selectedButton, "__new_button__");
assert.match(deleting._message, /deleted.*verified/);
deleting._selectedButton = "power";
const powerRow = { id: "saved-power", key_reference: "power", label: "Power", code: "keep on failure" };
deleting._call = async () => { throw new Error("Hub rejected deletion"); };
await deleting._deleteRow(powerRow);
assert.match(deleting._error, /Hub rejected deletion/);
assert.equal(deleting._selectedButton, "power");
assert.equal(deleting._rowEdits.get(powerRow.id).code, "keep on failure");
assert.equal(deleting._remote().remote.keys.length, 1);
deleting._call = async () => ({ deleted_key_name: "power", verified: true });
await deleting._deleteRow(powerRow);
assert.equal(deleting._remote().remote.keys.length, 0, "last-button removal must retain remote");
deleting._call = async () => { throw new Error("Draft removal must not contact hub"); };
context.window.confirm = () => false;
await deleting._deleteRow(deleting._draftRows[0]);
assert.equal(deleting._draftRows[0].label, "Keep me");
context.window.confirm = () => true;
await deleting._deleteRow(deleting._draftRows[0]);
assert.equal(deleting._draftRows.length, 1);
assert.equal(deleting._draftRows[0].label, "", "retain a usable empty row");
assert.match(deleting._message, /Nothing was changed on the hub/);

// Load the optional control card in its own ES-module-like scope.
vm.runInContext(`{ ${fs.readFileSync(new URL("../lovelace/tapo-ir-card.js", import.meta.url), "utf8")} }`, context);
const RemoteCard = registry.get("tapo-ir-card");
const control = new RemoteCard();
control.setConfig({ hub: "Hub A" });
control._hass = {
  entities: {
    "sensor.a": { entity_id: "sensor.a", device_id: "a", platform: "tapo_ir" },
    "sensor.b": { entity_id: "sensor.b", device_id: "b", platform: "tapo_ir" },
    "button.child": { entity_id: "button.child", device_id: "child", platform: "tapo_ir" },
  },
  devices: { a: { name: "Hub A" }, b: { name: "Hub B" }, child: { name: "TV B", via_device_id: "b" } },
  states: { "button.child": { state: "unknown", attributes: { friendly_name: "TV B Power" } } },
};
assert.equal(control._discover()[0].children.length, 0, "excluded hub children must not leak into another hub");
control._hass.devices.child.via_device_id = "a";
let builds = 0;
control._renderStructure = () => { builds++; };
control._update();
control._hass.states["button.child"].attributes.friendly_name = "TV B Source";
control._update();
assert.equal(builds, 2, "label-only edits must update the rendered card");
delete control._hass.entities["sensor.a"];
delete control._hass.entities["sensor.b"];
assert.equal(control._discover()[0].children.length, 1, "hidden hub diagnostics must not hide remotes");
let disabled;
control.shadowRoot.querySelectorAll = (selector) => selector === ".chip" ? [] : [{
  dataset: { entity: "button.missing" }, toggleAttribute: (_name, value) => { disabled = value; },
}];
control._refreshStates();
assert.equal(disabled, true);
control._hass.callService = async () => { throw new Error("Hub offline"); };
await control._onClick({ composedPath: () => [{ dataset: { action: "press", entity: "button.child" } }] });
assert.equal(control._error, "Hub offline");

console.log("Tapo IR card/editor and legacy card regression tests passed");
