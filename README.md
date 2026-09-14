**English** | [Русский](README.ru.md)

# Glyphstroke

Control your computer with mouse gestures: hold a button, draw a sign, release —
the assigned action runs. The plain click keeps working as before.

The program comes for three systems. Their recognition core is identical
number-for-number, while everything that talks to the OS is its own — hence the
three folders:

| System | Folder | How capture works |
|---|---|---|
| Linux (X11 and Wayland) | [`linux/`](linux/) | evdev + uinput; a GNOME Shell extension for the trail on Wayland |
| macOS | [`macos/`](macos/) | Quartz Event Services (CGEventTap), Swift + AppKit |
| Windows | [`windows/`](windows/) | a low-level hook, C# + WPF |

Installation and build instructions are in the README inside each folder.

## Download

Ready-made packages are on the [releases page](../../releases/latest): a `.deb`
for Linux, a `.dmg` for macOS and an `.exe` installer for Windows.

## System requirements

| System | Minimum | Extra libraries |
|---|---|---|
| Linux | X11 or Wayland session; Python 3.9+ | `python3-evdev`, `python3-yaml` (required); `python3-gi` + `gir1.2-gtk-3.0` for the editor and the X11 trail. The `.deb` pulls these in itself. |
| macOS | macOS 13 (Ventura) or newer, Apple Silicon | none — the app carries everything it needs |
| Windows | Windows 10 or 11, 64-bit | none — the installer is self-contained (.NET is bundled) |

Details for each system are in its folder's README.

## Gestures move between systems

The file format is shared: `settings.yaml` and `gestures/*.yaml`. A gesture set
moves from one machine to another by copying the folder. So that the actions
move too, gestures have a "standard action" type — the file holds a name
(`copy`, `back`, `minimize`), and the shortcut is filled in by whichever system
runs the gesture: `ctrl+c` on Linux and Windows, `cmd+c` on macOS.

## How it works

While the modifier button is held (the right one by default), its press is kept
back. Release it without a stroke and the program sends a normal click — the
context menu opens as usual. Draw a stroke and the click is not sent; the bound
action runs instead. The stroke shape is matched two ways: by a direction code
(`D-R` — "down, then right") and by drawn samples (the $1 Unistroke algorithm).

## Updates

Each version checks once a day whether a newer release is out and, if so, shows
a message with a link. The program does not update itself: mouse capture is not
the place for a silent swap — installing a new version is up to you. The check
can be turned off in the settings.

## Support

The program is free. If it is useful to you and you would like to support the
development — [boosty.to/runetrace](https://boosty.to/runetrace).

## Licence

PolyForm Noncommercial 1.0.0 — see the [`LICENSE`](LICENSE) file. In short: free
non-commercial use is allowed, as is reading and modifying the code; selling the
program or its modifications is not.
