# Tapo IR Hub for Home Assistant

[![hacs][hacs-badge]][hacs-url]
[![release][release-badge]][release-url]
[![license][license-badge]](LICENSE)

A local Home Assistant integration for Tapo H1xx IR hubs such as the H110.
It discovers every virtual remote stored on the hub, creates readable Home
Assistant entities, and provides a utility dashboard card for safely viewing,
learning, creating, and editing IR codes.

## Highlights

- Reuses Home Assistant's loaded core TP-Link session when available. This
  credential-free mode prevents competing KLAP sessions and is recommended.
- Retains direct Tapo credential mode for installations where the core TP-Link
  integration does not expose the hub.
- Creates a device per virtual remote, a normalized `button` entity per key,
  and a standard `remote` entity per profile.
- Adds a conservative climate entity for AC profiles, based on the AC work in
  the WhiteEyeYan fork.
- Bundles and automatically loads `custom:tapo-ir-control-card`.
- Verifies every create, edit, learn, rename, and delete operation by reading
  the result back from the hub.
- Keeps full IR waveforms out of entity states and recorder history.

## Installation

1. Add this repository to HACS as an **Integration** and download it:

   [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.][my-hacs-badge]][my-hacs-url]

2. Restart Home Assistant.
3. Add **Tapo IR Hub**:

   [![Open your Home Assistant instance and start setting up a new integration.][my-config-badge]][my-config-url]

4. Choose a connection:
   - **Shared TP-Link hub (recommended):** select a compatible hub already
     loaded by Home Assistant's TP-Link integration. No credentials are stored.
   - **Direct connection:** enter the hub IP and case-sensitive Tapo account
     username and password.

Home Assistant 2024.6 or newer is required.

## Entities and naming

The physical hub receives a **Rescan devices** button plus diagnostic sensors.
Each stored remote becomes a child device containing:

- one `button` entity per saved key;
- one `remote` entity supporting `remote.send_command`;
- one climate entity when the profile reports model `AC`.

Vendor labels are not trusted blindly. The normalizer:

- strips NUL and control-byte metadata;
- expands protocol names such as `NAVIGATE_UP`, `TEMP+`, and `VOL-`;
- formats all-caps labels while preserving acronyms such as TV, USB, and OK;
- replaces generated eight-character identifiers with deterministic
  **Unlabeled Button N** names instead of presenting random tokens as labels;
- uses protocol key identity, not the editable label, for new unique IDs.

Existing entity registry IDs are retained during migration, so changing a
display label does not needlessly break automations. User-assigned names remain
under Home Assistant's normal entity-registry control.

## Tapo IR Control Panel card

The integration serves and loads the card automatically. Add it from the
dashboard card picker or use:

```yaml
type: custom:tapo-ir-control-card
title: Tapo IR Control Panel
```

The card is intentionally a utility editor rather than a decorative remote.
It has no transmit action.

### Existing remote workflow

1. Select a remote.
2. Select one of its buttons or **+ New Button**.
3. Review or edit the exact stored JSON representation:

   ```json
   {"pwm":26,"pulse":"..."}
   ```

4. Use:
   - **save** to write and verify the value;
   - **plus** to add another draft button;
   - **refresh** to render the current text without saving it;
   - **brain** to enter receive mode and capture one signal;
   - **stop** to leave receive mode before its 30-second timeout.

The waveform view is deliberately simple. Numeric pulse trains are drawn as
alternating marks and spaces. Encoded pulse strings are shown as a byte-level
shape so users can still compare captures without the card guessing a protocol.
Some factory-provided Tapo keys are exposed by the hub only as a protocol name
and PWM value, not as an editable pulse waveform. The card shows that exact
reference and keeps the button usable; replacing it requires learning or
pasting a complete waveform first.

### New remote workflow

Choose **+ New Remote**, select the target hub, enter the remote and first
button names, then enter or learn a code. The backend creates the remote and
first button as one transaction. A remote is never intentionally left saved
without at least one verified button; failed first-button writes trigger
cleanup of the new remote.

### Learning and cleanup

Learning starts the hub's receive mode but does not save or transmit anything.
The captured code populates the editor and visualizer; the user must explicitly
save it. The backend always requests `stopIrReceiveMode` on success, error,
timeout, or manual stop.

The optional trim control removes only explicit leading and trailing zero
tokens from numeric pulse sequences. It refuses opaque encodings instead of
guessing where valid signal data ends.

Card management commands are admin-only WebSocket commands authenticated by
Home Assistant. Full pulse data is returned only on demand to the editor.

## Existing remote-control card

The original `lovelace/tapo-ir-card.js` remains available for users who want a
button-oriented transmitting remote. It is separate from the control panel and
must still be installed as described in [lovelace/README.md](lovelace/README.md).

## AC climate support

AC profile parsing and `sendIrCmdByStatus` support incorporate the useful part
of the WhiteEyeYan fork with safer behavior:

- only the confirmed Cool (`M0`) and Heat (`M1`) mappings are exposed;
- unsupported modes fail explicitly instead of silently doing nothing;
- ambient temperature is not fabricated from the target temperature;
- state is labeled as last-known IR profile state because IR provides no device
  feedback.

Fan (`auto`, `low`, `high`) and swing (`auto`, `fixed`) mappings are retained
from the fork. Confirm device behavior before using them in unattended
automations. The integration refuses partial AC commands until the hub has
reported all P/M/T/S/D fields; it never fills unknown physical state with
invented defaults.

## Issue #1 and plugp100 compatibility

Fresh installs of v1.0.2 could fail with:

```text
No module named 'plugp100.new'
```

The requirement allowed several `plugp100` releases, but the factory import was
hard-coded to the layout used only by 5.1.x. The module moved in 5.2 and again
in 6.0.

This tree isolates the import in `compat.py` and supports all known layouts:

1. `plugp100.devices.factory` (6.0+)
2. `plugp100.devices.device_factory` (5.2)
3. `plugp100.new.device_factory` (5.1)

The compatible version range remains intentionally non-exact so another Tapo
integration cannot force a repeated upgrade/downgrade conflict in Home
Assistant's shared Python environment. Direct mode also retries H110
auto-detection with the explicit `SMART.TAPOHUB` / H110 / KLAP v2 profile
reported to work for affected EU hardware.

If direct authentication still fails:

- preserve the exact capitalization of the Tapo account username;
- verify the hub is locally reachable;
- if the hub was onboarded through TP-Link Simple Setup and retained stale
  credentials, factory-reset it and onboard it directly on an isolated 2.4 GHz
  network before trying again.

## Architecture and safety

- **Shared mode:** calls the already-loaded core TP-Link coordinator and its
  child protocol wrappers. It opens no second connection and stores no Tapo
  credentials.
- **Direct mode:** owns one serialized `plugp100` client and reconnects only
  after an explicit request failure.
- **Mutations:** lock per configured hub, snapshot before modification, write,
  refresh, compare exact read-back, and surface any mismatch.
- **Entity states:** contain command identity and friendly metadata only, not
  raw pulse strings.
- **Frontend:** served by Home Assistant as a versioned ES module and talks only
  through authenticated WebSocket commands.

No telemetry or cloud service is used.

## Development

Run the focused dependency-free checks:

```text
python -m unittest discover -s tests -v
python -m compileall -q custom_components/tapo_ir
node --check custom_components/tapo_ir/frontend/tapo-ir-control-card.js
```

See [CHANGELOG.md](CHANGELOG.md) for the unreleased consolidation details.

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
