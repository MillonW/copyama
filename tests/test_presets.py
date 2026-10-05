"""职业预设模板与设置项声明的单测。"""

from __future__ import annotations

import pytest

from copyama.config import Config
from copyama.core.presets import PRESETS, apply_preset, list_presets


def test_all_presets_field_names_exist():
    """每个模板覆盖的字段都必须真实存在于 Config，防止改名后静默失效。"""
    known = set(Config().__dataclass_fields__)
    for preset in PRESETS.values():
        unknown = set(preset.overrides) - known
        assert not unknown, f"{preset.key} 引用了未知字段：{unknown}"


def test_apply_preset_overrides_and_keeps_rest():
    config = Config()
    new = apply_preset(config, "programmer")
    assert new.max_items == 800
    assert new.theme == "dark"
    assert new.popup_position == "cursor"
    # 未被模板覆盖的字段保持原值
    assert new.font_size == config.font_size
    # 不修改入参
    assert config.max_items == 200


def test_apply_unknown_preset_returns_same_config():
    config = Config()
    assert apply_preset(config, "not-exist") == config


def test_list_presets_contains_general_first():
    presets = list_presets()
    assert presets[0].key == "general"
    assert len(presets) >= 8


def test_preset_choice_matches_config_field_type():
    """模板中的枚举型取值应与 Config 字段的既有取值域一致。"""
    allowed = {
        "theme": {"system", "light", "dark"},
        "popup_position": {
            "cursor", "active_center", "primary_center", "tray", "remember", "fixed",
        },
    }
    for preset in PRESETS.values():
        for key, choices in allowed.items():
            if key in preset.overrides:
                assert preset.overrides[key] in choices


def test_settings_specs_consistent_with_config():
    """设置界面声明的每一项都必须能在 Config 上找到，且默认值合法。"""
    from copyama.ui.settings_window import validate_specs

    assert validate_specs(Config()) == []


def test_autostart_requires_explicit_confirm():
    from copyama.core.autostart import AutostartManager

    manager = AutostartManager()
    with pytest.raises(PermissionError):
        manager.enable(confirm=False)
