"""Меню под жестом: выбор пунктов и то, что оно не мешает жестам без меню."""

from __future__ import annotations

import types

import pytest

pytest.importorskip("evdev")

from evdev import ecodes  # noqa: E402

from glyphstroke.config import Action, Gesture, MenuItem, Settings  # noqa: E402
from glyphstroke.daemon import Daemon  # noqa: E402
from glyphstroke.menu import MenuChoice, MenuSession  # noqa: E402


def motion(dy: int):
    return types.SimpleNamespace(type=ecodes.EV_REL, code=ecodes.REL_Y, value=dy)


def wheel(value: int, code: int = ecodes.REL_WHEEL):
    return types.SimpleNamespace(type=ecodes.EV_REL, code=code, value=value)


def button(code: int, value: int):
    return types.SimpleNamespace(type=ecodes.EV_KEY, code=code, value=value)


def session(count: int = 3, **kwargs) -> MenuSession:
    items = [MenuItem(f"Пункт {i + 1}", [Action("keys", f"ctrl+{i + 1}")])
             for i in range(count)]
    return MenuSession("Меню", items, step_px=40.0, **kwargs)


# --- выбор пункта движением ---
def test_nothing_is_picked_until_the_mouse_leaves_the_dead_zone():
    menu = session()
    assert menu.handle(motion(10)) is None
    assert menu.index == -1


def test_each_step_down_moves_to_the_next_item():
    menu = session()
    menu.handle(motion(30))          # 20 — мёртвая зона, дальше шаг 40
    assert menu.index == 0
    menu.handle(motion(40))
    assert menu.index == 1
    menu.handle(motion(40))
    assert menu.index == 2


def test_below_the_last_item_the_highlight_stays_there():
    menu = session()
    menu.handle(motion(1000))
    assert menu.index == 2


def test_moving_up_deselects():
    """Выше места жеста — зона отмены: щёлкнув там, ничего не выполняем."""
    menu = session()
    menu.handle(motion(70))
    assert menu.index == 1
    assert menu.handle(motion(-200)) == "highlight"
    assert menu.index == -1


def test_the_same_item_does_not_repaint():
    menu = session()
    menu.handle(motion(30))
    assert menu.handle(motion(2)) is None, "подсветка не менялась — рисовать нечего"


def test_the_wheel_walks_the_items():
    menu = session()
    assert menu.handle(wheel(-1)) == "highlight"
    assert menu.index == 0
    menu.handle(wheel(-1))
    assert menu.index == 1
    menu.handle(wheel(1))
    assert menu.index == 0


def test_the_hi_res_wheel_does_not_count_twice():
    """Иначе один щелчок колеса перескакивал бы через пункт."""
    menu = session()
    menu.handle(wheel(-1))
    menu.handle(wheel(-120, code=11))
    assert menu.index == 0


def test_the_wheel_and_the_mouse_agree_afterwards():
    menu = session()
    menu.handle(wheel(-1))
    menu.handle(wheel(-1))           # второй пункт
    menu.handle(motion(40))          # шаг вниз — должен быть третий, а не первый
    assert menu.index == 2


# --- чем заканчивается ---
def test_the_left_button_picks_on_release():
    """Решение принимаем на отпускании: иначе оно осталось бы без пары."""
    menu = session()
    menu.handle(motion(30))
    assert menu.handle(button(ecodes.BTN_LEFT, 1)) is None
    assert menu.handle(button(ecodes.BTN_LEFT, 0)) == "choose"
    assert menu.chosen.name == "Пункт 1"


def test_the_right_button_cancels():
    menu = session()
    menu.handle(motion(30))
    menu.handle(button(ecodes.BTN_RIGHT, 1))
    assert menu.handle(button(ecodes.BTN_RIGHT, 0)) == "cancel"
    assert menu.chosen is None


def test_a_click_with_nothing_highlighted_cancels():
    menu = session()
    menu.handle(button(ecodes.BTN_LEFT, 1))
    assert menu.handle(button(ecodes.BTN_LEFT, 0)) == "cancel"
    assert menu.chosen is None


def test_a_finished_menu_ignores_the_rest():
    menu = session()
    menu.handle(button(ecodes.BTN_LEFT, 1))
    menu.handle(button(ecodes.BTN_LEFT, 0))
    assert menu.handle(motion(200)) is None


def test_a_still_mouse_closes_the_menu():
    """Без срока мышь можно было бы потерять в невидимом меню насовсем."""
    menu = session(timeout_ms=500)
    menu.last_activity -= 1.0
    assert menu.expired()
    menu.last_activity += 1.0
    assert not menu.expired()


def test_the_timeout_can_be_switched_off():
    menu = session(timeout_ms=0)
    menu.last_activity -= 3600
    assert not menu.expired()


# --- жест и демон ---
class FakeChannel:
    def __init__(self, capabilities=("menu",), listeners=1):
        self.capabilities = set(capabilities)
        self.listeners = listeners
        self.sent: list[str] = []

    def has(self, capability):
        return capability in self.capabilities

    def broadcast(self, line):
        self.sent.append(line)
        return self.listeners


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("GLYPHSTROKE_CONFIG_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def daemon():
    daemon = Daemon(Settings())
    daemon.overlay_server = FakeChannel()
    return daemon


def with_menu() -> Gesture:
    return Gesture(name="Правка", directions=["D"],
                   menu=[MenuItem("Копировать", [Action("keys", "ctrl+c")]),
                         MenuItem("Вставить", [Action("keys", "ctrl+v")])])


def test_a_gesture_without_a_menu_opens_nothing(daemon):
    """Главное обещание: жесты без меню работают ровно как раньше."""
    gesture = Gesture(name="Назад", directions=["L"], actions=[Action("keys", "alt+Left")])
    assert daemon.open_menu(gesture, None) is False
    assert daemon.menu is None
    assert not any(line.startswith("menu") for line in daemon.overlay_server.sent)


def test_the_menu_opens_when_there_is_someone_to_draw_it(daemon):
    assert daemon.open_menu(with_menu(), "gedit | текст") is True
    assert daemon.menu is not None
    assert daemon.overlay_server.sent == ["menu\tПравка\tКопировать\tВставить"]


def test_an_invisible_menu_is_not_opened(daemon):
    """Мышь ушла бы в невидимый список, и это выглядело бы как поломка."""
    daemon.overlay_server = FakeChannel(capabilities=["keys", "window"])
    assert daemon.open_menu(with_menu(), None) is False
    assert daemon.menu is None


def test_the_x11_trail_window_can_draw_it_too(daemon):
    daemon.overlay_server = FakeChannel(capabilities=[])
    daemon.overlay = types.SimpleNamespace(poll=lambda: None)
    assert daemon.can_draw_menu() is True


def test_a_dead_trail_window_does_not_count(daemon):
    daemon.overlay_server = FakeChannel(capabilities=[])
    daemon.overlay = types.SimpleNamespace(poll=lambda: 1)
    assert daemon.can_draw_menu() is False


def test_moving_the_mouse_repaints_the_highlight(daemon):
    daemon.open_menu(with_menu(), None)
    daemon.overlay_server.sent.clear()
    daemon.handle_menu_event(motion(200))
    assert daemon.overlay_server.sent == ["menu-select\t1"]


def test_picking_an_item_queues_its_actions(daemon):
    daemon.open_menu(with_menu(), "gedit | текст")
    daemon.handle_menu_event(motion(200))
    daemon.handle_menu_event(button(ecodes.BTN_LEFT, 1))
    daemon.handle_menu_event(button(ecodes.BTN_LEFT, 0))
    assert daemon.menu is None
    _machine, choice = daemon._work.get_nowait()
    assert isinstance(choice, MenuChoice)
    assert choice.item.name == "Вставить"
    assert choice.app == "gedit | текст", "действие должно уйти в то же окно"
    assert "menu-hide" in daemon.overlay_server.sent
    assert "menu-choice\tПравка\tВставить" in daemon.overlay_server.sent


def test_cancelling_runs_nothing(daemon):
    daemon.open_menu(with_menu(), None)
    daemon.handle_menu_event(motion(200))
    daemon.handle_menu_event(button(ecodes.BTN_RIGHT, 1))
    daemon.handle_menu_event(button(ecodes.BTN_RIGHT, 0))
    assert daemon.menu is None
    assert daemon._work.empty()
    assert "menu-choice\tПравка\t-" in daemon.overlay_server.sent


def test_the_gesture_runs_its_own_actions_and_then_opens_the_menu(daemon):
    gesture = with_menu()
    gesture.actions = [Action("keys", "ctrl+s")]
    performed = []
    daemon.perform = lambda name, actions, app: performed.append((name, actions))
    daemon.focus_target_window = lambda: None
    assert daemon.run_gesture(gesture, None) is True
    assert performed == [("Правка", gesture.actions)]
    assert daemon.menu is not None


def test_pausing_the_capture_closes_the_menu(daemon):
    daemon.open_menu(with_menu(), None)
    daemon.apply_pause(True)
    assert daemon.menu is None
    assert "menu-hide" in daemon.overlay_server.sent


def test_the_menu_item_is_named_together_with_the_gesture(daemon):
    performed = []
    daemon.perform = lambda name, actions, app: performed.append(name)
    daemon.focus_target_window = lambda: None
    daemon.run_menu_item(MenuChoice("Правка", MenuItem("Вставить"), None))
    assert performed == ["Правка → Вставить"]


# --- как это хранится ---
def test_the_menu_survives_a_round_trip(tmp_path):
    gesture = with_menu()
    gesture.save(tmp_path)
    from glyphstroke.config import load_gestures

    loaded = load_gestures(tmp_path)[0]
    assert [item.name for item in loaded.menu] == ["Копировать", "Вставить"]
    assert loaded.menu[0].actions[0].value == "ctrl+c"


def test_a_gesture_without_a_menu_gets_no_menu_key(tmp_path):
    """Пересохранение прежнего жеста не должно менять его файл."""
    gesture = Gesture(name="Назад", directions=["L"])
    assert "menu" not in gesture.to_dict()
    assert "menu" not in gesture.save(tmp_path).read_text(encoding="utf-8")


def test_items_without_a_name_are_dropped(tmp_path):
    gesture = Gesture(name="Правка", menu=[MenuItem("", [Action("keys", "ctrl+c")])])
    path = gesture.save(tmp_path)
    from glyphstroke.config import load_gestures

    assert load_gestures(tmp_path)[0].menu == []
    assert path.exists()
