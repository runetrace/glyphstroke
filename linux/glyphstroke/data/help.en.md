# Glyphstroke — help

## How it works

The daemon takes the mouse for itself and forwards every event to the system.
The only thing it holds back is the press of the trigger button (the right one
by default): that press waits until you release it. If you simply clicked, the
click is delivered to the application — the context menu opens as usual. If you
drew a stroke, the click is never delivered and the bound action runs instead.

Capture happens at the kernel level, so it behaves the same in X11 and in
Wayland. Key presses go through the kernel as well, and in GNOME through the
shell extension, so that the keyboard layout does not get in the way.

## Installation and the first run

Nothing has to be set up by hand. The installer grants access to the mouse and
turns on autostart by itself, and the GNOME shell extension is put in place by
the daemon at its first run.

One step is left, and it cannot be avoided: log out and log back in. The
`input` group is picked up only at login, and GNOME loads extensions only when
a session starts.

The commands in this help are for those who prefer them. Everything needed
daily is in the editor: gestures, settings, pause, moving gestures as a file.

## Your first gesture

1. Open the editor: the Glyphstroke icon in the applications menu, or `glyphstroke gui`.
2. Press «＋» and give the gesture a name.
3. Draw a stroke on the canvas with the left button — it becomes a sample
   right away.
   Two or three samples are enough.
4. On the «Actions» tab choose what should happen.
5. Press «Save gesture». The settings of the program itself live behind
   the gear button in the header.

Drawing is optional: you can type a direction code instead, for example `D-R`,
which means «down, then right».

## What a gesture is made of

**Stroke samples.** What you draw is resampled to 64 points and compared by
shape. Size, position on the screen and a shaky hand make no difference.

**A direction code.** A string of octants: `R`, `DR`, `D`, `DL`, `L`, `UL`,
`U`, `UR`. Codes are compared with tolerance: one extra neighbouring octant
costs almost nothing, a jump across an octant breaks the match.

**Special gestures.** These are matched by a mouse event rather than a shape:

- `rocker-left` — click the left button while holding the right one;
- `rocker-right` — click the right button while holding the left one;
- `wheel-up`, `wheel-down` — the wheel while the trigger button is held.

The page does not scroll while this happens: the wheel event is taken by the
gesture.

## Actions

- `standard` — a standard action of the system by name: copy, paste, minimise
  the window and the rest of the list. There is nothing to memorise, and such a
  gesture moves to another system as it is: there the same action runs with
  that system's own keys.
- `keys` — a key combination: `ctrl+w`, `alt+Left`, several in a row.
- `command` — a shell command.
- `app` — launch an application: a path to a `.desktop` file or to a program.
- `window` — act on the window: `minimize`, `maximize`, `close`,
  `fullscreen`, `activate` and their opposites.
- `text` — type a string.
- `button` — click a mouse button, `scroll` — scroll the wheel.
- `delay` — a pause in milliseconds between actions.

The actions of one gesture run one after another.

## A menu under a gesture

A menu is an optional addition to a gesture. With no items nothing changes:
the gesture runs its own actions, just as before. As soon as the «Menu» tab
has at least one item, the same stroke opens a list at the cursor — one shape
instead of a dozen memorised ones.

While the menu is open the mouse belongs to it: the cursor stands still and
the choice follows the distance travelled — one step down per item. The wheel
walks the list as well. Release the left button and the chosen item runs, the
right one closes the menu, and it also closes by itself if the mouse stands
still for a few seconds.

The list is drawn by the shell extension, or by the trail window in X11. With
neither of them the menu does not open: the gesture simply runs its own
actions and says so in the log.

## Gestures for one application

The «Only in applications» field limits a gesture. Applications already known
are ticked behind the «Choose…» button, and a new one is caught with the
target: press the crosshair icon next to the field, drag it onto the window of
the program you want and release. The window class is remembered by itself,
there is nothing to type.

The same stroke can do different things in different programs — a gesture of
the application wins over a global one, and the global one works everywhere it
has no local rival.

The exclusion list in the settings is chosen the same way. In those
applications there is no capture at all: the right button behaves as if the
program did not exist.

All caught applications are gathered in the settings, in the «Applications»
group. That is also where they are removed: bindings to a removed application
are dropped, and a gesture left without any other application is switched off
so that it does not start working everywhere.

A caught application is compared with the whole window class. Expressions
typed into gesture files earlier are still matched against «window class |
title».

In GNOME on Wayland the active window and the window under the target are
reported to the daemon by the shell extension. Without it, per-application
gestures do not work there.

## Drawing on the touchpad

On a laptop a gesture can be drawn with a finger. Hold Super (the key with the
Windows logo) and move a finger across the touchpad: this is the same stroke
as with the right mouse button. Lift the finger or release the key and the
gesture fires.

The key is changed in the settings, in the «Touchpad» group: pick one from the
list or assign any key by pressing it. «Off» removes drawing on the touchpad
altogether.

The touchpad is not grabbed for this: the cursor follows the finger, and
two-finger scrolling and shell gestures work as usual. A two-finger touch does
not count as a stroke.

If a gesture has a menu, move a finger across it and lift the finger on the
item you want.

Super released after a stroke does not open the GNOME overview: the shell
extension takes care of that. In other desktops a released Super may open
their menu — assign another key there.

## Gesture sets

A set is all the gestures at once. While there is only one set, nothing
changes: the gestures stay where they were. As soon as a second one is
created, the editor shows a chooser above the list and «glyphstroke profile» starts
to work in the terminal.

    glyphstroke profile                 which sets exist and which one is current
    glyphstroke profile new games --copy  create one as a copy of the current set
    glyphstroke profile use games       switch the whole set
    glyphstroke profile use base        go back to the base set

Switching changes everything at once — the gestures and their actions. That
beats the per-application filter when the sets differ as a whole: an ordinary
one and one for games, say. The base set cannot be removed, and if the
directory of a set disappears, the program quietly falls back to the base one.

## Hints on the screen

- The name of the gesture that fired is shown on a small plate; the
  `show_gesture_name` setting turns it off.
- Hold the button without moving and a cheat sheet with the list of gestures
  appears. The delay is `hint_delay_ms`, zero disables it.
- The trail follows the cursor while you draw. In X11 the program draws it
  itself, in GNOME on Wayland the shell extension does. Its colour, width and
  opacity are set right in the editor settings, with a sample next to them.

## Pause

Capture can be released without stopping the service: `glyphstroke pause`,
`glyphstroke resume`, `glyphstroke toggle`. The switch in the editor settings and the icon in
the top panel do the same. While paused, the mouse is truly released.

There is also a «Turn off in fullscreen» setting. While the active window is
fullscreen — a game, a video, a presentation — the mouse is let go by itself,
and the capture comes back when you leave. If you pause or resume by hand, we
stop interfering until the next game. A fullscreen window is visible directly in
X11, sway and Hyprland, and in GNOME the shell extension reports it.

## Moving gestures around

`glyphstroke export FILE` puts every gesture into a single file, `glyphstroke import FILE`
loads them back; `--replace` makes an exact copy, `--with-settings` carries the
settings over too. In the editor these are the «Export to a file…» and «Load
from a file…» buttons.

## Updates

Once a day the program asks the releases page whether a newer version is out
and, if it is, says so with a bar in the editor and a line in `glyphstroke doctor`.
It does not update itself: mouse capture is not the place for a silent
replacement. Installing a new version is up to you, and the «Open the page»
button leads where it should.

The check is a request to somebody else's server, so it is visible and can be
turned off: in the editor settings, the «Program» group, or with
`check_updates: false` in `settings.yaml`. The «Check now» button is next to
it. Nothing about your system is sent, and the address of the releases page is
the `update_repo` setting.

## When something does not work

- `glyphstroke doctor` — permissions, devices, daemon version, code clashes.
- `glyphstroke update` — check for updates right now.
- `glyphstroke watch` — what is recognised right now and which action was sent.
- `journalctl --user -u glyphstroke -f` — the daemon log.
- The mouse stopped obeying: `systemctl --user stop glyphstroke` puts everything
  back.
- A gesture does not fire: most likely its code is claimed by a second gesture
  — `glyphstroke list` and `glyphstroke doctor` will say so.
