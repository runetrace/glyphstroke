/*
 * След за курсором для glyphstroke.
 *
 * Демон слушает мышь на уровне ядра и объявляет в сокете начало и конец
 * росчерка. Рисовать линию из обычного приложения в Wayland нельзя: нет ни
 * глобальной позиции курсора, ни слоя поверх окон. У расширения оболочки
 * есть и то, и другое, поэтому вся отрисовка живёт здесь.
 */

import Cairo from 'gi://cairo';
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const FRAME_MS = 16;          // примерно 60 кадров в секунду
const MIN_STEP_PX = 2;        // мельче не запоминаем, чтобы не копить мусор
const RECONNECT_MS = 3000;    // демон может стартовать позже оболочки
// оболочка может узнать об отпускании Super позже демона
const OVERLAY_GRACE_MS = 500;
const FADE_MS = 220;
const MENU_GAP = 14;          // отступ списка от курсора
// выключенный перехват показываем красным значком — так же говорят о себе
// StrokeIt и Sensiva, и это понятно без чтения меню
const PAUSED_COLOUR = '#e0574d';
// активный перехват — фирменный синий (как у следа): без явного цвета
// оболочка красит символьный значок акцентом системы, а он бывает любым
const ACTIVE_COLOUR = '#4da3ff';
const MENU_ROW_STYLE = 'padding: 6px 14px; border-radius: 8px;';
const MENU_ROW_ACTIVE_STYLE = MENU_ROW_STYLE
    + 'background-color: rgba(77,163,255,0.85); color: #ffffff;';

/*
 * Расширение живёт отдельно от программы, поэтому и переводы у него свои.
 * Строк немного, целый каталог заводить незачем: исходные английские, рядом
 * таблица для других языков.
 */
const MESSAGES = {
    ru: {
        'Glyphstroke gestures': 'Жесты Glyphstroke',
        'Gesture capture': 'Перехват жестов',
        'Gesture editor…': 'Редактор жестов…',
        'daemon is not running': 'демон не запущен',
        'capture is on': 'перехват включён',
        'capture is paused': 'перехват приостановлен',
    },
};

function _(text) {
    const names = GLib.get_language_names();
    for (const name of names) {
        const code = name.split(/[_.@]/)[0];
        if (MESSAGES[code] && MESSAGES[code][text])
            return MESSAGES[code][text];
    }
    return text;
}

/*
 * Демон нажимает клавиши кодами через uinput, и композитор читает их через
 * текущую раскладку: при русской KEY_C превращается в «с», приложение не
 * узнаёт в этом Ctrl+C. Здесь мы шлём не код клавиши, а символ, поэтому
 * раскладка перестаёт что-либо значить.
 */
const MODIFIERS = {
    ctrl: 'Control_L', control: 'Control_L', lctrl: 'Control_L', rctrl: 'Control_R',
    alt: 'Alt_L', lalt: 'Alt_L', ralt: 'Alt_R', altgr: 'ISO_Level3_Shift',
    shift: 'Shift_L', lshift: 'Shift_L', rshift: 'Shift_R',
    super: 'Super_L', win: 'Super_L', meta: 'Super_L', cmd: 'Super_L',
};
const NAMED = {
    left: 'Left', right: 'Right', up: 'Up', down: 'Down',
    enter: 'Return', return: 'Return', esc: 'Escape', escape: 'Escape',
    tab: 'Tab', space: 'space', backspace: 'BackSpace',
    del: 'Delete', delete: 'Delete', ins: 'Insert', insert: 'Insert',
    home: 'Home', end: 'End', pgup: 'Page_Up', pageup: 'Page_Up',
    pgdn: 'Page_Down', pagedown: 'Page_Down',
    plus: 'plus', minus: 'minus', equal: 'equal',
    printscreen: 'Print', print: 'Print', menu: 'Menu',
};

function keyvalFor(token) {
    const low = token.toLowerCase();
    const name = MODIFIERS[low] ?? NAMED[low] ??
        (/^f\d{1,2}$/.test(low) ? low.toUpperCase() : null) ??
        (token.length === 1 ? token : token);
    return Clutter[`KEY_${name}`] ?? 0;
}

function parseColor(text) {
    let hex = (text || '').replace('#', '');
    if (hex.length === 3)
        hex = [...hex].map(c => c + c).join('');
    if (hex.length !== 6)
        return [0.30, 0.64, 1.0];
    const value = parseInt(hex, 16);
    return [(value >> 16 & 255) / 255, (value >> 8 & 255) / 255, (value & 255) / 255];
}

export default class GlyphstrokeTrail extends Extension {
    enable() {
        this._points = [];
        this._color = [0.30, 0.64, 1.0];
        this._width = 4;
        this._alpha = 1;
        this._opacity = 0.9;
        this._frameTimer = 0;
        this._fadeTimer = 0;
        this._reconnectTimer = 0;
        this._menu = null;
        this._menuRows = null;
        this._cancellable = new Gio.Cancellable();
        this._overlayHeld = false;
        this._overlayTimer = 0;
        this._patchOverview();

        this._area = new St.DrawingArea({
            reactive: false,
            can_focus: false,
            track_hover: false,
        });
        this._area.set_position(0, 0);
        this._area.set_size(global.stage.width, global.stage.height);
        this._repaintId = this._area.connect('repaint', area => this._repaint(area));
        // addTopChrome кладёт актёр поверх окон; affectsInputRegion false —
        // чтобы щелчки уходили в приложение под следом
        Main.layoutManager.addTopChrome(this._area, {affectsInputRegion: false});
        this._area.hide();

        this._focusId = global.display.connect('notify::focus-window',
            () => this._reportWindow(null));
        // в игре мышь должна принадлежать игре: демон отпустит её, если
        // включено «не мешать в полноэкранных»
        this._fullscreenId = global.display.connect('in-fullscreen-changed',
            () => this._reportFullscreen());
        this._stageId = global.stage.connect('notify::width', () => this._resize());
        this._stageHeightId = global.stage.connect('notify::height', () => this._resize());

        this._buildIndicator();
        this._connect();
    }

    disable() {
        this._stopTimers();
        this._unpatchOverview();
        this._cancellable?.cancel();
        this._cancellable = null;
        this._closeConnection();
        if (this._focusId) {
            global.display.disconnect(this._focusId);
            this._focusId = 0;
        }
        if (this._fullscreenId) {
            global.display.disconnect(this._fullscreenId);
            this._fullscreenId = 0;
        }
        if (this._stageId) {
            global.stage.disconnect(this._stageId);
            this._stageId = 0;
        }
        if (this._stageHeightId) {
            global.stage.disconnect(this._stageHeightId);
            this._stageHeightId = 0;
        }
        this._keyboard = null;
        this._gicon = null;
        this._target = null;
        this._hideHint();
        this._hideMenu();
        this._indicator?.destroy();
        this._indicator = null;
        this._switch = null;
        this._icon = null;
        this._statusItem = null;
        if (this._area) {
            if (this._repaintId) {
                this._area.disconnect(this._repaintId);
                this._repaintId = 0;
            }
            Main.layoutManager.removeChrome(this._area);
            this._area.destroy();
            this._area = null;
        }
        this._points = [];
    }

    _resize() {
        this._area?.set_size(global.stage.width, global.stage.height);
    }

    // --- значок в панели ---
    _buildIndicator() {
        this._indicator = new PanelMenu.Button(0.0, 'Glyphstroke', false);
        this._icon = new St.Icon({
            gicon: this._ownIcon(),
            style_class: 'system-status-icon',
        });
        this._indicator.add_child(this._icon);

        this._switch = new PopupMenu.PopupSwitchMenuItem(_('Gesture capture'), true);
        this._switch.connect('toggled', (item, active) => {
            this._send(active ? 'resume' : 'pause');
        });
        this._indicator.menu.addMenuItem(this._switch);
        this._indicator.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        const editor = new PopupMenu.PopupMenuItem(_('Gesture editor…'));
        editor.connect('activate', () => {
            try {
                GLib.spawn_command_line_async('glyphstroke gui');
            } catch (error) {
                logError(error, 'glyphstroke: не удалось открыть редактор');
            }
        });
        this._indicator.menu.addMenuItem(editor);

        this._statusItem = new PopupMenu.PopupMenuItem(_('daemon is not running'), {
            reactive: false,
        });
        this._indicator.menu.addMenuItem(this._statusItem);

        Main.panel.addToStatusArea('glyphstroke', this._indicator);
        this._setState(null);
    }

    _ownIcon() {
        /*
         * Свой значок лежит рядом с расширением: тема оболочки его не знает,
         * пока программа не установлена в систему. Имя кончается на
         * «-symbolic», поэтому оболочка красит его под свою тему.
         */
        if (this._gicon) {
            return this._gicon;
        }
        // Из .deb значок лежит в теме как «glyphstroke-symbolic»; именованный
        // символьный значок оболочка рисует и перекрашивает везде, включая OSD,
        // где файловый значок показывается не всегда. Без темы (установка из
        // исходников) — файл рядом с расширением.
        try {
            const theme = new St.IconTheme();
            if (theme.has_icon('glyphstroke-symbolic')) {
                this._gicon = new Gio.ThemedIcon({name: 'glyphstroke-symbolic'});
                return this._gicon;
            }
        } catch (error) {
            // St.IconTheme различается между версиями — тогда просто файл
        }
        this._gicon = Gio.icon_new_for_string(
            `${this.path}/icons/glyphstroke-symbolic.svg`);
        return this._gicon;
    }

    _setState(state) {
        // state: 'active' | 'paused' | null (демон не на связи)
        const connected = state !== null;
        const active = state === 'active';
        if (this._switch) {
            this._switch.setSensitive(connected);
            this._switch.setToggleState(active);
        }
        if (this._icon) {
            // значок один и тот же в любом состоянии: меняется только цвет,
            // иначе о выключенном перехвате приходится догадываться
            this._icon.gicon = this._ownIcon();
            this._icon.style = `color: ${active ? ACTIVE_COLOUR : PAUSED_COLOUR};`;
            this._icon.opacity = connected ? 255 : 110;
        }
        if (this._statusItem) {
            this._statusItem.label.text = !connected ? _('daemon is not running')
                : (active ? `${_('capture is on')} (${this._version ?? '?'})`
                    : _('capture is paused'));
        }
    }

    _send(command) {
        try {
            this._connection?.get_output_stream().write_all(`${command}\n`, null);
        } catch (error) {
            logError(error, `glyphstroke: команда «${command}» не ушла`);
        }
    }

    // --- связь с демоном ---
    _socketPath() {
        return GLib.build_filenamev([GLib.get_user_runtime_dir(), 'glyphstroke', 'overlay.sock']);
    }

    _connect() {
        const path = this._socketPath();
        if (!GLib.file_test(path, GLib.FileTest.EXISTS)) {
            this._scheduleReconnect();
            return;
        }
        try {
            const client = new Gio.SocketClient();
            this._connection = client.connect(new Gio.UnixSocketAddress({path}), null);
            this._stream = new Gio.DataInputStream({
                base_stream: this._connection.get_input_stream(),
            });
            // говорим демону, что умеем нажимать клавиши: он перестанет слать
            // их кодами через uinput и отдаст их нам
            this._connection.get_output_stream().write_all(
                'iam shell keys window focus menu fullscreen pick\n', null);
            this._reportWindow(null);
            this._readLine();
        } catch (error) {
            logError(error, 'glyphstroke: не удалось подключиться к демону');
            this._closeConnection();
            this._setState(null);
            this._scheduleReconnect();
        }
    }

    _readLine() {
        if (!this._stream)
            return;
        this._stream.read_line_async(GLib.PRIORITY_DEFAULT, this._cancellable, (stream, result) => {
            let line = null;
            try {
                [line] = stream.read_line_finish_utf8(result);
            } catch (error) {
                line = null;
            }
            if (line === null) {          // демон закрылся или перезапускается
                this._closeConnection();
                this._setState(null);
                this._scheduleReconnect();
                return;
            }
            this._handle(line.trim());
            this._readLine();
        });
    }

    _handle(line) {
        if (line.startsWith('hello\t')) {
            const parts = line.split('\t');
            this._version = parts[1];
            this._setState(parts[3] ?? 'active');
            return;
        }
        if (line.startsWith('state\t')) {
            this._setState(line.split('\t')[1]);
            return;
        }
        if (line.startsWith('dokeys\t')) {
            this._sendKeys(line.slice('dokeys\t'.length));
            return;
        }
        if (line.startsWith('notify\t')) {
            this._showName(line.slice('notify\t'.length));
            return;
        }
        if (line.startsWith('hint\t')) {
            this._showHint(line.slice('hint\t'.length));
            return;
        }
        if (line === 'hint-hide') {
            this._hideHint();
            return;
        }
        if (line.startsWith('menu\t')) {
            const parts = line.split('\t');
            this._showMenu(parts[1] ?? '', parts.slice(2));
            return;
        }
        if (line.startsWith('menu-select\t')) {
            this._selectMenu(parseInt(line.split('\t')[1], 10));
            return;
        }
        if (line === 'menu-hide') {
            this._hideMenu();
            return;
        }
        if (line.startsWith('dowindow\t')) {
            this._doWindow(line.slice('dowindow\t'.length).trim());
            return;
        }
        if (line === 'dofocus') {
            this._focusTarget();
            return;
        }
        if (line === 'dopick') {
            this._pickWindow();
            return;
        }
        if (line === 'overlay-key-hold') {
            this._holdOverlayKey();
            return;
        }
        if (line === 'overlay-key-free') {
            this._freeOverlayKey();
            return;
        }
        const [command, color, width, opacity] = line.split(/\s+/);
        if (command === 'begin')
            this._begin(color, width, opacity);
        else if (command === 'end' || command === 'quit')
            this._end();
    }

    // --- какое окно под курсором ---
    _reportWindow(win) {
        // В Wayland приложению не отдают ни активное окно, ни его класс,
        // поэтому единственный, кто может рассказать демону, над чем рисуют, —
        // это оболочка. Без этого жесты «только в таком-то приложении» и
        // список исключений там просто не работают.
        const target = win ?? global.display.focus_window;
        if (!target) {
            this._send('window\t-\t-');
            this._reportFullscreen();
            return;
        }
        const app = target.get_wm_class() ?? target.get_gtk_application_id() ?? '-';
        const title = (target.get_title() ?? '').replace(/[\t\n]/g, ' ');
        this._send(`window\t${app}\t${title}`);
        this._reportFullscreen();
    }

    _reportFullscreen() {
        const win = global.display.focus_window;
        let full = false;
        try {
            full = win ? win.is_fullscreen() : false;
        } catch (error) {
            full = false;
        }
        this._send(`fullscreen\t${full ? '1' : '0'}`);
    }

    // --- подсказки на экране ---
    _showName(name) {
        // штатный OSD оболочки: выглядит как регулятор громкости
        try {
            Main.osdWindowManager.show(-1, this._ownIcon(), name, null);
        } catch (error) {
            logError(error, 'glyphstroke: не показать название жеста');
        }
    }

    _monitorUnderPointer() {
        const [x, y] = global.get_pointer();
        return Main.layoutManager.monitors.find(
            m => x >= m.x && x < m.x + m.width && y >= m.y && y < m.y + m.height)
            ?? Main.layoutManager.primaryMonitor;
    }

    _showHint(payload) {
        this._hideHint();
        const items = payload.split('\t').filter(Boolean).map(x => x.split('|'));
        if (!items.length)
            return;
        const box = new St.BoxLayout({
            vertical: true,
            style: 'background-color: rgba(20,20,24,0.86); color: #f2f2f2; '
                 + 'padding: 18px 24px; border-radius: 14px; spacing: 6px; '
                 + 'border: 1px solid rgba(255,255,255,0.12);',
        });
        box.add_child(new St.Label({
            text: _('Glyphstroke gestures'),
            style: 'font-weight: bold; padding-bottom: 8px;',
        }));
        for (const [name, how] of items) {
            const row = new St.BoxLayout({style: 'spacing: 24px;'});
            row.add_child(new St.Label({text: name ?? '', x_expand: true}));
            row.add_child(new St.Label({
                text: how ?? '',
                style: 'color: #7fb2ff;',
            }));
            box.add_child(row);
        }
        Main.layoutManager.addTopChrome(box, {affectsInputRegion: false});
        const monitor = this._monitorUnderPointer();
        const [, width] = box.get_preferred_width(-1);
        const [, height] = box.get_preferred_height(width);
        box.set_position(
            monitor.x + Math.floor((monitor.width - width) / 2),
            monitor.y + Math.floor((monitor.height - height) / 2));
        box.opacity = 0;
        box.ease({opacity: 255, duration: 120,
                  mode: Clutter.AnimationMode.EASE_OUT_QUAD});
        this._hint = box;
    }

    _hideHint() {
        if (!this._hint)
            return;
        const box = this._hint;
        this._hint = null;
        box.ease({
            opacity: 0,
            duration: 120,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            onComplete: () => {
                Main.layoutManager.removeChrome(box);
                box.destroy();
            },
        });
    }

    // --- меню под жестом ---
    _showMenu(title, items) {
        this._hideMenu();
        if (!items.length)
            return;
        const box = new St.BoxLayout({
            vertical: true,
            style: 'background-color: rgba(20,20,24,0.92); color: #f2f2f2; '
                 + 'padding: 10px; border-radius: 14px; '
                 + 'border: 1px solid rgba(255,255,255,0.12);',
        });
        if (title) {
            box.add_child(new St.Label({
                text: title,
                style: 'color: #9fbaf0; font-weight: bold; padding: 4px 14px 8px 14px;',
            }));
        }
        this._menuRows = items.map(text => {
            const row = new St.Label({text, style: MENU_ROW_STYLE});
            box.add_child(row);
            return row;
        });
        Main.layoutManager.addTopChrome(box, {affectsInputRegion: false});

        // курсор во время меню стоит на месте — демон не пускает его никуда,
        // поэтому место запоминаем один раз, при открытии
        const [px, py] = global.get_pointer();
        const monitor = this._monitorUnderPointer();
        const [, width] = box.get_preferred_width(-1);
        const [, height] = box.get_preferred_height(width);
        const x = Math.min(Math.max(monitor.x + 8, px - Math.floor(width / 2)),
                           monitor.x + monitor.width - width - 8);
        let y = py + MENU_GAP;
        if (y + height > monitor.y + monitor.height - 8)
            y = Math.max(monitor.y + 8, py - MENU_GAP - height);
        box.set_position(x, y);
        box.opacity = 0;
        box.ease({opacity: 255, duration: 100,
                  mode: Clutter.AnimationMode.EASE_OUT_QUAD});
        this._menu = box;
    }

    _selectMenu(index) {
        if (!this._menuRows)
            return;
        this._menuRows.forEach((row, i) => {
            row.style = i === index ? MENU_ROW_ACTIVE_STYLE : MENU_ROW_STYLE;
        });
    }

    _hideMenu() {
        this._menuRows = null;
        if (!this._menu)
            return;
        const box = this._menu;
        this._menu = null;
        Main.layoutManager.removeChrome(box);
        box.destroy();
    }

    // --- окна ---
    _windowUnderPointer() {
        const [x, y] = global.get_pointer();
        const actors = global.get_window_actors();
        for (let i = actors.length - 1; i >= 0; i--) {   // сверху вниз по стопке
            const win = actors[i].meta_window;
            if (!win || win.minimized)
                continue;
            const type = win.get_window_type();
            if (type !== Meta.WindowType.NORMAL && type !== Meta.WindowType.DIALOG)
                continue;
            const rect = win.get_frame_rect();
            if (x >= rect.x && x < rect.x + rect.width &&
                y >= rect.y && y < rect.y + rect.height)
                return win;
        }
        return null;
    }

    _targetWindow() {
        // окно, запомненное при нажатии, могло уже закрыться
        if (this._target && this._target.get_compositor_private())
            return this._target;
        return this._windowUnderPointer() ?? global.display.focus_window;
    }

    _focusTarget() {
        const win = this._targetWindow();
        if (win && win !== global.display.focus_window)
            win.activate(global.get_current_time());
    }

    _pickWindow() {
        // мишень из редактора: окно под курсором в миг, когда её отпустили.
        // Класс и название кодируются, потому что демон делит строку по пробелам
        const win = this._windowUnderPointer();
        const wmClass = win
            ? (win.get_wm_class() ?? win.get_gtk_application_id() ?? '') : '';
        if (!wmClass) {
            this._send('picked - nowindow');
            return;
        }
        let name = '';
        try {
            name = Shell.WindowTracker.get_default().get_window_app(win)?.get_name() ?? '';
        } catch (error) {
            name = '';
        }
        this._send(`picked ${encodeURIComponent(wmClass)} ${encodeURIComponent(name || wmClass)}`);
    }

    // --- Super, занятый росчерком по тачпаду ---
    _patchOverview() {
        // Одиночный Super оболочка ловит при отпускании и открывает обзор.
        // Когда Super зажимали ради росчерка по тачпаду, это лишнее: демон
        // говорит об этом заранее, и одно такое открытие мы пропускаем
        const overview = Main.overview;
        const original = overview.toggle;
        this._ownToggle = Object.prototype.hasOwnProperty.call(overview, 'toggle');
        this._originalToggle = original;
        overview.toggle = (...args) => {
            if (this._overlayHeld) {
                this._overlayHeld = false;
                return undefined;
            }
            return original.apply(overview, args);
        };
    }

    _unpatchOverview() {
        if (this._originalToggle) {
            if (this._ownToggle)
                Main.overview.toggle = this._originalToggle;
            else
                delete Main.overview.toggle;
            this._originalToggle = null;
        }
        if (this._overlayTimer) {
            GLib.source_remove(this._overlayTimer);
            this._overlayTimer = 0;
        }
        this._overlayHeld = false;
    }

    _holdOverlayKey() {
        if (this._overlayTimer) {
            GLib.source_remove(this._overlayTimer);
            this._overlayTimer = 0;
        }
        this._overlayHeld = true;
    }

    _freeOverlayKey() {
        if (this._overlayTimer)
            GLib.source_remove(this._overlayTimer);
        this._overlayTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, OVERLAY_GRACE_MS, () => {
            this._overlayTimer = 0;
            this._overlayHeld = false;
            return GLib.SOURCE_REMOVE;
        });
    }

    _doWindow(command) {
        const win = this._targetWindow();
        if (!win)
            return;
        const time = global.get_current_time();
        try {
            switch (command) {
            case 'minimize':
                win.minimize();
                break;
            case 'maximize':
                win.maximize(Meta.MaximizeFlags.BOTH);
                break;
            case 'unmaximize':
                win.unmaximize(Meta.MaximizeFlags.BOTH);
                break;
            case 'close':
                win.delete(time);
                break;
            case 'fullscreen':
                win.make_fullscreen();
                break;
            case 'unfullscreen':
                win.unmake_fullscreen();
                break;
            case 'activate':
                win.activate(time);
                break;
            case 'above':
                win.make_above();
                break;
            case 'unabove':
                win.unmake_above();
                break;
            default:
                log(`glyphstroke: неизвестное действие над окном: ${command}`);
            }
        } catch (error) {
            logError(error, `glyphstroke: не вышло выполнить «${command}»`);
        }
    }

    // --- нажатие клавиш вместо демона ---
    _virtualKeyboard() {
        if (!this._keyboard) {
            const seat = Clutter.get_default_backend().get_default_seat();
            this._keyboard = seat.create_virtual_device(
                Clutter.InputDeviceType.KEYBOARD_DEVICE);
        }
        return this._keyboard;
    }

    _sendKeys(text) {
        let device;
        try {
            device = this._virtualKeyboard();
        } catch (error) {
            logError(error, 'glyphstroke: не удалось создать устройство ввода');
            return;
        }
        for (const combo of text.trim().split(/\s+/).filter(Boolean)) {
            const mods = [];
            const keys = [];
            for (const token of combo.replace(/-/g, '+').split('+')) {
                if (!token)
                    continue;
                const keyval = keyvalFor(token);
                if (!keyval)
                    continue;
                if (MODIFIERS[token.toLowerCase()])
                    mods.push(keyval);
                else
                    keys.push(keyval);
            }
            if (!mods.length && !keys.length)
                continue;
            const time = global.get_current_time() * 1000;
            for (const keyval of mods)
                device.notify_keyval(time, keyval, Clutter.KeyState.PRESSED);
            for (const keyval of keys) {
                device.notify_keyval(time, keyval, Clutter.KeyState.PRESSED);
                device.notify_keyval(time, keyval, Clutter.KeyState.RELEASED);
            }
            for (const keyval of mods.reverse())
                device.notify_keyval(time, keyval, Clutter.KeyState.RELEASED);
        }
    }

    _scheduleReconnect() {
        if (this._reconnectTimer)
            return;
        this._reconnectTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, RECONNECT_MS, () => {
            this._reconnectTimer = 0;
            this._connect();
            return GLib.SOURCE_REMOVE;
        });
    }

    _closeConnection() {
        this._stream = null;
        try {
            this._connection?.close(null);
        } catch (error) {
            // соединение уже мертво — ничего страшного
        }
        this._connection = null;
    }

    // --- рисование ---
    _begin(color, width, opacity) {
        this._stopFade();
        // запоминаем окно под курсором сразу: к концу росчерка курсор может
        // оказаться уже над другим окном или вовсе на другом экране
        this._target = this._windowUnderPointer();
        this._reportWindow(this._target);
        this._points = [];
        this._alpha = 1;
        this._color = parseColor(color);
        this._width = Math.max(1, parseInt(width, 10) || 4);
        const parsed = parseFloat(opacity);
        // старый демон третьего поля не шлёт — тогда рисуем почти непрозрачно
        this._opacity = Number.isFinite(parsed) ? Math.min(1, Math.max(0.05, parsed)) : 0.9;
        if (!this._frameTimer) {
            this._frameTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, FRAME_MS,
                () => this._frame());
        }
    }

    _frame() {
        const [x, y] = global.get_pointer();
        const last = this._points.at(-1);
        if (!last || Math.max(Math.abs(x - last[0]), Math.abs(y - last[1])) >= MIN_STEP_PX) {
            this._points.push([x, y]);
            // окно поднимаем только когда курсор поехал: на обычном щелчке
            // мелькать ничего не должно
            if (this._points.length >= 2) {
                this._area.show();
                this._area.queue_repaint();
            }
        }
        return GLib.SOURCE_CONTINUE;
    }

    _end() {
        if (this._frameTimer) {
            GLib.source_remove(this._frameTimer);
            this._frameTimer = 0;
        }
        if (!this._area || !this._area.visible) {
            this._points = [];
            return;
        }
        const step = FRAME_MS / FADE_MS;
        this._fadeTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, FRAME_MS, () => {
            this._alpha -= step;
            if (this._alpha <= 0) {
                this._fadeTimer = 0;
                this._points = [];
                this._alpha = 1;
                this._area?.hide();
                return GLib.SOURCE_REMOVE;
            }
            this._area?.queue_repaint();
            return GLib.SOURCE_CONTINUE;
        });
    }

    _stopFade() {
        if (this._fadeTimer) {
            GLib.source_remove(this._fadeTimer);
            this._fadeTimer = 0;
        }
    }

    _stopTimers() {
        this._stopFade();
        if (this._frameTimer) {
            GLib.source_remove(this._frameTimer);
            this._frameTimer = 0;
        }
        if (this._reconnectTimer) {
            GLib.source_remove(this._reconnectTimer);
            this._reconnectTimer = 0;
        }
    }

    _repaint(area) {
        const cr = area.get_context();
        if (this._points.length >= 2) {
            const [r, g, b] = this._color;
            cr.setLineWidth(this._width);
            cr.setLineCap(Cairo.LineCap.ROUND);
            cr.setLineJoin(Cairo.LineJoin.ROUND);
            cr.setSourceRGBA(r, g, b, this._alpha * (this._opacity ?? 0.9));
            cr.moveTo(this._points[0][0], this._points[0][1]);
            for (const [x, y] of this._points.slice(1))
                cr.lineTo(x, y);
            cr.stroke();
        }
        cr.$dispose();
    }
}
