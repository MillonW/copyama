"""设置项声明：与 Config 对齐、覆盖本次新增配置。"""

from copyama.config import Config
from copyama.ui.settings_window import SCHEME_VALUES, TABS, tab_specs, validate_specs
from copyama.ui.theme import ColorScheme


def test_specs_match_config_fields():
    assert validate_specs() == []


def test_defaults_satisfy_spec_bounds():
    cfg = Config()
    for tab, specs in TABS.items():
        for spec in specs:
            value = getattr(cfg, spec.key)
            if spec.kind == "int":
                assert spec.minimum is not None and spec.maximum is not None, spec.key
                assert spec.minimum <= value <= spec.maximum, f"[{tab}] {spec.key}"
            elif spec.kind == "choice":
                assert value in spec.choices, f"[{tab}] {spec.key}"


def test_new_requirements_have_settings_entries():
    keys = {spec.key for specs in TABS.values() for spec in specs}
    for key in (
        "max_age_days", "date_grouping", "group_mode", "page_size",
        "purge_interval_minutes", "color_scheme", "line_width",
        "thumb_max_px", "thumb_format", "blob_quota_mb", "vacuum_on_start",
    ):
        assert key in keys, key


def test_default_capacity_is_200():
    assert Config().max_items == 200
    assert Config().max_age_days == 7
    assert Config().date_grouping is True


def test_scheme_values_align_with_theme():
    assert SCHEME_VALUES == tuple(s.value for s in ColorScheme)


def test_tab_specs_helper():
    assert tab_specs("general") == TABS["general"]
    assert tab_specs("no-such-tab") == []
