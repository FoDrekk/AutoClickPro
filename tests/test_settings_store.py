import json

import pytest

from autoclick_pro.settings_store import (
    PROFILE_DEFAULTS,
    SCHEMA_VERSION,
    SETTINGS_DEFAULTS,
    SettingsStore,
    sanitize_profile,
    sanitize_settings,
    validate_profile_name,
)


@pytest.fixture
def path(tmp_path):
    return tmp_path / "sub" / "settings.json"


def test_missing_file_gives_defaults(path):
    store = SettingsStore.load(path)
    assert store.settings == SETTINGS_DEFAULTS
    assert store.profiles == {}
    assert store.load_warning is None
    assert not path.exists()


def test_round_trip(path):
    store = SettingsStore.load(path)
    store.update_settings({"interval": 250, "theme": "light", "fixedX": -1920, "fixedY": 15})
    store.set_profile("Fast", {"interval": 20, "double": True})
    store.save()

    again = SettingsStore.load(path)
    assert again.settings["interval"] == 250
    assert again.settings["theme"] == "light"
    assert (again.settings["fixedX"], again.settings["fixedY"]) == (-1920, 15)
    assert again.profiles["Fast"]["interval"] == 20
    assert again.profiles["Fast"]["double"] is True
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == SCHEMA_VERSION
    assert [p.name for p in path.parent.iterdir()] == ["settings.json"]  # No temp files left.


def test_garbage_values_fall_back_to_defaults():
    clean = sanitize_settings(
        {
            "interval": "abc",
            "mode": "sideways",
            "button": 3,
            "double": "maybe",
            "maxClicks": -5,
            "maxSeconds": float("nan"),
            "theme": None,
            "toggleKey": "f6",
            "stopKey": "f6",
            "sound": [],
        }
    )
    assert clean == SETTINGS_DEFAULTS


def test_legacy_string_values_are_coerced():
    # QSettings on Windows hands everything back as strings.
    clean = sanitize_settings(
        {"interval": "250", "double": "true", "failsafe": "false", "maxSeconds": "1.5", "toggleKey": "f2"}
    )
    assert clean["interval"] == 250
    assert clean["double"] is True
    assert clean["failsafe"] is False
    assert clean["maxSeconds"] == 1.5
    assert clean["toggleKey"] == "f2"


def test_out_of_range_interval_rejected():
    assert sanitize_profile({"interval": 0})["interval"] == PROFILE_DEFAULTS["interval"]
    assert sanitize_profile({"interval": 1})["interval"] == 1
    assert sanitize_profile({"interval": 12.5})["interval"] == PROFILE_DEFAULTS["interval"]


def test_fixed_position_needs_both_coordinates():
    assert sanitize_profile({"fixedX": 10})["fixedX"] is None
    assert sanitize_profile({"fixedX": 10, "fixedY": "oops"})["fixedX"] is None
    pair = sanitize_profile({"fixedX": "10", "fixedY": -20})
    assert (pair["fixedX"], pair["fixedY"]) == (10, -20)


def test_corrupt_file_is_set_aside(path):
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    store = SettingsStore.load(path)
    assert store.settings == SETTINGS_DEFAULTS
    assert store.load_warning and "reset" in store.load_warning
    assert (path.parent / "settings.json.corrupt").exists()
    assert not path.exists()


def test_non_object_root_is_corrupt(path):
    path.parent.mkdir(parents=True)
    path.write_text("[1, 2]", encoding="utf-8")
    assert SettingsStore.load(path).load_warning


def test_newer_schema_loads_best_effort(path):
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"version": 99, "settings": {"interval": 333}, "extra": 1}), encoding="utf-8")
    assert SettingsStore.load(path).settings["interval"] == 333


def test_legacy_migration_runs_once(path):
    calls = []

    def legacy():
        calls.append(1)
        return {
            "settings": {"interval": "75", "sound": "false"},
            "profiles": {"Slow": {"interval": "2000", "button": "right"}},
        }

    store = SettingsStore.load(path, legacy_loader=legacy)
    assert store.settings["interval"] == 75
    assert store.settings["sound"] is False
    assert store.profiles["Slow"]["button"] == "right"
    assert path.exists()

    SettingsStore.load(path, legacy_loader=legacy)
    assert len(calls) == 1


def test_legacy_loader_failure_is_not_fatal(path):
    def broken():
        raise RuntimeError("registry unavailable")

    assert SettingsStore.load(path, legacy_loader=broken).settings == SETTINGS_DEFAULTS


@pytest.mark.parametrize("name", ["a/b", "Fast & loose", "Ünïcødé", "x" * 64])
def test_profile_names_accepted(path, name):
    store = SettingsStore.load(path)
    store.set_profile(name, {"interval": 42})
    store.save()
    assert SettingsStore.load(path).profiles[name]["interval"] == 42


@pytest.mark.parametrize("name", ["", "   ", "x" * 65, "bad\nname", None])
def test_profile_names_rejected(name):
    with pytest.raises(ValueError):
        validate_profile_name(name)


def test_profiles_drop_app_preferences(path):
    store = SettingsStore.load(path)
    store.set_profile("p", {"interval": 50, "theme": "light", "toggleKey": "f1"})
    assert set(store.profiles["p"]) == set(PROFILE_DEFAULTS)


def test_profile_names_sorted_case_insensitively(path):
    store = SettingsStore.load(path)
    for name in ("beta", "Alpha", "gamma"):
        store.set_profile(name, {})
    assert store.profile_names() == ["Alpha", "beta", "gamma"]


def test_export_import(tmp_path, path):
    source = SettingsStore.load(path)
    source.set_profile("One", {"interval": 11})
    source.set_profile("Two", {"interval": 22})
    export = tmp_path / "export.json"
    assert source.export_profiles(export) == 2

    target = SettingsStore.load(tmp_path / "other.json")
    target.set_profile("Two", {"interval": 99})
    assert target.import_profiles(export) == (1, 1)
    assert target.profiles["Two"]["interval"] == 22


def test_import_rejects_bad_files(tmp_path, path):
    store = SettingsStore.load(path)
    bad = tmp_path / "bad.json"
    for content in ("nope", "[]", '{"profiles": 3}', '{"profiles": {"": {}}}'):
        bad.write_text(content, encoding="utf-8")
        with pytest.raises(ValueError):
            store.import_profiles(bad)
    with pytest.raises(ValueError):
        store.import_profiles(tmp_path / "missing.json")
    assert store.profiles == {}


def test_jitter_values_clamped_to_defaults():
    assert sanitize_profile({"jitterPct": 25, "jitterPx": 7})["jitterPct"] == 25
    assert sanitize_profile({"jitterPct": 51})["jitterPct"] == 0
    assert sanitize_profile({"jitterPx": -1})["jitterPx"] == 0


def test_hotkeys_normalized():
    clean = sanitize_settings({"toggleKey": "Alt+Ctrl+S", "stopKey": "Pause"})
    assert (clean["toggleKey"], clean["stopKey"]) == ("ctrl+alt+s", "pause")


@pytest.mark.parametrize("bad", ["a", "shift+b", "nope", 12, None])
def test_invalid_hotkeys_fall_back(bad):
    assert sanitize_settings({"toggleKey": bad})["toggleKey"] == SETTINGS_DEFAULTS["toggleKey"]


def test_hotkey_collision_keeps_toggle():
    clean = sanitize_settings({"toggleKey": "f8", "stopKey": "f12"})
    assert clean["toggleKey"] == "f8"
    assert clean["stopKey"] not in {"f8", "f12"}


def test_reserved_f12_is_migrated_with_notice(path):
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"version": 1, "settings": {"stopKey": "f12"}}), encoding="utf-8")
    store = SettingsStore.load(path)
    assert store.settings["stopKey"] == "f8"
    assert store.load_warning and "F12" in store.load_warning and "F8" in store.load_warning
