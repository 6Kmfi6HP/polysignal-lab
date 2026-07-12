# Legacy dual-path residue

Modules in this package that still mention `OrderBookRegistry`, standalone CLOB REST/WS clients, or domain live books are **non-live residue**.

They are retained only for:

- historical tests
- non-runtime adapters that have not yet been deleted

They are **not** live trading truth.

Cutover rules (see `docs/RUNTIME_BOUNDARY.md`):

- `nautilus_runtime`, `nautilus_bridge`, and `signal_layer` must not import these as decision/book authority
- MarketView books come only from Nautilus Cache projections
- safety scan / platform boundary tests enforce the forbid-list

Do not reattach these surfaces to the live decision path.
