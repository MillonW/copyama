"""主题与配色方案：多方案、线条风、气泡差异化。"""

from copyama.ui.theme import (
    SCHEME_LABELS,
    SCHEMES,
    ColorScheme,
    ThemeMode,
    bubble_object_name,
    bubble_qss,
    build_qss,
    detect_system_mode,
    mode_from_str,
    palette_for,
    resolve_mode,
    scheme_choices,
    scheme_from_str,
    thumbnail_qss,
)


def test_every_scheme_has_light_and_dark():
    assert set(SCHEMES) == set(ColorScheme)
    for light, dark in SCHEMES.values():
        assert light.bg != dark.bg and light.text != dark.text
        assert light.line and dark.line_strong


def test_palette_for_picks_variant_and_falls_back():
    assert palette_for(ThemeMode.LIGHT, "nord") is SCHEMES[ColorScheme.NORD][0]
    assert palette_for(ThemeMode.DARK, ColorScheme.NORD) is SCHEMES[ColorScheme.NORD][1]
    # 未知方案名回退纯黑白，不抛异常
    assert palette_for(ThemeMode.LIGHT, "neon") is SCHEMES[ColorScheme.MONO][0]


def test_scheme_helpers_align():
    assert scheme_from_str("sakura") is ColorScheme.SAKURA
    assert scheme_from_str("bogus") is ColorScheme.MONO
    choices = scheme_choices()
    assert [v for v, _ in choices] == [s.value for s in ColorScheme]
    assert all(SCHEME_LABELS[s] for s in ColorScheme)


def test_mode_helpers_and_system_detection():
    assert mode_from_str("dark") is ThemeMode.DARK
    assert mode_from_str("whatever") is ThemeMode.SYSTEM
    assert resolve_mode(ThemeMode.LIGHT) is ThemeMode.LIGHT
    assert detect_system_mode() in (ThemeMode.LIGHT, ThemeMode.DARK)


def test_build_qss_uses_line_width_and_palette():
    palette = palette_for(ThemeMode.LIGHT, "graphite")
    qss = build_qss(palette, line_width=3, radius=8, font_size=14)
    assert "3px solid" in qss
    assert palette.line in qss
    assert "font-size: 14px" in qss
    assert "QLineEdit:focus" in qss


def test_bubble_object_name_is_unique_per_kind():
    kinds = ["link", "email", "image", "media", "archive", "path", "code", "number", "text"]
    names = [bubble_object_name(k) for k in kinds]
    assert len(set(names)) == len(kinds)
    assert bubble_object_name("nope") == "BubbleText"


def test_bubble_qss_shared_metrics_with_kind_specific_details():
    palette = palette_for(ThemeMode.DARK, "mono")
    qss = bubble_qss(palette, radius=12, font_size=13)
    for name in ("BubbleText", "BubbleCode", "BubbleLink", "BubbleImage",
                 "BubbleMedia", "BubbleArchive", "BubbleFile"):
        assert f"QPushButton#{name}" in qss
    # 统一：同一圆角与内边距
    assert "border-radius: 12px" in qss
    assert "padding: 4px 12px" in qss
    # 差异：代码块有底纹与等宽字体，图片/文件只有左色条不同
    assert palette.code_bg in qss
    assert "monospace" in qss
    assert "border-left: 2px solid" in qss


def test_thumbnail_qss_has_thumb_and_kind_tag():
    qss = thumbnail_qss(palette_for(ThemeMode.LIGHT, "ink"), radius=4)
    assert "QLabel#Thumb" in qss
    assert "QLabel#KindTag" in qss
    assert "QLabel#EmptyHint" in qss
