# Compact One Dark dictation pill

## Goal

Replace the tall purple recording card (organic orb blob + status row + inline
settings/history panel) with a minimal single-row pill, about button height,
themed with Atom One Dark, showing a reactive equalizer instead of the orb.

## Form and size

- The floating recording window becomes a single-row pill, ~220 x 44 px
  (was 340 x 170).
- Frameless, rounded (10px), always-on-top, draggable, does not steal focus
  (all existing window flags preserved).
- Recording mode shows only the indicator row. No chevron, no inline
  settings/history.

## Indicator: RecordingBar widget (new file recordingbar.py)

A single self-contained QWidget that paints, left to right:

1. A pulsing record dot.
2. A row of ~14 equalizer bars driven by mic level (same level/buffer feed the
   old WaveformWidget consumed via `update_waveform(level, buffer)`).
3. An elapsed timer label (e.g. `0:04`).

State-driven colors (Atom One Dark):

- Recording: dot `#e06c75` (red, breathing), bars `#61afef` (blue), reacting to
  voice level.
- Transcribing: bars shimmer in `#e5c07b` (yellow), timer frozen.
- Done: brief `#98c379` (green) flash, then the window hides.

The widget exposes the same update surface the app already calls so the wiring
in main.py changes minimally: `set_recording(bool)`, `update_waveform(level,
buffer)`, plus a `set_state(...)` for transcribing/done and timer control.

`waveform.py`'s `WaveformWidget` (the blob) is retired from the recording view.
The file is left in place (unused) rather than deleted.

## Theme: Atom One Dark

- Pill surface `#21252b`, ~95% opaque; border `#181a1f`.
- Text/timer `#abb2bf`; secondary `#5c6370`.
- The settings/history panel restyled from purple/lime to the One Dark palette.

## Settings relocation

The recording pill carries no settings UI. Settings and history stay reachable
via the existing tray entry "Settings..." (`_show_settings`), which opens the
panel as its own larger window. No feature removed, only moved out of the
floating bar.

## Scope

Touched:
- `recordingbar.py` (new) - the RecordingBar widget.
- `main.py` - RecordingWindow recording-mode layout, pill sizing, swap
  WaveformWidget -> RecordingBar, remove the inline chevron/settings from the
  recording view (keep the settings panel reachable via tray), One Dark styling.
- `config.py` - new default window size; keep the larger size for the settings
  view.
- live `config.json` - window size.

Not touched: recording/transcription/typing pipeline, hotkey handling, API
client.

## Out of scope

- No change to the transcription, typing, mic, or API behavior.
- No new settings/preferences for theme or animation (single fixed One Dark
  look for now).
