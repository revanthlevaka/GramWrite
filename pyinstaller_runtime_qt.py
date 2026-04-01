from __future__ import annotations

import os
import sys
from pathlib import Path


def _qt_plugin_candidates() -> list[Path]:
    base_path = Path(getattr(sys, "_MEIPASS", Path.cwd()))
    return [
        base_path / "PyQt6" / "Qt6" / "plugins",
        base_path.parent / "Frameworks" / "PyQt6" / "Qt6" / "plugins",
        base_path.parent / "Resources" / "PyQt6" / "Qt6" / "plugins",
    ]


for plugins_dir in _qt_plugin_candidates():
    if not plugins_dir.exists():
        continue
    os.environ["QT_PLUGIN_PATH"] = str(plugins_dir)
    platform_dir = plugins_dir / "platforms"
    if platform_dir.exists():
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(platform_dir)
    break
