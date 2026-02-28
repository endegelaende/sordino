"""
jive.utils — Utility modules for the Jivelite Python3 port.

Ported from the original Lua utility modules in share/jive/jive/utils/.

Modules:
    - table_utils: Ordered iteration, list search/delete (from table.lua)
    - string_utils: Hex encoding, URL encode/decode, split, trim (from string.lua)
    - log: Logging facility by category and level (from log.lua)
    - debug: Table dumping and trace utilities (from debug.lua)
    - autotable: Auto-vivifying nested dictionaries (from autotable.lua)
    - datetime_utils: Date/time formatting utilities (from datetime.lua)
    - locale: Localization / string lookup (from locale.lua)
    - dumper: Pretty-printing of nested structures (from dumper.lua)
    - jsonfilters: JSON filtering utilities (from jsonfilters.lua)

Note: coxpcall.lua is NOT ported — Python has native try/except/finally.
"""

from __future__ import annotations

__all__ = [
    "table_utils",
    "string_utils",
    "log",
    "debug",
    "autotable",
    "datetime_utils",
    "locale",
    "dumper",
    "jsonfilters",
]
