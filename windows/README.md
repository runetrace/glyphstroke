**English** | [Русский](README.ru.md)

# Glyphstroke for Windows

Control your computer with mouse gestures: hold a button, draw a sign, release —
the assigned action runs. The plain click keeps working as before.

## System requirements

- Windows 10 or 11, 64-bit.
- No extra libraries are needed — the installer is self-contained, .NET is
  bundled. Administrator rights are not required to install.

## Installation

Run `Glyphstroke-0.3.5-setup.exe` and go through the setup. Administrator rights
are not needed — the program installs for a single user.

On first launch Windows may show a SmartScreen window, "Windows protected your
PC" — that is how the system greets any program without a signature: "More
info" → "Run anyway". It goes away once the program has a signing certificate.

The icon appears in the notification area, bottom right — gestures, settings,
pause and the log live there.

## How to use

Hold the right mouse button, draw a sign, release. Signs are configured in the
editor (tray icon → "Gestures…"): draw a sample or type a direction code, for
example `D-R` — "down, then right".

## Features

- stroke recognition and a trail behind the cursor;
- actions: standard ones from a list (copy, paste, minimise the window and so
  on), keys, text, launching programs, commands, clicks, scrolling, window
  actions;
- a gesture editor with sample drawing;
- settings: the modifier button, the stroke threshold, the trail look,
  autostart, excluded programs;
- an update check once a day;
- a notification-area icon with pause and the log.

## Where settings live

Files are in `%APPDATA%\Glyphstroke\`: `settings.yaml` and the `gestures\` folder.
The format is shared with the Linux and macOS versions — a gesture set moves by
copying the folder.

## Build

You need the [.NET 8 SDK](https://dotnet.microsoft.com/download) and, for the
installer, [Inno Setup 6](https://jrsoftware.org/isdl.php).

```powershell
dotnet build src\Glyphstroke.App          # check that it builds
dotnet test tests\Glyphstroke.Core.Tests  # core tests
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

The last command builds the program, runs the tests and puts the installer into
`dist`. Without Inno Setup it stops at the ready folder — you can already run
that. The build is self-contained; .NET is not needed on the user's machine.

## Licence

PolyForm Noncommercial 1.0.0: free for non-commercial use, selling is not
allowed. Full text in the `LICENSE` file at the repository root.
