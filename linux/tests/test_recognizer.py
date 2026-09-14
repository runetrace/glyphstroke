"""Проверки распознавания: коды направлений и сопоставление с шаблонами."""

import math

import pytest

from glyphstroke.recognizer import (
    GestureDef, Recognizer, direction_code, distance_at_best_angle,
    normalize, path_length, resample,
)


def line(x0, y0, x1, y1, n=40):
    return [(x0 + (x1 - x0) * i / (n - 1), y0 + (y1 - y0) * i / (n - 1))
            for i in range(n)]


def jitter(points, amount=1.5, seed=7):
    import random
    rnd = random.Random(seed)
    return [(x + rnd.uniform(-amount, amount), y + rnd.uniform(-amount, amount))
            for x, y in points]


# --- геометрия ---
def test_resample_gives_uniform_spacing():
    pts = resample(line(0, 0, 300, 0), 64)
    assert len(pts) == 64
    gaps = [math.dist(pts[i - 1], pts[i]) for i in range(1, 64)]
    assert max(gaps) - min(gaps) < 1e-6


def test_path_length_of_corner():
    assert path_length(line(0, 0, 0, 100) + line(0, 100, 100, 100)) == pytest.approx(200, abs=1)


# --- коды направлений ---
@pytest.mark.parametrize("stroke,expected", [
    (line(0, 0, 200, 0), "R"),
    (line(0, 0, -200, 0), "L"),
    (line(0, 0, 0, 200), "D"),
    (line(0, 0, 0, -200), "U"),
    (line(0, 0, 150, 150), "DR"),
    (line(0, 0, -150, 150), "DL"),
    (line(0, 0, 0, 200) + line(0, 200, 200, 200), "D-R"),
    (line(0, 0, 200, 0) + line(200, 0, 200, 200), "R-D"),
    (line(0, 0, 0, 200) + line(0, 200, -200, 200), "D-L"),
    (line(0, 0, 200, 0) + line(200, 0, 200, 200) + line(200, 200, 0, 200), "R-D-L"),
])
def test_direction_code(stroke, expected):
    assert direction_code(stroke) == expected


def test_direction_code_survives_shaky_hand():
    stroke = line(0, 0, 0, 200) + line(0, 200, 200, 200)
    assert direction_code(jitter(stroke, 3.0)) == "D-R"


def test_direction_code_is_scale_independent():
    small = line(0, 0, 0, 60) + line(0, 60, 60, 60)
    large = line(0, 0, 0, 900) + line(0, 900, 900, 900)
    assert direction_code(small) == direction_code(large) == "D-R"


def test_empty_stroke_has_no_code():
    assert direction_code([(5.0, 5.0)]) == ""


# --- шаблоны $1 ---
def test_template_matches_itself_exactly():
    template = normalize(line(0, 0, 200, 0) + line(200, 0, 200, 200))
    d = distance_at_best_angle(template, template, math.radians(20))
    assert d == pytest.approx(0.0, abs=1e-6)


def test_template_tolerates_size_and_shift():
    shape = line(0, 0, 100, 0) + line(100, 0, 100, 100)
    big = [(x * 3 + 500, y * 3 + 700) for x, y in shape]
    rec = Recognizer([GestureDef("угол", templates=[shape])])
    assert rec.recognize(big).name == "угол"


def test_direction_matters_for_templates():
    """Линия вправо не должна опознаться как линия вниз."""
    rec = Recognizer([GestureDef("вправо", templates=[line(0, 0, 200, 0)])])
    assert rec.recognize(line(0, 0, 200, 0)).name == "вправо"
    assert rec.recognize(line(0, 0, 0, 200)).name is None


def test_ambiguous_stroke_is_rejected():
    """Два почти одинаковых шаблона — лучше не сработать, чем ошибиться."""
    rec = Recognizer(
        [GestureDef("а", templates=[line(0, 0, 200, 0)]),
         GestureDef("б", templates=[line(0, 0, 200, 2)])],
        min_margin=0.05,
    )
    assert rec.recognize(line(0, 0, 200, 1)).name is None


def test_several_samples_of_one_gesture():
    shape = line(0, 0, 0, 150) + line(0, 150, 150, 150)
    g = GestureDef("угол", templates=[jitter(shape, 2, seed=s) for s in (1, 2, 3)])
    rec = Recognizer([g])
    assert rec.recognize(jitter(shape, 4, seed=9)).name == "угол"


def test_directions_and_templates_together():
    rec = Recognizer([
        GestureDef("вниз-вправо", directions=["D-R"]),
        GestureDef("галочка", templates=[line(0, 0, 60, 100) + line(60, 100, 200, -120)]),
    ])
    assert rec.recognize(line(0, 0, 0, 200) + line(0, 200, 200, 200)).name == "вниз-вправо"
    check = line(0, 0, 62, 104) + line(62, 104, 205, -118)
    assert rec.recognize(check).name == "галочка"


def test_unknown_stroke_returns_none():
    rec = Recognizer([GestureDef("вправо", directions=["R"])])
    match = rec.recognize(line(0, 0, -200, 0))
    assert match.name is None and match.code == "L"


# --- допуск при сверке кодов направлений ---
from glyphstroke.recognizer import direction_similarity, octant_distance  # noqa: E402


def test_octant_distance_wraps_around():
    assert octant_distance("R", "R") == 0
    assert octant_distance("R", "UR") == 1
    assert octant_distance("R", "L") == 4
    assert octant_distance("U", "UR") == 1


def test_identical_codes_match_exactly():
    assert direction_similarity("D-R", "D-R") == 1.0


@pytest.mark.parametrize("drawn,target", [
    ("L-DL", "L"),      # хвост линии увело вниз
    ("R-UR", "R"),      # и вверх
    ("D-DR-R", "D-R"),  # угол вышел скруглённым
    ("DR-D-R", "D-R"),  # начали чуть под углом
])
def test_shaky_hand_still_matches(drawn, target):
    assert direction_similarity(drawn, target) >= 0.80, \
        "нормальный росчерк не должен браковаться из-за дрожания"


@pytest.mark.parametrize("drawn,target", [
    ("D-R", "D"),       # угол — это не прямая линия
    ("U-L", "L"),
    ("R", "L"),         # противоположные направления
    ("D-R-D", "D-R"),
])
def test_different_shapes_do_not_match(drawn, target):
    assert direction_similarity(drawn, target) < 0.80


def test_diagonal_is_ambiguous_and_fires_nothing():
    """Ровно между «вправо» и «вниз» — лучше не угадывать."""
    rec = Recognizer([GestureDef("вправо", directions=["R"]),
                      GestureDef("вниз", directions=["D"])])
    diagonal = line(0, 0, 200, 200)
    match = rec.recognize(diagonal)
    assert match.name is None
    assert match.code == "DR"


def test_wobbly_stroke_fires_the_intended_gesture():
    rec = Recognizer([GestureDef("назад", directions=["L"]),
                      GestureDef("вниз", directions=["D"])])
    # ведём влево, к концу линию уводит вниз
    stroke = line(0, 0, -200, 0) + line(-200, 0, -260, 60)
    assert direction_similarity(direction_code(stroke), "L") >= 0.80
    assert rec.recognize(stroke).name == "назад"


def test_unrecognized_reports_the_closest_gesture():
    rec = Recognizer([GestureDef("вниз-вправо", directions=["D-R"])])
    match = rec.recognize(line(0, 0, 0, 200))
    assert match.name is None
    assert match.runner_up == "вниз-вправо", "нужно видеть, чего не хватило"


def test_two_gestures_with_one_code_cancel_each_other():
    """Так выглядит «жест не работает», если код занят дважды."""
    rec = Recognizer([GestureDef("Новая вкладка", directions=["U"]),
                      GestureDef("Копировать", directions=["U"])])
    match = rec.recognize(line(0, 0, 0, -200))
    assert match.name is None
    assert match.code == "U"
    assert {name for name, _ in rec.score_all(line(0, 0, 0, -200))} == {
        "Новая вкладка", "Копировать"}
