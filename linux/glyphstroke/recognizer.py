"""Распознавание росчерков.

Два независимых способа сопоставления, оба работают на одном и том же
списке точек, снятом с мыши:

* **Шаблоны** — алгоритм $1 Unistroke Recognizer (Wobbrock, Wilson, Li, 2007).
  Пользователь рисует жест несколько раз, каждый росчерк становится шаблоном.
  В отличие от канонического $1 поворот к «главной оси» отключён: для нас
  линия вправо и линия вниз — разные жесты, а не один повёрнутый.

* **Код направлений** — росчерк раскладывается в строку октантов вида
  ``D-R`` («вниз, потом вправо»). Такой жест можно задать текстом, не рисуя,
  поэтому им описан стартовый набор.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

Point = tuple[float, float]

# --- параметры $1 -----------------------------------------------------------
NUM_POINTS = 64
SQUARE_SIZE = 250.0
HALF_DIAGONAL = 0.5 * math.hypot(SQUARE_SIZE, SQUARE_SIZE)
PHI = 0.5 * (-1.0 + math.sqrt(5.0))
#: если росчерк вытянут сильнее, чем 1:4, масштабируем его равномерно —
#: иначе прямая линия растянулась бы в квадрат и потеряла форму
THIN_RATIO = 0.25

#: экранная система координат: X вправо, Y вниз
DIRECTIONS = ("R", "DR", "D", "DL", "L", "UL", "U", "UR")


# --- геометрия --------------------------------------------------------------
def path_length(points: list[Point]) -> float:
    return sum(
        math.dist(points[i - 1], points[i]) for i in range(1, len(points))
    )


def dedupe(points: list[Point], eps: float = 1e-9) -> list[Point]:
    out: list[Point] = []
    for p in points:
        if not out or math.dist(out[-1], p) > eps:
            out.append(p)
    return out


def resample(points: list[Point], n: int = NUM_POINTS) -> list[Point]:
    """Равномерно по длине пути разложить росчерк на ``n`` точек."""
    points = dedupe(points)
    if len(points) < 2:
        return [points[0] if points else (0.0, 0.0)] * n
    interval = path_length(points) / (n - 1)
    if interval <= 0:
        return [points[0]] * n
    out = [points[0]]
    accumulated = 0.0
    i = 1
    pts = list(points)
    while i < len(pts):
        d = math.dist(pts[i - 1], pts[i])
        if accumulated + d >= interval:
            t = (interval - accumulated) / d
            nx = pts[i - 1][0] + t * (pts[i][0] - pts[i - 1][0])
            ny = pts[i - 1][1] + t * (pts[i][1] - pts[i - 1][1])
            out.append((nx, ny))
            pts.insert(i, (nx, ny))
            accumulated = 0.0
        else:
            accumulated += d
        i += 1
    while len(out) < n:  # добираем хвост из-за накопленной ошибки float
        out.append(pts[-1])
    return out[:n]


def centroid(points: list[Point]) -> Point:
    return (
        sum(p[0] for p in points) / len(points),
        sum(p[1] for p in points) / len(points),
    )


def bounding_box(points: list[Point]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def rotate_by(points: list[Point], radians: float) -> list[Point]:
    cx, cy = centroid(points)
    cos, sin = math.cos(radians), math.sin(radians)
    return [
        (
            (p[0] - cx) * cos - (p[1] - cy) * sin + cx,
            (p[0] - cx) * sin + (p[1] - cy) * cos + cy,
        )
        for p in points
    ]


def scale_to_square(points: list[Point], size: float = SQUARE_SIZE) -> list[Point]:
    _x, _y, w, h = bounding_box(points)
    if w <= 0 and h <= 0:
        return list(points)
    thin = min(w, h) / max(w, h) < THIN_RATIO if max(w, h) > 0 else True
    if thin:
        # вытянутый росчерк (прямая, узкая дуга) — только равномерное сжатие
        k = size / max(w, h)
        return [(p[0] * k, p[1] * k) for p in points]
    return [(p[0] * size / w, p[1] * size / h) for p in points]


def translate_to_origin(points: list[Point]) -> list[Point]:
    cx, cy = centroid(points)
    return [(p[0] - cx, p[1] - cy) for p in points]


def normalize(points: list[Point], n: int = NUM_POINTS) -> list[Point]:
    """Привести росчерк к виду, пригодному для сравнения с шаблоном."""
    return translate_to_origin(scale_to_square(resample(points, n)))


def path_distance(a: list[Point], b: list[Point]) -> float:
    return sum(math.dist(p, q) for p, q in zip(a, b)) / len(a)


def distance_at_angle(points: list[Point], template: list[Point], angle: float) -> float:
    return path_distance(rotate_by(points, angle), template)


def distance_at_best_angle(
    points: list[Point],
    template: list[Point],
    tolerance: float,
    precision: float = math.radians(2.0),
) -> float:
    """Золотое сечение по углу в пределах ``±tolerance``.

    Допуск маленький (по умолчанию 20°): он гасит дрожание руки, но не
    позволяет спутать жест с его же поворотом на 90°.
    """
    straight = distance_at_angle(points, template, 0.0)
    if tolerance <= 0:
        return straight
    lo, hi = -tolerance, tolerance
    x1 = PHI * lo + (1.0 - PHI) * hi
    f1 = distance_at_angle(points, template, x1)
    x2 = (1.0 - PHI) * lo + PHI * hi
    f2 = distance_at_angle(points, template, x2)
    while abs(hi - lo) > precision:
        if f1 < f2:
            hi, x2, f2 = x2, x1, f1
            x1 = PHI * lo + (1.0 - PHI) * hi
            f1 = distance_at_angle(points, template, x1)
        else:
            lo, x1, f1 = x1, x2, f2
            x2 = (1.0 - PHI) * lo + PHI * hi
            f2 = distance_at_angle(points, template, x2)
    # угол 0 проверяем явно: поиск в него не попадает и слегка портит
    # оценку даже при точном совпадении росчерка с шаблоном
    return min(straight, f1, f2)


# --- код направлений --------------------------------------------------------
def _octant(dx: float, dy: float) -> str:
    angle = math.degrees(math.atan2(dy, dx)) % 360.0
    return DIRECTIONS[int((angle + 22.5) % 360.0 // 45.0)]


def direction_code(
    points: list[Point],
    step_ratio: float = 0.16,
    min_step_px: float = 12.0,
) -> str:
    """Разложить росчерк в строку октантов, например ``D-R`` или ``R-D-L``.

    Шаг дискретизации берётся от размера самого росчерка, поэтому код не
    зависит от того, крупно или мелко нарисован жест.
    """
    pts = dedupe(points)
    if len(pts) < 2:
        return ""
    total = path_length(pts)
    _x, _y, w, h = bounding_box(pts)
    step = max(min_step_px, step_ratio * max(math.hypot(w, h), total * 0.5))
    raw: list[str] = []
    anchor = pts[0]
    for p in pts[1:]:
        if math.dist(anchor, p) >= step:
            raw.append(_octant(p[0] - anchor[0], p[1] - anchor[1]))
            anchor = p
    if not raw:
        raw.append(_octant(pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1]))

    # схлопываем повторы, попутно считая длину каждой серии
    runs: list[list] = []
    for d in raw:
        if runs and runs[-1][0] == d:
            runs[-1][1] += 1
        else:
            runs.append([d, 1])

    # выкидываем одиночные октанты-«скругления» между двумя соседними
    cleaned: list[list] = []
    for i, (d, count) in enumerate(runs):
        if count == 1 and 0 < i < len(runs) - 1:
            prev_d, next_d = runs[i - 1][0], runs[i + 1][0]
            if _adjacent(prev_d, d) and _adjacent(d, next_d):
                continue
        if cleaned and cleaned[-1][0] == d:
            cleaned[-1][1] += count
        else:
            cleaned.append([d, count])
    return "-".join(d for d, _count in cleaned)


def octant_distance(a: str, b: str) -> int:
    """Насколько далеко друг от друга два направления, в октантах (0…4)."""
    i, j = DIRECTIONS.index(a), DIRECTIONS.index(b)
    return min((i - j) % 8, (j - i) % 8)


def _adjacent(a: str, b: str) -> bool:
    return octant_distance(a, b) == 1


#: во сколько обходится лишний октант: соседний с уже принятым — это дрожание
#: руки, а вот скачок через октант означает, что нарисовали другую фигуру
WOBBLE_COST = 0.35
EXTRA_COST = 1.0


def _skip_cost(sequence: list[str], index: int) -> float:
    neighbours = []
    if index > 0:
        neighbours.append(sequence[index - 1])
    if index < len(sequence) - 1:
        neighbours.append(sequence[index + 1])
    return WOBBLE_COST if any(_adjacent(sequence[index], n) for n in neighbours) \
        else EXTRA_COST


def direction_similarity(drawn: str, target: str) -> float:
    """Насколько нарисованный код похож на заданный, от 0 до 1.

    Строгое посимвольное сравнение бракует нормальные росчерки: рука уводит
    хвост линии, и вместо ``L`` получается ``L-DL``. Поэтому считаем
    расстояние редактирования, где замена стоит тем дороже, чем дальше
    направления друг от друга, а лишний соседний октант почти бесплатен.
    Неоднозначные случаи всё равно отсеет проверка отрыва от второго места.
    """
    if not drawn or not target:
        return 0.0
    a = [part for part in drawn.split("-") if part in DIRECTIONS]
    b = [part for part in target.split("-") if part in DIRECTIONS]
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    rows, cols = len(a), len(b)
    cost = [[0.0] * (cols + 1) for _unused in range(rows + 1)]
    for i in range(1, rows + 1):
        cost[i][0] = cost[i - 1][0] + _skip_cost(a, i - 1)
    for j in range(1, cols + 1):
        cost[0][j] = cost[0][j - 1] + _skip_cost(b, j - 1)
    for i in range(1, rows + 1):
        for j in range(1, cols + 1):
            substitute = cost[i - 1][j - 1] + octant_distance(a[i - 1], b[j - 1]) / 4.0
            drop = cost[i - 1][j] + _skip_cost(a, i - 1)
            add = cost[i][j - 1] + _skip_cost(b, j - 1)
            cost[i][j] = min(substitute, drop, add)
    return max(0.0, 1.0 - cost[rows][cols] / max(rows, cols))


# --- сопоставление ----------------------------------------------------------
@dataclass
class GestureDef:
    """Жест как его видит распознаватель (действия живут отдельно)."""

    name: str
    templates: list[list[Point]] = field(default_factory=list)
    directions: list[str] = field(default_factory=list)
    rotation_tolerance: float = math.radians(20.0)

    def normalized_templates(self) -> list[list[Point]]:
        if not hasattr(self, "_cache") or self._cache_src is not self.templates:
            self._cache = [normalize(t) for t in self.templates if len(t) >= 2]
            self._cache_src = self.templates
        return self._cache


@dataclass
class Match:
    name: str | None
    score: float
    code: str
    runner_up: str | None = None
    runner_up_score: float = 0.0


class Recognizer:
    def __init__(self, gestures: list[GestureDef], min_score: float = 0.80,
                 min_margin: float = 0.05):
        self.gestures = gestures
        self.min_score = min_score
        self.min_margin = min_margin

    def score_all(self, points: list[Point]) -> list[tuple[str, float]]:
        code = direction_code(points)
        candidate = normalize(points)
        scored: list[tuple[str, float]] = []
        for g in self.gestures:
            best = 0.0
            for wanted in g.directions:
                best = max(best, direction_similarity(code, wanted))
            for template in g.normalized_templates():
                d = distance_at_best_angle(candidate, template, g.rotation_tolerance)
                best = max(best, 1.0 - d / HALF_DIAGONAL)
            if best > 0:
                scored.append((g.name, best))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored

    def recognize(self, points: list[Point]) -> Match:
        code = direction_code(points)
        scored = self.score_all(points)
        if not scored:
            return Match(None, 0.0, code)
        name, score = scored[0]
        second, second_score = (scored[1] if len(scored) > 1 else (None, 0.0))
        if score < self.min_score:
            # ничего не подошло: показываем самого близкого, чтобы было видно,
            # чего не хватило
            return Match(None, score, code, name, score)
        if (score - second_score) < self.min_margin:
            return Match(None, score, code, second, second_score)
        return Match(name, score, code, second, second_score)
