"""Loading of user plugins (anime and light-novel sources): every subclass of a base class found in `<folder>/*.py`.

Plugins are ordinary Python run with the user's rights: only install files you trust. A broken plugin is skipped and logged,
it never stops the app.
"""
from __future__ import annotations

import importlib.util
import inspect
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def load_plugin_classes(folder: Path, base: type, prefix: str) -> list[type]:
    found: list[type] = []
    if not folder.is_dir():
        return found
    for file in sorted(folder.glob("*.py")):
        try:
            spec = importlib.util.spec_from_file_location(f"{prefix}_{file.stem}", file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001
            log.warning("plugin %s failed to load: %s", file.name, exc)
            continue
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if (issubclass(cls, base) and cls is not base and not inspect.isabstract(cls) and cls.__module__ == module.__name__):
                found.append(cls)
    return found


def build_plugins(classes: list[type], args: tuple, taken: set[str]) -> dict[str, object]:
    """Instantiate plugin classes; a class that fails to start, or whose name is taken, is skipped."""
    built: dict[str, object] = {}
    for cls in classes:
        try:
            source = cls(*args)
        except Exception as exc:  # noqa: BLE001
            log.warning("plugin %s could not start: %s", cls.__name__, exc)
            continue
        if source.name in taken or source.name in built:
            log.warning("plugin %s: the name '%s' is taken", cls.__name__, source.name)
            continue
        built[source.name] = source
    return built
