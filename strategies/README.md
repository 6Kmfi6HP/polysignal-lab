# External strategies (no container rebuild)

Drop a Python file in this directory and reference it from `config/*.yaml` to
add a strategy **without rebuilding the image**. The directory is bind-mounted
into the container at `/app/strategies` and is scanned at runtime.

## YAML shape

```yaml
safety:
  allow_external_strategies: true   # required gate, off by default

strategies:
  external:
    - name: my_strategy             # unique; must not collide with built-ins
      enabled: true
      module: example_external_strategy.py   # file here, or an importable module
      class_name: ExampleExternalAlphaCore
      assets: [BTC]
      timeframes: [5m, 15m]
      params:
        threshold: 0.40
        max_spread: 0.05
```

`module` is either:

- a path relative to this directory (e.g. `example_external_strategy.py` or
  `subdir/foo.py`), loaded from the mounted volume; or
- a fully qualified importable module path (e.g. `my_pkg.my_module`).

File-based modules are confined to this directory; paths that escape it are
refused.

## Plugin contract

The referenced class must satisfy the `AlphaCore` protocol:

```python
def evaluate(self, view: MarketView) -> list[AlphaDecision]: ...
```

This is checked when the plugin is resolved: a class without a callable
`evaluate` is rejected at startup rather than failing per market update.

The host passes a config object with `name`, `assets`, `timeframes` and
`params` (the YAML block above). `assets`/`timeframes` drive market
subscriptions; `params` is your free-form configuration. See
`example_external_strategy.py` for a working, minimal implementation that emits
an `AlphaDecision`.

After construction the host assigns `config` and `name` onto the instance, so
the class must permit attribute assignment — a `__slots__` class that omits
those names, or a frozen dataclass, is refused with an explanatory error.

Note the sandbox applies to the **file** form of `module` only. A dotted
importable module path is resolved through the normal import system and is not
confined to this directory, so treat it as trusted-code configuration.

## Enabling it on a deployment

The bundled `docker-compose.yml` mounts this directory read-only and sets
`POLYSIGNAL_STRATEGY_ROOT`, but ships the feature **off**: nothing loads until
you both open the safety gate and declare a `strategies.external` block. Opting
in is a deliberate, two-part step:

1. Add the `safety.allow_external_strategies` and `strategies.external` keys to
   the config the container reads, and
2. rebuild/pin an image that understands those keys.

Order matters. `config/` is bind-mounted read-only and `Settings` forbids
unknown keys, so a config carrying `strategies.external` fed to an image built
before this feature makes every in-container `load_settings` fail — the failure
mode documented at the top of `config/signal_bot.yaml`. Pin the image
explicitly (`POLYSIGNAL_IMAGE_REF`, see `docs/versioning.md`) when you switch
the config over.

## Reloading

Editing YAML or swapping the `.py` file takes effect on the next runtime start
(regular container restart, no image rebuild). The module is imported once per
process, so a fresh container is required to pick up code changes.

## Bundled examples

These plugins ship in this directory and are exercised by
`tests/test_external_strategy_functional.py`. Copy any of them as a starting
point for your own strategy:

- `example_external_strategy.py` — minimal buy-when-cheap demo of the contract.
- `momentum_breakout_external.py` — picks the cheaper side below a threshold.
- `mean_reversion_external.py` — buys the cheaper leg when the pair is mispriced
  above parity (`up.best_ask + down.best_ask > params.inefficiency`).
- `pairs_hedge_external.py` — emits an entry plus a `reduce_only` hedge leg on
  the opposite side (covers the hedge/exit contract).
- `spot_confirmed_external.py` — only trades when `view.spot` is present and in
  `params.price_band` (covers the spot-data branch).
- `staleness_guard_external.py` — returns no decisions when
  `view.freshness.max_ms` exceeds `params.max_freshness_ms`.
