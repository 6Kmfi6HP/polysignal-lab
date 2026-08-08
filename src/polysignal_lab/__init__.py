from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import cast

import tomllib

__all__ = ["__version__"]


def _source_version() -> str:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project")
    if not isinstance(project, dict):
        raise KeyError("project")
    source_version = cast("dict[str, object]", project).get("version")
    if not isinstance(source_version, str):
        raise KeyError("project.version")
    return source_version


try:
    __version__: str = version("polysignal-lab")
except PackageNotFoundError:
    try:
        __version__ = _source_version()
    except (KeyError, OSError, tomllib.TOMLDecodeError):
        __version__ = "0+unknown"
