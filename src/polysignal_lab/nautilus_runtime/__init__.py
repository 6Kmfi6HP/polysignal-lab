"""Nautilus runtime package — platform boundary for the optional Nautilus engine.

The default runtime stays paper-safe and never imports ``nautilus_trader``.
Real wiring lands in Task 13; until then ``node.run_nautilus_cli`` raises a
clear ``RuntimeError`` so the CLI boundary exists without enabling live paths.
"""
