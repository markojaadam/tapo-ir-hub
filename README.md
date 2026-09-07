# Tapo IR Hub for Home Assistant

[![hacs][hacs-badge]][hacs-url]
[![release][release-badge]][release-url]
[![license][license-badge]](LICENSE)

Local control and management for the IR remotes stored on Tapo H1xx hubs such
as the H110. The integration creates native Home Assistant devices and entities
for each remote, with dashboard tools for everyday control and IR code
management.

## Features

- Local communication with the hub; no bridge, MQTT broker, or cloud service
  required
- Credential-free connection through Home Assistant's TP-Link integration
- Direct connection option for installations where a shared TP-Link hub is not
  available
- A Home Assistant device for every stored IR remote
- Readable, normalized button names and stable entity identities
- Standard `remote` entities with `remote.send_command` support
- Climate entities for compatible AC profiles
- Automatic discovery of remotes and buttons
- Verified creation, editing, learning, renaming, and deletion
- Two dashboard cards:
  - **Tapo IR Control Panel** for managing remotes and IR codes
  - **Tapo IR Card** for button-based remote control

## Requirements

- Home Assistant 2026.8 or newer (the shared adapter uses current core
  TP-Link runtime and entity-registry APIs)
- A Tapo H1xx IR hub reachable on the local network
- For the recommended connection: a compatible hub configured in Home
  Assistant's TP-Link integration
- For a direct connection: the hub IP address and Tapo account credentials

The integration supports the `plugp100` factory layouts used by versions 5.1,
5.2, and 6.x.

## Installation

1. Add this repository to HACS as an **Integration**:

   [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.][my-hacs-badge]][my-hacs-url]

2. Download **Tapo IR Hub** and restart Home Assistant.
3. Add the integration:

   [![Open your Home Assistant instance and start setting up a new integration.][my-config-badge]][my-config-url]

4. Select a connection method:
   - **Shared TP-Link hub (recommended):** choose a compatible hub already
     loaded by Home Assistant. Tapo IR Hub stores no credentials and uses the
     hub's established local session.
   - **Direct connection:** enter the hub IP address and the case-sensitive
     Tapo account username and password.

Repeat the setup flow for each IR hub.

## Home Assistant devices and entities

Each physical hub provides:

- **Rescan devices** button
- **Discovered devices** diagnostic sensor
- **Last scan** diagnostic sensor

Each stored IR remote appears as a child device with:

- one `button` entity per saved key;
- one `remote` entity for use with `remote.send_command`;
- one climate entity when the remote profile reports model `AC`.

Button labels are cleaned and formatted automatically. Control bytes and
truncated vendor metadata are removed, known protocol names are expanded, and
acronyms such as TV, USB, and OK remain intact. When a hub supplies only an
opaque generated identifier, Home Assistant shows a deterministic
**Unlabeled Button N** name instead of presenting the token as a meaningful
label. User-assigned entity names remain under Home Assistant's normal entity
registry control.

## Tapo IR Control Panel

The management card is bundled with the integration and loaded automatically.
Add it from the dashboard card picker or use:

```yaml
type: custom:tapo-ir-control-card
title: Tapo IR Control Panel
default_hub: ""
default_remote: ""
learn_timeout: 30
show_waveform: true
trim_silence: false
```

The card is designed for utility rather than remote control. It cannot transmit
an IR command.

The card supports both Home Assistant's Visual Editor and direct YAML editing.
The optional `default_hub` accepts a hub entry ID, hub ID, or hub name;
`default_remote` accepts a remote device ID or name. The learning timeout is
limited to 5-120 seconds.

### Manage an existing remote

1. Select a remote.
2. Select a saved button or **+ New Button**.
3. Review, learn, or enter its IR code.
4. Use the row controls:
   - **Save** writes the code and verifies it against the hub.
   - **Plus** creates another button row.
   - **Refresh** redraws the visualization from the current text.
   - **Brain** starts IR learning.
   - **Stop** ends an active learning session.
   - **Trash** deletes a saved button from the hub after confirmation, or
     discards an unsaved draft without contacting the hub.

Deletion verifies that the saved button is gone before reporting success.
It does not delete the remote, even when removing its last button. Other buttons
and unsaved drafts are preserved. Existing Home Assistant references to a deleted
button become unavailable; update affected dashboards and automations and remove
the obsolete entity from the entity registry if no longer needed. Deletion cannot
be undone, so copy any available code before proceeding.

Editable waveforms use this representation:

```json
{"pwm":26,"pulse":"..."}
```

Numeric pulse values are plotted in sequence, not to a timing scale. Opaque
encodings receive a character-level comparison plot, not a decoded waveform.
Previewing does not prove that a code will control an appliance.

Some factory-provided keys are exposed by the hub only as a protocol name and
PWM value. These keys remain fully usable for control. The card displays the
available protocol reference and requires a learned or pasted waveform before
the saved code can be replaced.

### Create a remote

Choose **+ New Remote**, select the target hub, and enter the remote name plus
its first button. The remote is saved only after the first button has been
written and verified. If that transaction fails, the partially created remote
is removed when it can be identified safely and cleanup succeeds. If the hub
disconnects during creation or cleanup, inspect its remote list before retrying.
An unidentified remote is never adopted or deleted based on timing alone.

### Learn an IR code

The brain button places the hub in receive mode for the configured timeout
(30 seconds by default). A captured
signal fills the editor and updates the visualization, but it is not stored
until **Save** is selected. Receive mode is stopped after capture, timeout,
error, or a manual stop. Stop applies to the selected hub; the editor remains
locked until cleanup finishes. A failed stop is reported explicitly.

The optional trim control removes explicit leading and trailing zero tokens
from numeric pulse sequences. It does not modify opaque encodings.

Management commands use Home Assistant's authenticated WebSocket API and
require an administrator account. Full waveform data is requested only while
using the editor and is not placed in normal entity states.

Some hubs hide pulse data even after accepting a learned button. In that case
the editor confirms the saved identity and label, but explicitly reports that
the waveform itself could not be compared. The last submitted code remains
visible for that editing session; it is not represented as hub-read waveform data.

## Tapo IR Card

The button-oriented card in `lovelace/tapo-ir-card.js` provides a conventional
remote-control dashboard with grid and handset layouts, automatic device
discovery, filters, collapsible panels, and diagnostic controls.

Installation and configuration are documented in
[lovelace/README.md](lovelace/README.md).

## AC climate control

AC profiles expose:

- Off, Cool, and Heat HVAC modes
- Target temperature
- Auto, Low, and High fan modes
- Auto and Fixed swing modes

IR is one-way communication, so the climate entity represents the last known
profile state rather than measured feedback from the appliance. Ambient
temperature is not inferred from the target temperature. Commands are sent only
when the hub has supplied a complete AC state.

Confirm that the profile's fan and swing behavior matches the appliance before
using those controls in unattended automations.

## Connection modes

### Shared TP-Link session

Shared mode uses the loaded TP-Link coordinator and its child protocol wrappers.
It opens no additional hub connection and stores no Tapo credentials. This is
the recommended option when the hub is already available through Home
Assistant's TP-Link integration.

### Direct connection

Direct mode owns one serialized local `plugp100` connection. Read operations
may reconnect after a stale session; write and transmit operations are never
retried automatically.

## Reliability and safety

- Hub mutations are serialized per configured hub.
- Shared IR availability follows the owning TP-Link coordinator; cached remote
  data is never presented as healthy after a failed parent refresh.
- Writes are refreshed and compared with their read-back result.
- Remote creation attempts verified cleanup of incomplete work.
- Nested protocol failures are surfaced instead of reported as success.
- AC commands do not fill unknown state with assumed values.
- Entity states contain command identity and friendly metadata, not raw pulse
  strings.
- The management card has no IR transmission API.
- No telemetry is collected.

Config-entry diagnostics contain parent health and remote inventory while
redacting credentials, network addresses, device identifiers, and IR
waveforms. An unavailable shared parent also creates a Home Assistant Repair
issue that clears automatically after recovery.

### Options and removal

Use the integration's options to set the refresh interval (30-3600 seconds,
300 by default) and optional JSON name overrides mapping remote IDs to names.
The hub's Rescan button requests an earlier refresh.

To remove the integration, delete its entry under **Settings > Devices &
services**, then uninstall it in HACS and restart Home Assistant. This removes
Home Assistant entities, not remotes or codes stored on the hub. Remove any
manually installed dashboard resources/cards separately. Shared TP-Link entries
and entities are owned by the core integration and are not deleted.

## Troubleshooting

### Direct authentication fails

- Preserve the exact capitalization of the Tapo account username.
- Confirm that the hub IP is reachable from Home Assistant.
- If TP-Link Simple Setup copied stale credentials to the hub, factory-reset
  the hub and onboard it directly on an isolated 2.4 GHz network.
- Prefer the shared TP-Link connection when it is available.

### A button has no editable waveform

Factory remote profiles may expose a key by protocol reference without
returning its pulse data. The button can still be used normally. Use the brain
button to learn a replacement waveform before saving changes to that key.

### A new remote or button does not appear

Press **Rescan devices** on the hub or wait for the configured refresh interval.

## Development

Run the focused checks:

```text
python -m unittest discover -s tests -v
python -m compileall -q custom_components/tapo_ir
node --check custom_components/tapo_ir/frontend/tapo-ir-control-card.js
node --check lovelace/tapo-ir-card.js
node tests/test_card.mjs
```

These dependency-free regression tests simulate hub and Home Assistant
boundaries. They do not certify all firmware versions or replace testing on a
running Home Assistant instance. The quality-scale checklist tracks remaining
work; no official integration tier is claimed.

Release history and upgrade-specific details are available in
[CHANGELOG.md](CHANGELOG.md) and the
[GitHub releases](https://github.com/Loadst0ne/tapo-ir-hub/releases).

## License

[MIT](LICENSE) (c) Loadst0ne

[hacs-badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge
[hacs-url]: https://hacs.xyz/
[release-badge]: https://img.shields.io/github/v/release/Loadst0ne/tapo-ir-hub?style=for-the-badge
[release-url]: https://github.com/Loadst0ne/tapo-ir-hub/releases
[license-badge]: https://img.shields.io/github/license/Loadst0ne/tapo-ir-hub
[my-hacs-badge]: https://my.home-assistant.io/badges/hacs_repository.svg
[my-hacs-url]: https://my.home-assistant.io/redirect/hacs_repository/?owner=Loadst0ne&repository=tapo-ir-hub&category=integration
[my-config-badge]: https://my.home-assistant.io/badges/config_flow_start.svg
[my-config-url]: https://my.home-assistant.io/redirect/config_flow_start/?domain=tapo_ir
