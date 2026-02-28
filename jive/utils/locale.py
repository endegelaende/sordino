"""
jive.utils.locale — Localisation module with strings.txt parser.

Ported from share/jive/jive/utils/locale.lua

Provides locale-based string lookup for the Jivelite application.
The original Lua module parses ``strings.txt`` files that contain
translation tokens with locale-specific translations, and provides
string lookup with fallback to English.

File format for ``strings.txt``::

    TOKEN_NAME
    \tEN\tEnglish translation
    \tDE\tGerman translation
    \tFR\tFrench translation

    ANOTHER_TOKEN
    \tEN\tAnother English string
    \tDE\tEin anderer deutscher String

- Lines starting with an uppercase letter are token names.
- Translation lines start with one or more tabs, followed by the
  locale code (e.g. ``EN``, ``DE``), then one or more tabs, then
  the translated string.
- ``\\n`` in translations is converted to actual newlines.
- If no translation exists for the current locale, English (``EN``)
  is used as fallback.

The original Lua module depends on ``jive.System`` for finding files
and determining the machine type, and ``jive.ui.Task`` for cooperative
yielding. In this Python port we provide a self-contained implementation
that works without those dependencies, using ``pathlib`` for file
discovery and a configurable machine suffix for machine-specific
string overrides.

Usage::

    from jive.utils.locale import Locale

    loc = Locale()
    loc.set_locale("DE")

    # Load a strings file
    strings = loc.read_strings_file("/path/to/strings.txt")

    # Look up a translated string
    greeting = strings.str("GREETING")

    # With format arguments
    welcome = strings.str("WELCOME_USER", "Alice")

    # Get/set current locale
    print(loc.get_locale())  # "DE"

Copyright 2010 Logitech. All Rights Reserved.
This file is licensed under BSD. Please see the LICENSE file for details.
"""

from __future__ import annotations

import re
import weakref
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from jive.utils.log import logger

log = logger("jivelite.locale")


# ─── LocalizedString ──────────────────────────────────────────────────────────


class LocalizedString:
    """
    A wrapper around a string value that allows the translation to be
    changed later (e.g. when the locale is switched).

    In the original Lua code, each token is stored as a table with a
    ``str`` field and a ``__tostring`` metamethod. We replicate this
    with a simple class that stores the current translation and
    supports ``str()`` / ``__str__()`` conversion.

    Examples:
        >>> ls = LocalizedString("Hello")
        >>> str(ls)
        'Hello'
        >>> ls.str = "Hallo"
        >>> str(ls)
        'Hallo'
        >>> ls.str = False  # not yet translated
        >>> str(ls)
        ''
    """

    __slots__ = ("str",)

    def __init__(self, value: Union[str, bool] = False) -> None:
        self.str: Union[str, bool] = value

    def __str__(self) -> str:
        if isinstance(self.str, str):
            return self.str
        return ""

    def __repr__(self) -> str:
        return f"LocalizedString({self.str!r})"

    def __bool__(self) -> bool:
        """Return True if a translation is set (non-False, non-empty)."""
        return isinstance(self.str, str) and len(self.str) > 0

    def __eq__(self, other: object) -> bool:
        if isinstance(other, LocalizedString):
            return self.str == other.str
        if isinstance(other, str):
            return self.str == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.str)


# ─── StringsTable ─────────────────────────────────────────────────────────────


class StringsTable:
    """
    A table of localized strings loaded from a ``strings.txt`` file.

    Supports dict-like access (``table["TOKEN"]``) and a ``str()``
    method for looking up tokens with optional format arguments and
    machine-specific overrides.

    The table can have a parent (fallback) table — typically the
    global strings table — which is consulted when a token is not
    found in this table.

    Examples:
        >>> table = StringsTable()
        >>> table["HELLO"] = LocalizedString("Hello")
        >>> table.str("HELLO")
        'Hello'
        >>> table.str("MISSING")
        'MISSING'
    """

    def __init__(
        self,
        parent: Optional[StringsTable] = None,
        machine_suffix: str = "",
    ) -> None:
        self._data: Dict[str, LocalizedString] = {}
        self._parent = parent
        self._machine_suffix = machine_suffix

    def __getitem__(self, key: str) -> Optional[LocalizedString]:
        if key in self._data:
            return self._data[key]
        if self._parent is not None:
            return self._parent[key]
        return None

    def __setitem__(self, key: str, value: LocalizedString) -> None:
        self._data[key] = value

    def __contains__(self, key: str) -> bool:
        if key in self._data:
            return True
        if self._parent is not None:
            return key in self._parent
        return False

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value by key with a default fallback."""
        result = self[key]
        if result is None:
            return default
        return result

    def keys(self) -> List[str]:
        """Return all keys in this table (not including parent)."""
        return list(self._data.keys())

    def str(
        self,
        token: Union[str, LocalizedString],
        *args: Any,
    ) -> str:
        """
        Look up a localized string by token name.

        If the token is a :class:`LocalizedString`, its ``.str`` value
        is used as the token name.  Machine-specific overrides are
        checked first (token + machine suffix).

        When format arguments are provided, the translated string is
        passed through ``str.format()`` or ``%``-formatting (matching
        the Lua ``string.format`` convention).

        Args:
            token: The token name (string or LocalizedString).
            *args: Optional format arguments.

        Returns:
            The translated string, or the token name itself if no
            translation is found.

        Examples:
            >>> t = StringsTable()
            >>> t["HELLO"] = LocalizedString("Hello")
            >>> t.str("HELLO")
            'Hello'
            >>> t.str("MISSING")
            'MISSING'
        """
        # Resolve token to string
        if isinstance(token, LocalizedString):
            token_str = token.str if isinstance(token.str, str) else str(token)
        else:
            token_str = str(token)

        # Try machine-specific override first
        if self._machine_suffix:
            machine_token = token_str + self._machine_suffix
            machine_entry = self[machine_token]
            if machine_entry is not None and machine_entry:
                if args:
                    return _format_string(
                        machine_entry.str
                        if isinstance(machine_entry.str, str)
                        else machine_token,
                        args,
                    )
                return str(machine_entry)

        # Try the regular token
        entry = self[token_str]
        if entry is not None and entry:
            if args:
                return _format_string(
                    entry.str if isinstance(entry.str, str) else token_str,
                    args,
                )
            return str(entry)

        # Fallback: return the token name itself
        if args:
            return _format_string(token_str, args)
        return token_str

    def __repr__(self) -> str:
        parent_info = f", parent={self._parent!r}" if self._parent else ""
        return f"StringsTable({len(self._data)} entries{parent_info})"


# ─── Locale (main class) ─────────────────────────────────────────────────────


class Locale:
    """
    Locale manager that handles loading and switching between locales.

    Manages a global locale setting and keeps track of all loaded
    strings files so they can be reloaded when the locale changes.

    The Lua original uses module-level state. We use a class to allow
    multiple instances in tests, but also provide a module-level
    singleton via :func:`get_locale_instance`.

    Args:
        machine: Machine type string (e.g. ``"jive"``, ``"fab4"``).
                 Used to look up machine-specific string overrides
                 (token + ``"_MACHINE"`` suffix). If empty, no
                 machine-specific overrides are applied.
        find_file: Optional callable that resolves a logical path
                   (like ``"jive/global_strings.txt"``) to an actual
                   filesystem path. If not provided, paths are used
                   as-is.

    Examples:
        >>> loc = Locale()
        >>> loc.get_locale()
        'EN'
        >>> loc.set_locale("DE")
        >>> loc.get_locale()
        'DE'
    """

    def __init__(
        self,
        machine: str = "",
        find_file: Optional[Any] = None,
    ) -> None:
        self._locale: str = "EN"
        self._all_locales: Dict[str, bool] = {}
        self._loaded_files: weakref.WeakValueDictionary[str, StringsTable] = (
            weakref.WeakValueDictionary()
        )
        self._global_strings: StringsTable = StringsTable(
            machine_suffix=f"_{machine.upper()}" if machine else "",
        )
        self._machine: str = machine
        self._machine_suffix: str = f"_{machine.upper()}" if machine else ""
        self._find_file = find_file

    def set_locale(self, new_locale: str, do_yield: bool = False) -> None:
        """
        Set a new locale and reload all loaded strings files.

        Args:
            new_locale: The locale code (e.g. ``"EN"``, ``"DE"``, ``"FR"``).
            do_yield: Ignored in Python (was for Lua cooperative multitasking).

        Examples:
            >>> loc = Locale()
            >>> loc.set_locale("DE")
            >>> loc.get_locale()
            'DE'
        """
        if new_locale == self._locale:
            return

        self._locale = new_locale or "EN"
        self.read_global_strings_file()

        # Reload all previously loaded strings files
        for path, table in list(self._loaded_files.items()):
            _parse_strings_file(self._locale, path, table, self._all_locales)

    def get_locale(self) -> str:
        """
        Return the current locale code.

        Returns:
            The locale code string (e.g. ``"EN"``).

        Examples:
            >>> Locale().get_locale()
            'EN'
        """
        return self._locale

    def get_all_locales(self) -> List[str]:
        """
        Return all locale codes seen in any loaded strings files.

        Returns:
            Sorted list of locale code strings.

        Examples:
            >>> loc = Locale()
            >>> locales = loc.get_all_locales()
            >>> isinstance(locales, list)
            True
        """
        return sorted(self._all_locales.keys())

    def read_global_strings_file(
        self,
        global_strings_path: Optional[str] = None,
    ) -> StringsTable:
        """
        Load (or reload) the global strings file.

        The global strings table serves as the fallback parent for
        all other strings tables.

        Args:
            global_strings_path: Path to the global strings file.
                                 If not provided, attempts to use the
                                 ``find_file`` callback to locate
                                 ``"jive/global_strings.txt"``.

        Returns:
            The global :class:`StringsTable`.

        Examples:
            >>> loc = Locale()
            >>> gs = loc.read_global_strings_file()
            >>> isinstance(gs, StringsTable)
            True
        """
        if global_strings_path is None:
            if self._find_file is not None:
                resolved = self._find_file("jive/global_strings.txt")
                if resolved is not None:
                    global_strings_path = str(resolved)
            if global_strings_path is None:
                return self._global_strings

        _parse_strings_file(
            self._locale,
            global_strings_path,
            self._global_strings,
            self._all_locales,
        )
        return self._global_strings

    def read_strings_file(
        self,
        full_path: str,
        strings_table: Optional[StringsTable] = None,
    ) -> StringsTable:
        """
        Parse a ``strings.txt`` file and return a :class:`StringsTable`.

        The returned table has the global strings as its parent, so
        any token not found in this file will fall through to the
        global strings.

        Args:
            full_path: Path to the strings.txt file.
            strings_table: Optional existing table to populate. If
                           ``None``, a new table is created.

        Returns:
            The populated :class:`StringsTable`.

        Examples:
            >>> import tempfile, os
            >>> loc = Locale()
            >>> with tempfile.NamedTemporaryFile(mode='w', suffix='.txt',
            ...         delete=False) as f:
            ...     _ = f.write("HELLO\\n\\tEN\\tHello World\\n")
            ...     name = f.name
            >>> table = loc.read_strings_file(name)
            >>> table.str("HELLO")
            'Hello World'
            >>> os.unlink(name)
        """
        log.debug("loading strings from ", full_path)

        if strings_table is None:
            strings_table = StringsTable(
                parent=self._global_strings,
                machine_suffix=self._machine_suffix,
            )

        self._loaded_files[full_path] = strings_table

        _parse_strings_file(self._locale, full_path, strings_table, self._all_locales)

        return strings_table

    def load_all_strings(self, file_path: str) -> Dict[str, Dict[str, str]]:
        """
        Parse a strings file and return ALL locale translations.

        Unlike :meth:`read_strings_file` which only loads the current
        locale, this method loads every translation for every locale.

        Args:
            file_path: Path to the strings.txt file.

        Returns:
            A nested dict: ``{locale: {token: translation}}``.

        Examples:
            >>> import tempfile, os
            >>> loc = Locale()
            >>> with tempfile.NamedTemporaryFile(mode='w', suffix='.txt',
            ...         delete=False) as f:
            ...     _ = f.write("HELLO\\n\\tEN\\tHello\\n\\tDE\\tHallo\\n")
            ...     name = f.name
            >>> all_strings = loc.load_all_strings(name)
            >>> all_strings["EN"]["HELLO"]
            'Hello'
            >>> all_strings["DE"]["HELLO"]
            'Hallo'
            >>> os.unlink(name)
        """
        return _parse_all_strings(file_path)

    @property
    def global_strings(self) -> StringsTable:
        """Access the global strings table."""
        return self._global_strings


# ─── Module-Level Singleton ───────────────────────────────────────────────────

_instance: Optional[Locale] = None


def get_locale_instance() -> Locale:
    """
    Get or create the module-level :class:`Locale` singleton.

    This provides a convenient way to access the locale system
    without passing a Locale instance around, matching the Lua
    module's global-state approach.

    Returns:
        The singleton Locale instance.

    Examples:
        >>> loc = get_locale_instance()
        >>> isinstance(loc, Locale)
        True
        >>> loc is get_locale_instance()
        True
    """
    global _instance
    if _instance is None:
        _instance = Locale()
    return _instance


def reset_instance() -> None:
    """
    Reset the module-level singleton (primarily for testing).

    Examples:
        >>> reset_instance()
        >>> loc = get_locale_instance()
        >>> loc.get_locale()
        'EN'
    """
    global _instance
    _instance = None


# ─── File Parsing ─────────────────────────────────────────────────────────────


def _parse_strings_file(
    my_locale: str,
    file_path: str,
    strings_table: StringsTable,
    all_locales: Dict[str, bool],
) -> StringsTable:
    """
    Parse a ``strings.txt`` file, populating *strings_table* with
    translations for *my_locale* (with EN as fallback).

    This is the core parser that implements the Jivelite strings file
    format:

    - Lines starting with an uppercase letter define a new token.
    - Lines starting with tabs contain locale-specific translations.
    - The translation line format is: ``\\t+LOCALE\\t+translation``
    - ``\\\\n`` in translations is converted to ``\\n``.
    - If no translation is found for *my_locale*, the EN translation
      is used as fallback.

    Args:
        my_locale: The locale to load translations for.
        file_path: Path to the strings file.
        strings_table: The table to populate.
        all_locales: Dict tracking all locale codes seen (mutated).

    Returns:
        The populated *strings_table*.
    """
    log.debug("parsing ", file_path)

    path = Path(file_path)
    if not path.is_file():
        return strings_table

    token: Optional[str] = None
    fallback: Optional[str] = None

    # Regex for translation lines:
    # One or more tabs, then the locale code (non-whitespace),
    # then one or more tabs, then the translation (rest of line).
    translation_pattern = re.compile(r"^\t+(\S+)\t+(.+)")

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for raw_line in f:
                line = raw_line.rstrip()

                # Token line: starts with an uppercase letter
                if line and line[0].isupper():
                    # Apply fallback for previous token if needed
                    if (
                        token is not None
                        and fallback is not None
                        and token in strings_table
                    ):
                        entry = strings_table[token]
                        if entry is not None and not entry:
                            log.debug("EN fallback=", fallback)
                            entry.str = fallback

                    # Start new token
                    token = line
                    log.debug("token=", token)
                    fallback = None

                    # Create entry if it doesn't exist yet
                    if token not in strings_table._data:
                        strings_table[token] = LocalizedString(False)
                    else:
                        # Reset for re-parsing (locale switch)
                        entry = strings_table[token]
                        if entry is not None:
                            entry.str = False

                    continue

                # Translation line
                m = translation_pattern.match(line)
                if m and token is not None:
                    locale_code = m.group(1)
                    translation = m.group(2)

                    # Track all locales seen
                    all_locales[locale_code] = True

                    if locale_code == my_locale:
                        log.debug("translation=", translation)
                        # Convert literal \n to newline
                        translation = translation.replace("\\n", "\n")
                        entry = strings_table[token]
                        if entry is not None:
                            entry.str = translation

                    if locale_code == "EN":
                        fallback = translation.replace("\\n", "\n")

        # Apply fallback for the last token
        if token is not None and fallback is not None and token in strings_table:
            entry = strings_table[token]
            if entry is not None and not entry:
                log.debug("EN fallback=", fallback)
                entry.str = fallback

    except OSError as e:
        log.error("Failed to read strings file: ", str(e))

    return strings_table


def _parse_all_strings(file_path: str) -> Dict[str, Dict[str, str]]:
    """
    Parse a strings file and return translations for ALL locales.

    Args:
        file_path: Path to the strings file.

    Returns:
        Nested dict: ``{locale_code: {token: translation}}``.
    """
    path = Path(file_path)
    if not path.is_file():
        return {}

    all_strings: Dict[str, Dict[str, str]] = {}
    token: Optional[str] = None

    translation_pattern = re.compile(r"^\t+(\S+)\t+(.+)")

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for raw_line in f:
                line = raw_line.rstrip()

                # Token line
                if line and line[0].isupper():
                    token = line
                    log.debug("this is a string to be matched |", token, "|")
                    continue

                # Translation line
                m = translation_pattern.match(line)
                if m and token is not None:
                    locale_code = m.group(1)
                    translation = m.group(2)

                    # Convert literal \n
                    translation = translation.replace("\\n", "\n")

                    if locale_code not in all_strings:
                        all_strings[locale_code] = {}

                    all_strings[locale_code][token] = translation

    except OSError as e:
        log.error("Failed to read strings file: ", str(e))

    return all_strings


# ─── Internal Helpers ─────────────────────────────────────────────────────────


def _format_string(template: str, args: Sequence[Any]) -> str:
    """
    Format a string with positional arguments.

    Tries ``%``-style formatting first (matching Lua's ``string.format``),
    then falls back to ``str.format`` if that fails, and finally just
    appends the arguments if neither works.

    Args:
        template: The format string (may contain ``%s``, ``%d``, ``{}``, etc.).
        args: Positional arguments to substitute.

    Returns:
        The formatted string.
    """
    if not args:
        return template

    # Try %-style formatting (Lua string.format convention)
    try:
        return template % args
    except (TypeError, ValueError):
        pass

    # Try str.format style
    try:
        return template.format(*args)
    except (IndexError, KeyError, ValueError):
        pass

    # Last resort: just append args
    return template + " " + " ".join(str(a) for a in args)
