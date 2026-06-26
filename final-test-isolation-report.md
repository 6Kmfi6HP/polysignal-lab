# Final test isolation report

Fixed test pollution by restoring `polysignal_lab.nautilus_runtime.*` entries in `sys.modules` after the platform import-boundary assertion. Verified the two-file repro suite and the previously failing combined Nautilus targeted suite pass with Python 3.11.
