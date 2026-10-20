"""The plugins the hub loads in these tests are this checkout's, as the hub's image loads them: one core plugin per
entry point of this distribution, with the id, publisher and entry point name they had in evo-ak, version 1.1.0 of
their manifests, every contribution's Python in evo_core_plugins, and the version of the API they ask for the one the
evo-agents installed serves (the compat job's comparison). A plugin that asks for another version is left out with
the reason. No database."""

from __future__ import annotations

import importlib
import logging
import subprocess
import sys

import pytest

from evo_agents.hub import plugin_calls
from evo_agents.hub.server import core_plugin_api as hub
from evo_agents.hub.server import notifications
from evo_agents.plugins import core
from evo_core_plugins import PLUGINS
from evo_core_plugins import __main__ as command
from plugin_tests import conftest

MANIFEST_VERSION = "1.1.0"  # up from evo-ak's 1.0.0, so the hub's store records a new version of the image's plugins


@pytest.fixture(autouse=True)
def _fresh_registry():
    plugin_calls.core_registry.cache_clear()
    yield
    plugin_calls.core_registry.cache_clear()


def loaded() -> dict[str, core.CorePlugin]:
    return {plugin.entry_point: plugin for plugin in core.core_plugins() if plugin.entry_point in PLUGINS}


def test_the_hub_loads_each_plugin_once_from_this_distribution():
    assert conftest.ours() == frozenset(PLUGINS)
    found = loaded()
    assert sorted(found) == sorted(PLUGINS)
    ids = [plugin.manifest.id for plugin in core.core_plugins()]
    for name, plugin in found.items():
        assert plugin.value == f"evo_core_plugins.{name}:manifest"
        assert plugin.manifest.id == name and ids.count(name) == 1
        assert plugin.manifest.publisher == "evo-agents" and plugin.manifest.tier == "core"
        assert plugin.manifest.version == MANIFEST_VERSION
        assert plugin_calls.core_registry().manifest(name) == plugin.manifest


def test_what_another_distribution_declares_under_the_same_name_is_left_out():
    # evo-ak at the commit of evo-agents.lock still ships telegram and chats; once it does not, nothing is hidden.
    hidden = conftest.shadowed(conftest._read(group=core.ENTRY_POINT_GROUP))
    assert {point.name for point in hidden} <= frozenset(PLUGINS)
    assert all(not point.value.startswith("evo_core_plugins.") for point in hidden)
    kept = [point for point in core.entry_points(group=core.ENTRY_POINT_GROUP) if point.name in PLUGINS]
    assert sorted(point.name for point in kept) == sorted(PLUGINS)
    assert all(point.value.startswith("evo_core_plugins.") for point in kept)


def test_every_contribution_names_python_of_this_package():
    for name, plugin in loaded().items():
        refs = [ref for point in plugin.manifest.contributes for ref in plugin.manifest.python_refs(point).values()]
        assert refs, f"{name} contributes no Python"
        for ref in refs:
            assert ref.startswith(f"evo_core_plugins.{name}."), ref
            assert plugin_calls.load(ref) is not None


def test_the_channel_of_kind_telegram_is_this_plugins():
    from evo_core_plugins.telegram.server import TelegramChannel

    assert notifications.channel_class("telegram") is TelegramChannel
    assert hub.plugin("evo_core_plugins.telegram.server").id == "telegram"
    assert hub.plugin("evo_core_plugins.chats.kg").id == "chats"


def test_the_plugins_ask_for_the_api_this_evo_agents_serves():
    assert command.versions() == {name: hub.API_VERSION for name in PLUGINS}
    for name in PLUGINS:
        assert importlib.import_module(f"evo_core_plugins.{name}").API == hub.API_VERSION
    printed = subprocess.run(
        [sys.executable, "-m", "evo_core_plugins", "api"], capture_output=True, text=True, check=True
    ).stdout
    assert printed == ".".join(map(str, hub.API_VERSION)) + "\n"


@pytest.mark.parametrize("name", PLUGINS)
def test_a_plugin_written_for_another_api_version_is_left_out_with_the_reason(name, monkeypatch, caplog):
    module = importlib.import_module(f"evo_core_plugins.{name}")
    major, minor = hub.API_VERSION
    monkeypatch.setattr(module, "API", (major, minor + 1))
    with caplog.at_level(logging.WARNING, logger=core.__name__):
        assert name not in loaded()
    (record,) = [
        record
        for record in caplog.records
        if record.getMessage() == "core plugin not loaded" and record.entry_point == name
    ]
    served = f"{major}.{minor}"
    assert record.error == (
        f"UnsupportedApi: evo_core_plugins.{name} needs core plugin API {major}.{minor + 1}; this hub serves {served}"
    )


def test_the_command_refuses_plugins_that_ask_for_different_versions(tmp_path, capsys):
    for name, api in zip(PLUGINS, [(1, 1), (1, 2)], strict=True):
        (tmp_path / name).mkdir()
        (tmp_path / name / "__init__.py").write_text(f"API = {api!r}\n", encoding="utf-8")
    assert command.versions(tmp_path) == {"telegram": (1, 1), "chats": (1, 2)}
    assert command.main(["api"], tmp_path) == 1
    assert "different versions of the API: telegram 1.1, chats 1.2" in capsys.readouterr().err
    assert command.main([]) == 2
    (tmp_path / "chats" / "__init__.py").write_text('API = "1.1"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="not \\(major, minor\\)"):
        command.required("chats", tmp_path)
