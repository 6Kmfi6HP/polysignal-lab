from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import tomllib

__all__ = ["__version__"]

try:
    __version__ = version("polysignal-lab")
except PackageNotFoundError:
    try:
        _pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        __version__ = tomllib.loads(_pyproject.read_text(encoding="utf-8"))["project"][
            "version"
        ]
    except (KeyError, OSError, tomllib.TOMLDecodeError):
        __version__ = "0+unknown"
