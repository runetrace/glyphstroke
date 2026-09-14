"""Меню под жестом: одна фигура вместо десятка запомненных росчерков.

Меню — необязательная добавка. У жеста без пунктов ничего не меняется: он
выполняет свои действия и никакого списка не показывает.

Пока меню открыто, мышь принадлежит ему: демон не пересылает в систему ни
движений, ни щелчков. Поэтому курсор стоит на месте, а выбор считается по
пройденному пути — вниз на шаг за пункт. Так рисующему меню остаётся только
рисовать: подсветку задаёт демон, и картинка не может разойтись с тем, что
он на самом деле выберет.

Выбор подтверждается отпусканием левой кнопки, отменяется любой другой и
пропадает сам, если мышь замерла надолго, — потерять её насовсем нельзя.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from evdev import ecodes

from .config import MenuItem

#: колесо высокого разрешения — эти отсчёты идут вдобавок к обычным щелчкам
#: колеса, и без пропуска пункт перескакивал бы через один
HI_RES_WHEEL = (11, 12)

#: наименьший разумный шаг: меньше — и пункт меняется от дрожания руки
MIN_STEP_PX = 8.0

#: сколько пути мыши даёт миллиметр по тачпаду: шаг меню в 36 точек
#: укладывается в шесть миллиметров, это удобно пальцу
TOUCH_PX_PER_MM = 6.0


@dataclass
class MenuChoice:
    """Что выбрано в меню — уходит в очередь выполнения действий."""

    gesture: str
    item: MenuItem
    app: str | None = None


@dataclass
class MenuSession:
    """Открытое меню: копит движение мыши и решает, что выбрано."""

    name: str
    items: list[MenuItem]
    step_px: float = 36.0
    timeout_ms: int = 5000
    app: str | None = None
    index: int = -1
    dy: float = 0.0
    chosen: MenuItem | None = None
    finished: bool = False
    #: какую кнопку сейчас держат: решение принимаем на отпускании, иначе
    #: отпускание досталось бы приложению отдельно от нажатия
    pressed: int | None = None
    #: где лежал палец на тачпаде в прошлый раз; None — касание только началось
    touch_y: float | None = None
    started: float = field(default_factory=time.monotonic)
    last_activity: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        self.step_px = max(MIN_STEP_PX, float(self.step_px))

    @property
    def dead_px(self) -> float:
        """Пока не отошли от места жеста, не выбрано ничего."""
        return self.step_px / 2

    @property
    def labels(self) -> list[str]:
        return [item.name for item in self.items]

    # --- разбор событий ---
    def handle(self, event) -> str | None:
        """Событие мыши → что делать: ``highlight``, ``choose``, ``cancel``.

        ``None`` — снаружи делать нечего. Событие в любом случае считается
        съеденным: до системы во время меню не доходит ничего.
        """
        if self.finished:
            return None
        self.last_activity = time.monotonic()

        if event.type == ecodes.EV_REL:
            if event.code == ecodes.REL_Y:
                self.dy += event.value
                return self._move_to(self._index_for(self.dy))
            if event.code in HI_RES_WHEEL:
                return None
            if event.code == ecodes.REL_WHEEL and event.value:
                # колесом ходим по пунктам: вверх — к началу списка
                return self._step(-1 if event.value > 0 else 1)
            return None

        if event.type == ecodes.EV_KEY and event.value == 1:
            if self.pressed is None:
                self.pressed = event.code
            return None

        if event.type == ecodes.EV_KEY and event.value == 0 \
                and event.code == self.pressed:
            self.pressed = None
            self.finished = True
            if event.code == ecodes.BTN_LEFT and 0 <= self.index < len(self.items):
                self.chosen = self.items[self.index]
                return "choose"
            return "cancel"
        return None

    def handle_touch(self, event, units_per_mm: float) -> str | None:
        """Тачпад: палец ведёт по списку, отрыв пальца выбирает подсвеченное.

        Тачпад не захвачен, поэтому щелчок по нему достался бы и приложению под
        курсором — выбор отрывом пальца обходится без щелчка. Отрыв, когда
        ничего не подсвечено, меню не закрывает: палец могли просто переставить.
        """
        if self.finished:
            return None
        if event.type == ecodes.EV_ABS and event.code == ecodes.ABS_Y:
            self.last_activity = time.monotonic()
            previous, self.touch_y = self.touch_y, float(event.value)
            if previous is None:
                return None
            self.dy += (event.value - previous) * TOUCH_PX_PER_MM / max(units_per_mm, 1.0)
            return self._move_to(self._index_for(self.dy))
        if event.type == ecodes.EV_KEY and event.code == ecodes.BTN_TOUCH:
            self.last_activity = time.monotonic()
            self.touch_y = None
            if event.value == 0 and 0 <= self.index < len(self.items):
                self.finished = True
                self.chosen = self.items[self.index]
                return "choose"
        return None

    def _index_for(self, dy: float) -> int:
        if dy <= self.dead_px:
            return -1
        return min(len(self.items) - 1, int((dy - self.dead_px) // self.step_px))

    def _move_to(self, index: int) -> str | None:
        if index == self.index:
            return None
        self.index = index
        return "highlight"

    def _step(self, delta: int) -> str | None:
        index = max(-1, min(len(self.items) - 1, self.index + delta))
        # путь подтягиваем к новому пункту, иначе следующее же движение мыши
        # вернуло бы подсветку туда, где она была до колеса
        self.dy = 0.0 if index < 0 else self.dead_px + self.step_px * index + 1
        return self._move_to(index)

    def expired(self, now: float | None = None) -> bool:
        if not self.timeout_ms:
            return False
        now = time.monotonic() if now is None else now
        return (now - self.last_activity) * 1000 >= self.timeout_ms

    def cancel(self) -> None:
        self.finished = True
        self.chosen = None
