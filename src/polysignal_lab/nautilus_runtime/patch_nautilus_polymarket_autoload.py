from __future__ import annotations

import importlib.metadata
import importlib.util
from pathlib import Path

EXPECTED_VERSION = "1.229.0"
MODULE = "nautilus_trader.adapters.polymarket.data"
DISTRIBUTION = "nautilus_trader"

OLD_BLOCK = '''                except Exception as e:
                    self._log.error(f"Auto-load batch failed: {e}")
                    _resolve_with_exception(pending, e)
                    return'''

NEW_BLOCK = '''                except Exception as e:
                    self._log.error(f"Auto-load batch failed: {e}")
                    if attempt >= max_retries:
                        _resolve_with_exception(pending, e)
                        return
                    delay = auto_load_retry_delay(
                        attempt,
                        base_secs=base_secs,
                        max_secs=max_secs,
                    )
                    self._log.info(
                        f"Auto-load retry {attempt + 1}/{max_retries} for "
                        f"{len(pending)} instrument(s) after batch failure in {delay:.1f}s",
                        LogColor.YELLOW,
                    )
                    await asyncio.sleep(delay)
                    continue'''


def patch_source(source: str) -> str:
    if OLD_BLOCK not in source:
        raise RuntimeError("expected auto-load exception block not found; refusing to patch")
    return source.replace(OLD_BLOCK, NEW_BLOCK, 1)


def patch_installed() -> Path:
    version = importlib.metadata.version(DISTRIBUTION)
    if version != EXPECTED_VERSION:
        raise RuntimeError(f"expected {DISTRIBUTION}=={EXPECTED_VERSION}, found {version}")

    spec = importlib.util.find_spec(MODULE)
    if spec is None or spec.origin is None:
        raise RuntimeError(f"could not locate {MODULE}")

    path = Path(spec.origin)
    source = path.read_text(encoding="utf-8")
    _ = path.write_text(patch_source(source), encoding="utf-8")
    return path


def main() -> None:
    patched = patch_installed()
    print(f"patched {patched}")


if __name__ == "__main__":
    main()
