"""弹窗位置策略单测。"""

from __future__ import annotations

from copyama.core.placement import (
    Placement,
    clamp_to_screen,
    compute_position,
    screen_at_point,
)

SCREEN = (0, 0, 1920, 1080)
SIZE = (400, 500)


def test_cursor_offset():
    assert compute_position(
        Placement.CURSOR, SIZE, cursor=(100, 100), screen=SCREEN
    ) == (112, 112)


def test_cursor_clamped_at_bottom_right():
    x, y = compute_position(
        Placement.CURSOR, SIZE, cursor=(1900, 1070), screen=SCREEN
    )
    assert (x, y) == (1920 - 400, 1080 - 500)


def test_active_center():
    assert compute_position(Placement.ACTIVE_CENTER, SIZE, screen=SCREEN) == (760, 290)


def test_tray_places_above_icon():
    x, y = compute_position(
        Placement.TRAY, SIZE, tray=(1900, 1070), screen=SCREEN, margin=12
    )
    assert x == 1900 - 400 + 12
    assert y == 1070 - 500 - 12


def test_remember_and_fixed():
    assert compute_position(Placement.REMEMBER, SIZE, last=(300, 200), screen=SCREEN) == (300, 200)
    assert compute_position(Placement.FIXED, SIZE, fixed=(50, 60), screen=SCREEN) == (50, 60)


def test_missing_params_fall_back_to_center():
    assert compute_position(Placement.CURSOR, SIZE, screen=SCREEN) == (760, 290)


def test_clamp_when_window_larger_than_screen():
    assert clamp_to_screen(100, 100, (3000, 2000), SCREEN) == (0, 0)


def test_screen_at_point():
    second = (1920, 0, 1920, 1080)
    assert screen_at_point(100, 100, [SCREEN, second]) == SCREEN
    assert screen_at_point(2000, 100, [SCREEN, second]) == second
    # 落在屏幕外时回退到最近的屏
    assert screen_at_point(-500, 100, [SCREEN, second]) == SCREEN
