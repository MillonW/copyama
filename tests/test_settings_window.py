"""设置界面：类型转换纯逻辑 + 控件装配与数据流（离屏运行）。"""

from __future__ import annotations

import json

import pytest
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLineEdit, QSpinBox

from copyama.config import Config
from copyama.ui.settings_window import (
    TABS,
    SettingSpec,
    SettingsWindow,
    coerce_value,
    dump_value,
    validate_specs,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def spec_for(key: str) -> SettingSpec:
    for specs in TABS.values():
        for spec in specs:
            if spec.key == key:
                return spec
    raise KeyError(key)


ALL_KEYS = {spec.key for specs in TABS.values() for spec in specs}


class TestCoerceValue:
    def test_bool(self):
        assert coerce_value(spec_for("capture_text"), True) is True
        assert coerce_value(spec_for("capture_text"), 0) is False

    def test_int_clamped_and_cast(self):
        spec = spec_for("max_items")
        assert coerce_value(spec, 10**9) == spec.maximum
        assert coerce_value(spec, 1) == spec.minimum
        assert coerce_value(spec, "123") == 123

    def test_choice_must_be_known(self):
        assert coerce_value(spec_for("theme"), "dark") == "dark"
        with pytest.raises(ValueError):
            coerce_value(spec_for("theme"), "neon")

    def test_list_parsing(self):
        assert coerce_value(spec_for("blacklist"), '["a.exe"]') == ["a.exe"]
        with pytest.raises(ValueError):
            coerce_value(spec_for("blacklist"), '{"a": 1}')

    def test_plain_string(self):
        assert coerce_value(spec_for("font_family"), "Arial") == "Arial"


class TestDumpValue:
    def test_list_as_json(self):
        assert json.loads(dump_value(spec_for("fixed_position"), [1, 2])) == [1, 2]

    def test_none_becomes_empty(self):
        assert dump_value(spec_for("font_family"), None) == ""


class TestSpecsConsistency:
    def test_all_specs_valid(self):
        assert validate_specs() == []

    def test_every_config_field_has_spec(self):
        """反向校验：所有可配置字段都应在界面上暴露出来。"""
        without_spec = {"autostart_asked", "first_run_done"}
        expected = set(Config().__dataclass_fields__) - without_spec
        assert expected <= ALL_KEYS


class TestSettingsWindow:
    def test_builds_editor_for_every_spec(self, qapp):
        win = SettingsWindow(Config(), lambda cfg: None)
        assert set(win._editors) == ALL_KEYS
        win.deleteLater()

    def test_editor_types_match_kind(self, qapp):
        win = SettingsWindow(Config(), lambda cfg: None)
        assert isinstance(win._editors["capture_text"], QCheckBox)
        assert isinstance(win._editors["max_items"], QSpinBox)
        assert isinstance(win._editors["theme"], QComboBox)
        assert isinstance(win._editors["font_family"], QLineEdit)
        assert isinstance(win._editors["fixed_position"], QLineEdit)

    def test_collect_roundtrip(self, qapp):
        cfg = Config()
        values = SettingsWindow(cfg, lambda c: None).collect()
        assert values["max_items"] == cfg.max_items
        assert values["theme"] == cfg.theme
        assert values["capture_text"] == cfg.capture_text
        assert values["fixed_position"] == cfg.fixed_position

    def test_apply_writes_config_and_calls_back(self, qapp):
        cfg = Config()
        got = []
        win = SettingsWindow(cfg, got.append)
        win._editors["max_items"].setValue(321)
        win._editors["capture_text"].setChecked(False)
        problems = win.apply()

        assert got and got[0] is cfg
        assert cfg.max_items == 321
        assert cfg.capture_text is False
        assert isinstance(problems, list)

    def test_apply_surfaces_hotkey_problem(self, qapp):
        cfg = Config(hotkey="Ctrl+Alt+V")  # 该组合与录屏工具冲突，应产生提示
        win = SettingsWindow(cfg, lambda c: None)
        problems = win.apply()
        assert any("冲突" in p or "占用" in p for p in problems)

    def test_reset_to_defaults(self, qapp):
        win = SettingsWindow(Config(max_items=999, theme="dark"), lambda c: None)
        win.reset_to_defaults()
        values = win.collect()
        assert values["max_items"] == Config().max_items
        assert values["theme"] == Config().theme
