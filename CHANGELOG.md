# Changelog

## 2.0.3 - 2026-08-30

### Fixed

- Added an explicit migration bridge for button entities created by the retired
  `tplink_ir` sidecar.
- Sidecar entity IDs are captured by remote identity and key identity/label,
  then transferred to Tapo IR when the old platform is unloaded.
- If the sidecar is still loaded, the mapping is retained in the config entry
  and applied on the next reload after sidecar removal.
- Existing dashboard, script, and automation references therefore retain their
  entity IDs instead of receiving unexpected numeric suffixes.

## 2.0.2 - 2026-08-30

### Fixed

- Shared Tapo IR entries now resume immediately when their owning core TP-Link
  entry transitions back to loaded after a device power-cycle or network
  recovery.
- Recovery no longer waits for an independent Tapo IR setup-retry backoff after
  the parent hub is already healthy.

## 2.0.1 - 2026-08-30

### Fixed

- Shared-session entries now reject stale cached child data whenever the owning
  TP-Link coordinator is unavailable.
- Tapo IR entities now become unavailable with their parent hub instead of
  presenting old remote data as healthy.

### Added

- Added privacy-safe config-entry diagnostics with parent coordinator health,
  remote inventory, label-source counts, and no credentials or IR waveforms.
- Added a translated Repair issue for an unavailable shared TP-Link parent,
  automatically cleared when the hub recovers.
- Added safe removal support for hub and remote devices no longer reported by
  the integration.
- Declared explicit platform request parallelism.

## 2.0.0 - 2026-08-30

### Fixed

- Fixed issue #1 across `plugp100` 5.1, 5.2, and 6.0 package layouts without
  reintroducing the exact dependency pin conflict from the markesss fork.
- Added an explicit H110 KLAP v2 fallback for firmware where automatic protocol
  detection fails.
- Replaced malformed control-byte, truncated, all-caps, and opaque generated
  labels with normalized, deterministic entity names.
- Moved key unique IDs from editable labels to stable protocol identity while
  preserving existing registry entity IDs during migration.

### Added

- Added credential-free shared-session mode based on the proven active
  `tplink_ir` sidecar architecture.
- Added verified remote and key create, edit, learn, rename, and delete
  transactions.
- Added standard `remote` entities for every virtual profile.
- Integrated the WhiteEyeYan AC climate feature with only confirmed HVAC modes
  and explicit error handling.
- Added the auto-loaded `custom:tapo-ir-control-card` utility editor with
  dropdown discovery, exact code text, visualization, learning, manual stop,
  conservative silence trimming, and atomic new-remote creation.
- Added focused tests for observed label corruption and IR code validation.

### Safety

- The utility card contains no IR transmit action.
- Learning never auto-saves a capture.
- Full waveform data is excluded from entity states and exposed only through
  admin-only WebSocket requests.
- Factory keys whose hubs expose only a protocol reference are represented
  honestly and remain usable; the editor does not invent a missing waveform.
- No IR command was transmitted while preparing this change.
- Write and transmit requests are never retried automatically, preventing one
  failed response from duplicating a physical action.
- AC status commands refuse incomplete source state instead of inventing values
  for unknown fields.
