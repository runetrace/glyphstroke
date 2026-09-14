**English** | [Русский](README.ru.md)

# Glyphstroke for macOS

Control your computer with mouse gestures: hold a button, draw a sign, release —
the assigned action runs. The plain click keeps working as before.

## System requirements

- macOS 13 (Ventura) or newer.
- Apple Silicon (M1 and later): the release package is built for arm64. On Intel
  Macs, build from source (see "Build").
- No extra libraries are needed — the app carries everything it needs. On first
  launch you grant two permissions: Input Monitoring and Accessibility.

## Installation

Download `Glyphstroke-0.5.0.dmg`, open it and drag **Glyphstroke** into the
Applications folder. Launch it. On first launch the program opens a window and
asks for two permissions:

- **Input Monitoring** — to see mouse movement;
- **Accessibility** — to run actions and to know the active window.

Buttons in the window open the right page of System Settings. Once granted,
press "Restart" in the same window.

The icon appears in the menu bar — gestures, settings, pause and the log live
there.

On first launch the system may warn about an unknown developer: that goes away
once the program has an Apple signature.

## How to use

Hold the right mouse button, draw a sign, release. Signs are configured in the
editor (menu-bar icon → "Gestures…"): draw a sample or type a direction code,
for example `D-R` — "down, then right".

## Features

- stroke recognition and a trail behind the cursor;
- actions: standard ones from a list (copy, paste, minimise the window and so
  on), keys, text, launching programs, commands, clicks, scrolling, window
  actions;
- a gesture editor with sample drawing, split into the "Stroke", "Actions" and
  "Menu" tabs;
- a menu under a gesture: give it items and it opens a menu at the cursor
  instead of running its own actions;
- gesture sets: separate folders you switch between right in the editor;
- a target button: point at a window and its app lands in the gesture's
  conditions;
- settings: the modifier button, the stroke threshold, the trail look,
  autostart, theme and language;
- help inside the program;
- an update check once a day;
- a menu-bar icon with pause and the log.

## Where settings live

Files are in `~/Library/Application Support/Glyphstroke/`: `settings.yaml`, the
`gestures/` folder with the main set and the `profiles/` folder with the rest.
The format is shared with the Linux and Windows versions — gestures move by
copying the folder.

## Build

You need Xcode or the Command Line Tools with Swift 5.9 or newer.

```bash
swift build                  # check that it builds
swift test                   # core tests
./scripts/build-app.sh       # build Glyphstroke.app
./scripts/make-dmg.sh        # build the image for distribution
```

Open in Xcode: File → Open → `Package.swift`.

Distributing to others needs signing and notarisation with Apple (an Apple
Developer account): without them the image opens only on the machine where it
was built. The signing commands are in the comments of `scripts/make-dmg.sh`.

## Licence

PolyForm Noncommercial 1.0.0: free for non-commercial use, selling is not
allowed. Full text in the `LICENSE` file at the repository root.
