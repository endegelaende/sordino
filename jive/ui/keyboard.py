"""
jive.ui.keyboard — On-screen keyboard widget for the Jivelite Python3 port.

Ported from ``Keyboard.lua`` in the original jivelite project.

A Keyboard widget is a container (extends Group) that arranges Button
widgets in rows to form an on-screen keyboard.  It supports multiple
pre-defined layouts (qwerty, numeric, hex, email, IP) as well as
locale-specific variants (DE, FR, PL).

The keyboard dynamically computes key sizes based on screen width and
supports special keys: shift, space bar, arrow keys (cursor movement),
backspace, "done" (finish_operation), and layout-switch buttons.

Key layout structure::

    keyboard.keyboards = {
        'qwerty': [
            ['q', 'w', 'e', ...],       # row 1
            [spacer, 'a', 's', ...],     # row 2
            [shift_key, 'z', 'x', ...],  # row 3
            [switch_btn, space, go_btn], # row 4
        ],
        'numeric': [...],
        ...
    }

Each key in a row can be:
- A plain string (single character) — creates a standard key Button
- A dict with special properties (text, icon, keyWidth, callback, etc.)

Usage::

    from jive.ui.keyboard import Keyboard

    keyboard = Keyboard("keyboard", "qwerty", textinput=my_textinput)
    window.add_widget(keyboard)

Copyright 2010 Logitech. All Rights Reserved. (original Lua implementation)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import math
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from jive.ui.constants import (
    EVENT_CHAR_PRESS,
    EVENT_CONSUME,
)
from jive.ui.event import Event
from jive.ui.group import Group
from jive.ui.icon import Icon
from jive.ui.label import Label
from jive.ui.widget import Widget
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.ui.framework import Framework as FrameworkType

__all__ = ["Keyboard"]

log = logger("jivelite.ui")

# ---------------------------------------------------------------------------
# Module-level defaults (computed from screen size in __init__)
# ---------------------------------------------------------------------------

ROW_NUMBER_OF_KEYS: int = 10

# These are re-computed per instance based on screen dimensions
_DEFAULT_ROW_BORDER: int = 20

# ---------------------------------------------------------------------------
# Button text labels for keyboard-switch buttons
# ---------------------------------------------------------------------------

KEYBOARD_BUTTON_TEXT: Dict[str, str] = {
    "qwerty": "abc",
    "numeric": "123-&",
    "numericShift": "123-&",
    "numericMore": '" ~ < ]',
    "numericBack": ": + @ $",
    "hex": "hex",
    "chars": "!@&",
    "emailNumeric": "123-&",
}

# ---------------------------------------------------------------------------
# Key spec type — either a plain character string or a dict with metadata
# ---------------------------------------------------------------------------

KeySpec = Union[str, Dict[str, Any]]
RowSpec = List[KeySpec]
LayoutSpec = List[RowSpec]


class Keyboard(Group):
    """
    An on-screen keyboard widget.

    Extends :class:`~jive.ui.group.Group` and arranges Button widgets
    in rows.  Supports multiple pre-defined and user-defined keyboard
    layouts.

    Parameters
    ----------
    style : str
        The style key for skinning.
    kb_type : str or list
        The initial keyboard type — either a pre-defined name
        (``'qwerty'``, ``'numeric'``, ``'hex'``, ``'ip'``, ``'email'``,
        etc.) or a user-defined layout table.
    textinput : object, optional
        The associated Textinput widget.  If provided, the keyboard
        will call ``textinput.is_valid()`` to update the "done" button
        styling, and register for update callbacks.
    """

    def __init__(
        self,
        style: str,
        kb_type: Union[str, LayoutSpec] = "qwerty",
        textinput: Any = None,
    ) -> None:
        if not isinstance(style, str):
            raise TypeError(f"style must be a string, got {type(style).__name__}")

        # Initialize as a Group with no initial child widgets
        super().__init__(style, {})

        # Get screen dimensions from Framework
        try:
            from jive.ui.framework import framework as fw

            screen_w, screen_h = fw.get_screen_size()
        except (ImportError, AttributeError):
            screen_w, screen_h = 480, 272  # Fallback defaults

        # Ensure minimum usable dimensions (test/headless environments
        # may report 1×1 or similarly tiny screens)
        if screen_w < 100:
            screen_w = 480
        if screen_h < 100:
            screen_h = 272

        # Compute keyboard geometry (matching Lua calculations)
        row_border = _DEFAULT_ROW_BORDER
        keyboard_width = (screen_w - row_border) - (
            (screen_w - row_border) % ROW_NUMBER_OF_KEYS
        )
        row_border = (screen_w - keyboard_width) - ((screen_w - keyboard_width) % 2)
        row_offset_x = row_border // 2

        self._keyboard_width: int = keyboard_width
        self._row_border: int = row_border
        self._row_offset_x: int = row_offset_x

        # Default key dimensions
        self._default_width: int = keyboard_width // ROW_NUMBER_OF_KEYS
        self._default_height: int = (keyboard_width // ROW_NUMBER_OF_KEYS) - 3
        self._default_width_large: int = (keyboard_width // ROW_NUMBER_OF_KEYS) * 2

        # State
        self.kb_type: Union[str, LayoutSpec] = kb_type
        self.textinput: Any = textinput
        self.keyboard: List[
            List[Widget]
        ] = []  # current layout — list of rows of Button widgets
        self.key_info: List[List[Dict[str, Any]]] = []  # metadata per key
        self.keyboards: Dict[str, LayoutSpec] = {}  # all pre-defined layouts
        self.last: Optional[str] = None  # for one-key shift behaviour
        self.pushed: Optional[str] = None  # last switch-keyboard text

        # Build pre-defined keyboard layouts
        self._predefined_keyboards()

        # Set the initial keyboard layout
        self.set_keyboard(kb_type)

        # Hook up textinput update callback
        if textinput is not None:
            self._input_updated()
            if hasattr(textinput, "set_update_callback"):
                textinput.set_update_callback(lambda ti: self._input_updated())
            elif hasattr(textinput, "setUpdateCallback"):
                textinput.setUpdateCallback(lambda ti: self._input_updated())

    # ==================================================================
    # Pre-defined keyboard layouts
    # ==================================================================

    def _predefined_keyboards(self) -> None:
        """Build all pre-defined keyboard layout specs."""

        email_bottom_row: RowSpec = [
            self._switch_keyboard_button(
                "emailNumeric", KEYBOARD_BUTTON_TEXT["emailNumeric"]
            ),
            {"keyWidth": 0, "text": "."},
            {"keyWidth": 0, "text": "@"},
            "_",
            "-",
            self._go(),
        ]

        self.keyboards = {
            # ---- QWERTY (uppercase) ----
            "qwertyUpper": [
                ["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P"],
                [
                    self._spacer(),
                    "A",
                    "S",
                    "D",
                    "F",
                    "G",
                    "H",
                    "J",
                    "K",
                    "L",
                    self._spacer(),
                ],
                [
                    self._shift_key("qwerty"),
                    "Z",
                    "X",
                    "C",
                    "V",
                    "B",
                    "N",
                    "M",
                    self._arrow("left", "middle"),
                    self._arrow("right", "right"),
                ],
                [
                    self._switch_keyboard_button(
                        "numeric",
                        KEYBOARD_BUTTON_TEXT["numeric"],
                        self._default_width_large,
                        "qwerty",
                    ),
                    self._space_bar(),
                    self._go(self._default_width_large),
                ],
            ],
            # ---- QWERTY (uppercase, FR) ----
            "qwertyUpper_FR": [
                ["A", "Z", "E", "R", "T", "Y", "U", "I", "O", "P"],
                ["Q", "S", "D", "F", "G", "H", "J", "K", "L", "M"],
                [
                    self._shift_key("qwerty_FR"),
                    self._spacer(),
                    "W",
                    "X",
                    "C",
                    "V",
                    "B",
                    "N",
                    self._arrow("left", "middle"),
                    self._arrow("right", "right"),
                ],
                [
                    self._switch_keyboard_button(
                        "numeric",
                        KEYBOARD_BUTTON_TEXT["numeric"],
                        self._default_width_large,
                        "qwerty",
                    ),
                    self._space_bar(),
                    self._go(self._default_width_large),
                ],
            ],
            # ---- QWERTY (uppercase, DE) ----
            "qwertyUpper_DE": [
                ["Q", "W", "E", "R", "T", "Z", "U", "I", "O", "P"],
                [
                    self._spacer(),
                    "A",
                    "S",
                    "D",
                    "F",
                    "G",
                    "H",
                    "J",
                    "K",
                    "L",
                    self._spacer(),
                ],
                [
                    self._shift_key("qwerty"),
                    "Y",
                    "X",
                    "C",
                    "V",
                    "B",
                    "N",
                    "M",
                    self._arrow("left", "middle"),
                    self._arrow("right", "right"),
                ],
                [
                    self._switch_keyboard_button(
                        "numeric",
                        KEYBOARD_BUTTON_TEXT["numeric"],
                        self._default_width_large,
                        "qwerty",
                    ),
                    self._space_bar(),
                    self._go(self._default_width_large),
                ],
            ],
            # ---- QWERTY (lowercase) ----
            "qwerty": [
                ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
                [
                    self._spacer(),
                    "a",
                    "s",
                    "d",
                    "f",
                    "g",
                    "h",
                    "j",
                    "k",
                    "l",
                    self._spacer(),
                ],
                [
                    self._shift_key("qwertyUpper", "qwerty"),
                    "z",
                    "x",
                    "c",
                    "v",
                    "b",
                    "n",
                    "m",
                    self._arrow("left", "middle"),
                    self._arrow("right", "right"),
                ],
                [
                    self._switch_keyboard_button(
                        "numeric",
                        KEYBOARD_BUTTON_TEXT["numeric"],
                        self._default_width_large,
                        "qwerty",
                    ),
                    self._space_bar(),
                    self._go(self._default_width_large),
                ],
            ],
            # ---- QWERTY (lowercase, DE) ----
            "qwerty_DE": [
                ["q", "w", "e", "r", "t", "z", "u", "i", "o", "p"],
                [
                    self._spacer(),
                    "a",
                    "s",
                    "d",
                    "f",
                    "g",
                    "h",
                    "j",
                    "k",
                    "l",
                    self._spacer(),
                ],
                [
                    self._shift_key("qwertyUpper_DE", "qwerty_DE"),
                    "y",
                    "x",
                    "c",
                    "v",
                    "b",
                    "n",
                    "m",
                    self._arrow("left", "middle"),
                    self._arrow("right", "right"),
                ],
                [
                    self._switch_keyboard_button(
                        "numeric",
                        KEYBOARD_BUTTON_TEXT["numeric"],
                        self._default_width_large,
                        "qwerty",
                    ),
                    self._space_bar(),
                    self._go(self._default_width_large),
                ],
            ],
            # ---- QWERTY (lowercase, FR) ----
            "qwerty_FR": [
                ["a", "z", "e", "r", "t", "y", "u", "i", "o", "p"],
                ["q", "s", "d", "f", "g", "h", "j", "k", "l", "m"],
                [
                    self._shift_key("qwertyUpper_FR", "qwerty_FR"),
                    self._spacer(),
                    "w",
                    "x",
                    "c",
                    "v",
                    "b",
                    "n",
                    self._arrow("left", "middle"),
                    self._arrow("right", "right"),
                ],
                [
                    self._switch_keyboard_button(
                        "numeric",
                        KEYBOARD_BUTTON_TEXT["numeric"],
                        self._default_width_large,
                        "qwerty",
                    ),
                    self._space_bar(),
                    self._go(self._default_width_large),
                ],
            ],
            # ---- Email layouts ----
            "email": [
                ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
                [
                    self._spacer(),
                    "a",
                    "s",
                    "d",
                    "f",
                    "g",
                    "h",
                    "j",
                    "k",
                    "l",
                    self._spacer(),
                ],
                [
                    self._shift_key("emailUpper", "email"),
                    "z",
                    "x",
                    "c",
                    "v",
                    "b",
                    "n",
                    "m",
                    self._arrow("left", "middle"),
                    self._arrow("right", "right"),
                ],
                email_bottom_row,
            ],
            "emailUpper": [
                ["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P"],
                [
                    self._spacer(),
                    "A",
                    "S",
                    "D",
                    "F",
                    "G",
                    "H",
                    "J",
                    "K",
                    "L",
                    self._spacer(),
                ],
                [
                    self._shift_key("email"),
                    "Z",
                    "X",
                    "C",
                    "V",
                    "B",
                    "N",
                    "M",
                    self._arrow("left", "middle"),
                    self._arrow("right", "right"),
                ],
                email_bottom_row,
            ],
            "email_DE": [
                ["q", "w", "e", "r", "t", "z", "u", "i", "o", "p"],
                [
                    self._spacer(),
                    "a",
                    "s",
                    "d",
                    "f",
                    "g",
                    "h",
                    "j",
                    "k",
                    "l",
                    self._spacer(),
                ],
                [
                    self._shift_key("emailUpper_DE", "email_DE"),
                    "y",
                    "x",
                    "c",
                    "v",
                    "b",
                    "n",
                    "m",
                    self._arrow("left", "middle"),
                    self._arrow("right", "right"),
                ],
                email_bottom_row,
            ],
            "emailUpper_DE": [
                ["Q", "W", "E", "R", "T", "Z", "U", "I", "O", "P"],
                [
                    self._spacer(),
                    "A",
                    "S",
                    "D",
                    "F",
                    "G",
                    "H",
                    "J",
                    "K",
                    "L",
                    self._spacer(),
                ],
                [
                    self._shift_key("email_DE"),
                    "Y",
                    "X",
                    "C",
                    "V",
                    "B",
                    "N",
                    "M",
                    self._arrow("left", "middle"),
                    self._arrow("right", "right"),
                ],
                email_bottom_row,
            ],
            "email_FR": [
                ["a", "z", "e", "r", "t", "y", "u", "i", "o", "p"],
                ["q", "s", "d", "f", "g", "h", "j", "k", "l", "m"],
                [
                    self._shift_key("emailUpper_FR", "email_FR"),
                    self._spacer(),
                    "w",
                    "x",
                    "c",
                    "v",
                    "b",
                    "n",
                    self._arrow("left", "middle"),
                    self._arrow("right", "right"),
                ],
                email_bottom_row,
            ],
            "emailUpper_FR": [
                ["A", "Z", "E", "R", "T", "Y", "U", "I", "O", "P"],
                ["Q", "S", "D", "F", "G", "H", "J", "K", "L", "M"],
                [
                    self._shift_key("email_FR"),
                    self._spacer(),
                    "W",
                    "X",
                    "C",
                    "V",
                    "B",
                    "N",
                    self._arrow("left", "middle"),
                    self._arrow("right", "right"),
                ],
                email_bottom_row,
            ],
            "emailNumeric": [
                ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
                ["$", "+", "~", ".", "!", "#", "%", "&", "'", "*"],
                [
                    "/",
                    "=",
                    "?",
                    "^",
                    "`",
                    "{",
                    "|",
                    "}",
                    self._arrow("left", "middle"),
                    self._arrow("right", "right"),
                ],
                [
                    self._switch_keyboard_button(
                        "email", KEYBOARD_BUTTON_TEXT["qwerty"]
                    ),
                    {"keyWidth": 0, "text": "."},
                    {"keyWidth": self._default_width_large, "text": "@"},
                    "_",
                    "-",
                    self._go(),
                ],
            ],
            # ---- Hex keyboard ----
            "hex": [
                ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
                [
                    "A",
                    "B",
                    "C",
                    "D",
                    "E",
                    "F",
                    self._arrow("left", "bottom"),
                    self._arrow("right", "bottom"),
                    self._go(),
                ],
            ],
            # ---- IP keyboard ----
            "ip": [
                ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
                [
                    ".",
                    self._spacer(),
                    self._arrow("left", "bottom"),
                    self._arrow("right", "bottom"),
                    self._go(self._default_width_large),
                ],
            ],
            # ---- Numeric keyboard ----
            "numeric": [
                ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
                [".", "-", "+", "/", "=", "_", "@", "#", "$", "%"],
                [
                    self._switch_keyboard_button(
                        "numericShift",
                        KEYBOARD_BUTTON_TEXT["numericMore"],
                        self._default_width_large,
                    ),
                    ":",
                    "&",
                    ",",
                    "?",
                    "!",
                    "*",
                    self._arrow("left", "middle"),
                    self._arrow("right", "right"),
                ],
                [
                    self._switch_keyboard_button(
                        "qwerty",
                        KEYBOARD_BUTTON_TEXT["qwerty"],
                        self._default_width_large,
                    ),
                    self._space_bar(),
                    self._go(self._default_width_large),
                ],
            ],
            # ---- Numeric shift keyboard ----
            "numericShift": [
                ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
                [";", '"', "`", "'", "~", "^", "\\", "|", "[", "]"],
                [
                    self._switch_keyboard_button(
                        "numeric",
                        KEYBOARD_BUTTON_TEXT["numericBack"],
                        self._default_width_large,
                    ),
                    "<",
                    ">",
                    "{",
                    "}",
                    "(",
                    ")",
                    self._spacer(),
                    self._arrow("left", "middle"),
                    self._arrow("right", "right"),
                ],
                [
                    self._switch_keyboard_button(
                        "qwerty",
                        KEYBOARD_BUTTON_TEXT["qwerty"],
                        self._default_width_large,
                    ),
                    self._space_bar(),
                    self._go(self._default_width_large),
                ],
            ],
        }

        # PL uses DE layout
        self.keyboards["qwerty_PL"] = self.keyboards["qwerty_DE"]
        self.keyboards["qwertyUpper_PL"] = self.keyboards["qwertyUpper_DE"]
        self.keyboards["email_PL"] = self.keyboards["email_DE"]
        self.keyboards["emailUpper_PL"] = self.keyboards["emailUpper_DE"]

    # ==================================================================
    # Input updated callback
    # ==================================================================

    def _input_updated(self) -> None:
        """Notify all keys that the textinput value has changed."""
        for i, row in enumerate(self.keyboard):
            if i < len(self.key_info):
                row_info = self.key_info[i]
                for j, key in enumerate(row):
                    if j < len(row_info):
                        key_info = row_info[j]
                        input_updated_fn = key_info.get("inputUpdated")
                        if input_updated_fn is not None:
                            input_updated_fn(key)

    # ==================================================================
    # Layout
    # ==================================================================

    def _layout(self) -> None:
        """Compute positions for all key widgets in the current layout."""
        bx, by, bw, bh = self.get_bounds()
        x = self._row_offset_x
        y = by
        row_width = self._keyboard_width

        for i, row in enumerate(self.keyboard):
            if i >= len(self.key_info):
                break
            row_info = self.key_info[i]

            # First pass: count spacers and compute non-spacer total width
            spacers = 0
            non_spacer_key_width = 0
            for j, key in enumerate(row):
                if j >= len(row_info):
                    break
                ki = row_info[j]
                kw = self._default_width
                if ki.get("keyWidth") == 0:
                    spacers += 1
                else:
                    if ki.get("keyWidth") is not None:
                        kw = int(ki["keyWidth"])
                    non_spacer_key_width += kw

            # Second pass: layout each key
            if spacers > 0:
                extra_spacer_pixels = (row_width - non_spacer_key_width) % spacers
                spacer_width = (row_width - non_spacer_key_width) // spacers
            else:
                extra_spacer_pixels = 0
                spacer_width = 0

            x = self._row_offset_x
            number_of_spacers = 0

            for j, key in enumerate(row):
                if j >= len(row_info):
                    break
                ki = row_info[j]

                if ki.get("keyWidth") == 0:
                    # Spacer key
                    number_of_spacers += 1
                    if number_of_spacers == 1 and extra_spacer_pixels:
                        key_width = spacer_width + extra_spacer_pixels
                    else:
                        key_width = spacer_width
                else:
                    if ki.get("keyWidth") is not None:
                        key_width = int(ki["keyWidth"])
                    else:
                        key_width = self._default_width

                key.set_bounds(x, y, key_width, self._default_height)

                # Determine key position style based on grid location
                style = key.get_style()
                key_type = "key_"
                if style and (style.startswith("key") or style.startswith("spacer")):
                    if ki.get("spacer"):
                        key_type = "spacer_"

                    num_rows = len(self.keyboard)
                    num_cols = len(row)

                    if i == 0 and j == 0:
                        location = "topLeft"
                    elif i == 0 and j < num_cols - 1:
                        location = "top"
                    elif i == 0 and j == num_cols - 1:
                        location = "topRight"
                    elif i < num_rows - 1 and j == 0:
                        location = "left"
                    elif i < num_rows - 1 and j < num_cols - 1:
                        location = "middle"
                    elif i < num_rows - 1 and j == num_cols - 1:
                        location = "right"
                    elif i == num_rows - 1 and j == 0:
                        location = "bottomLeft"
                    elif i == num_rows - 1 and j < num_cols - 1:
                        location = "bottom"
                    else:
                        location = "bottomRight"

                    if ki.get("fontSize") == "small" and key_type == "key_":
                        location = location + "_small"

                    key.set_style(key_type + location)

                x += key_width

            # Move to the next row
            y += self._default_height

    # ==================================================================
    # Set keyboard layout
    # ==================================================================

    def set_keyboard(self, kb_type: Union[str, LayoutSpec]) -> None:
        """
        Switch the keyboard to a new layout.

        Parameters
        ----------
        kb_type : str or list
            Either a pre-defined keyboard name or a user-defined
            layout table (list of rows of key specs).
        """
        # Unlink current widgets from their parent
        if hasattr(self, "widgets") and self.widgets:
            for key, widget in (
                self.widgets.items()
                if isinstance(self.widgets, dict)
                else enumerate(self.widgets)
            ):
                if hasattr(widget, "parent"):
                    widget.parent = None

        # Reset internal state
        self._widgets: Optional[List[Widget]] = []
        self.keyboard = []
        self.key_info = []

        keyboard_spec: Optional[LayoutSpec] = None

        if isinstance(kb_type, list):
            # User-defined keyboard layout
            keyboard_spec = kb_type
        elif isinstance(kb_type, str):
            # Try locale-specific variant first
            locale_suffix = self._get_locale_suffix()
            localized_name = kb_type + "_" + locale_suffix if locale_suffix else None

            if localized_name and localized_name in self.keyboards:
                keyboard_spec = self.keyboards[localized_name]
            elif kb_type in self.keyboards:
                keyboard_spec = self.keyboards[kb_type]
            else:
                keyboard_spec = self.keyboards.get("qwerty")

        if keyboard_spec is None:
            log.error("No keyboard layout found for type: %s", kb_type)
            return

        keyboard_table: List[List[Widget]] = []
        info_table: List[List[Dict[str, Any]]] = []
        widget_table: List[Widget] = []

        for row_spec in keyboard_spec:
            row_buttons, row_info = self._buttons_from_chars(row_spec)
            keyboard_table.append(row_buttons)
            info_table.append(row_info)
            for widget in row_buttons:
                widget_table.append(widget)

        self.keyboard = keyboard_table
        self._widgets = widget_table
        self.key_info = info_table

        # Set parent linkage for all key widgets
        # Store widgets as a dict for Group compatibility
        self.widgets = {}
        for idx, widget in enumerate(widget_table):
            widget.parent = self
            self.widgets[f"key_{idx}"] = widget

        # Update input checkers (e.g., done button styling)
        self._input_updated()

        self.re_layout()

    # ==================================================================
    # Backspace button (not part of keyboard widget, but always paired)
    # ==================================================================

    def backspace(self) -> Widget:
        """
        Return a standard backspace Button widget.

        Not actually part of the Keyboard widget itself, but always
        paired with a keyboard in the UI.  Delivered here to keep
        applet code cleaner.
        """
        from jive.ui.button import Button as UIButton

        icon = Icon("button_keyboard_back")

        def on_press() -> int:
            try:
                from jive.ui.framework import framework as fw

                e = Event(int(EVENT_CHAR_PRESS), unicode=ord("\b"))
                fw.play_sound("SELECT")
                fw.dispatch_event(None, e)
            except (ImportError, AttributeError):
                pass
            return int(EVENT_CONSUME)

        def on_hold() -> int:
            try:
                from jive.ui.framework import framework as fw

                fw.play_sound("SELECT")
                fw.push_action("clear")
            except (ImportError, AttributeError):
                pass
            return int(EVENT_CONSUME)

        btn = UIButton(icon, action=on_press, hold_action=on_hold)
        return icon  # Return the icon widget (which has the Button listeners attached)

    # ==================================================================
    # Key creation helpers
    # ==================================================================

    def _buttons_from_chars(
        self, char_table: RowSpec
    ) -> Tuple[List[Widget], List[Dict[str, Any]]]:
        """
        Convert a row of key specs into Button widgets with metadata.

        Parameters
        ----------
        char_table : list
            A list of key specs — either plain character strings or
            dicts with ``text``, ``icon``, ``keyWidth``, ``callback``,
            ``spacer``, ``fontSize``, ``inputUpdated`` keys.

        Returns
        -------
        tuple of (buttons, info)
            *buttons* is a list of Widget (Label wrapped in Button
            listeners); *info* is the corresponding metadata dicts.
        """
        from jive.ui.button import Button as UIButton

        button_table: List[Widget] = []
        info_table: List[Dict[str, Any]] = []

        for v in char_table:
            if isinstance(v, dict):
                key_style = v.get("style", "key")
                if v.get("icon") is not None:
                    label_widget = v["icon"]
                else:
                    label_widget = Label(key_style, v.get("text", ""))

                callback = v.get("callback")
                if callback is None:
                    text = v.get("text", "")

                    def _make_char_callback(ch: str) -> Callable[[], int]:
                        def _cb() -> int:
                            try:
                                from jive.ui.framework import framework as fw

                                e = Event(int(EVENT_CHAR_PRESS), unicode=ord(ch))
                                fw.dispatch_event(None, e)
                            except (ImportError, AttributeError):
                                pass
                            if self.last:
                                self.set_keyboard(self.last)
                                self.last = None
                            return int(EVENT_CONSUME)

                        return _cb

                    callback = _make_char_callback(text)

                btn = UIButton(label_widget, action=callback)
                button_table.append(label_widget)
                info_table.append(dict(v))
            else:
                # Plain character string
                label_widget = Label("key", v)

                def _make_char_callback_plain(ch: str) -> Callable[[], int]:
                    def _cb() -> int:
                        try:
                            from jive.ui.framework import framework as fw

                            e = Event(int(EVENT_CHAR_PRESS), unicode=ord(ch))
                            fw.dispatch_event(None, e)
                        except (ImportError, AttributeError):
                            pass
                        if self.last:
                            self.set_keyboard(self.last)
                            self.last = None
                        return int(EVENT_CONSUME)

                    return _cb

                btn = UIButton(label_widget, action=_make_char_callback_plain(v))
                button_table.append(label_widget)
                info_table.append({})

        return button_table, info_table

    # ------------------------------------------------------------------
    # Special key builders
    # ------------------------------------------------------------------

    def _arrow(
        self,
        direction: str,
        position: Optional[str] = None,
        key_width: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Build an arrow-key spec dict."""
        if position is None:
            position = "bottom"
        style = f"arrow_{direction}_{position}"
        cursor_action = f"cursor_{direction}"

        if key_width is None:
            key_width = self._default_width

        def _callback() -> int:
            try:
                from jive.ui.framework import framework as fw

                fw.push_action(cursor_action)
            except (ImportError, AttributeError):
                pass
            return int(EVENT_CONSUME)

        return {
            "icon": Icon(style),
            "keyWidth": key_width,
            "callback": _callback,
        }

    def _macro_key_button(self, key_text: str, key_width: int = 0) -> Dict[str, Any]:
        """Build a macro-key spec that types multiple characters."""

        def _callback() -> int:
            try:
                from jive.ui.framework import framework as fw

                for ch in key_text:
                    e = Event(int(EVENT_CHAR_PRESS), unicode=ord(ch))
                    fw.dispatch_event(None, e)
            except (ImportError, AttributeError):
                pass
            return int(EVENT_CONSUME)

        return {
            "text": key_text,
            "keyWidth": key_width,
            "style": "key",
            "fontSize": "small",
            "callback": _callback,
        }

    def _switch_keyboard_button(
        self,
        kb_type: str,
        key_text: str,
        key_width: int = 0,
        switch_back: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build a keyboard-switch button spec."""

        def _callback() -> int:
            self.kb_type = kb_type
            self.pushed = key_text
            self.play_sound("SELECT")
            self.set_keyboard(kb_type)
            # Unset any one-key shift behaviour
            self.last = None
            return int(EVENT_CONSUME)

        return {
            "text": key_text,
            "fontSize": "small",
            "keyWidth": key_width,
            "callback": _callback,
        }

    def _go(self, key_width: int = 0) -> Dict[str, Any]:
        """Build a 'done' / 'go' button spec."""

        def _callback() -> int:
            if self.textinput is not None and not self.textinput.is_valid():
                return int(EVENT_CONSUME)
            try:
                from jive.ui.framework import framework as fw

                fw.push_action("finish_operation")
            except (ImportError, AttributeError):
                pass
            return int(EVENT_CONSUME)

        def _input_updated_fn(label_widget: Widget) -> None:
            if self.textinput is not None and self.textinput.is_valid():
                label_widget.set_style("done")
            else:
                label_widget.set_style("doneDisabled")

        return {
            "icon": Group("done", {"icon": Icon("icon"), "text": Label("text")}),
            "keyWidth": key_width,
            "callback": _callback,
            "inputUpdated": _input_updated_fn,
        }

    def _spacer(self, key_width: int = 0) -> Dict[str, Any]:
        """Build a spacer key spec (invisible, fills remaining space)."""

        def _callback() -> int:
            return int(EVENT_CONSUME)

        return {
            "text": "",
            "keyWidth": key_width,
            "spacer": 1,
            "callback": _callback,
        }

    def _shift_key(
        self, switch_to: str, switch_back: Optional[str] = None
    ) -> Dict[str, Any]:
        """Build a shift-key spec."""
        if switch_back:
            style = "shiftOff"
        else:
            style = "shiftOn"

        def _callback() -> int:
            self.set_keyboard(switch_to)
            self.play_sound("SELECT")
            if switch_back:
                self.last = switch_back
            else:
                self.last = None
            return int(EVENT_CONSUME)

        return {
            "icon": Icon(style),
            "callback": _callback,
        }

    def _space_bar(self, key_width: int = 0) -> Dict[str, Any]:
        """Build a space-bar key spec."""

        def _callback() -> int:
            try:
                from jive.ui.framework import framework as fw

                e = Event(int(EVENT_CHAR_PRESS), unicode=ord(" "))
                fw.dispatch_event(None, e)
            except (ImportError, AttributeError):
                pass
            return int(EVENT_CONSUME)

        return {
            "icon": Label("space"),
            "keyWidth": key_width,
            "callback": _callback,
        }

    # ------------------------------------------------------------------
    # Locale helper
    # ------------------------------------------------------------------

    @staticmethod
    def _get_locale_suffix() -> Optional[str]:
        """
        Return the locale suffix (e.g. ``'DE'``, ``'FR'``) for
        keyboard layout selection, or ``None`` if no locale is set.
        """
        try:
            from jive.utils.locale import get_locale

            loc = get_locale()
            if loc:
                return str(loc)
        except (ImportError, AttributeError):
            pass
        return None

    # ------------------------------------------------------------------
    # Keyboard type queries
    # ------------------------------------------------------------------

    def get_keyboard_type(self) -> Union[str, LayoutSpec]:
        """Return the current keyboard type."""
        return self.kb_type

    def get_available_keyboards(self) -> List[str]:
        """Return a sorted list of all pre-defined keyboard names."""
        return sorted(self.keyboards.keys())

    # ------------------------------------------------------------------
    # Iterate over child widgets (for drawing)
    # ------------------------------------------------------------------

    def iterate(self, closure: Callable[..., None]) -> None:
        """Iterate over all key widgets, calling *closure* for each."""
        if self._widgets:
            for widget in self._widgets:
                closure(widget)

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        num_keys = sum(len(row) for row in self.keyboard) if self.keyboard else 0
        return (
            f"Keyboard(style={self.get_style()!r}, "
            f"type={self.kb_type!r}, "
            f"keys={num_keys})"
        )

    def __str__(self) -> str:
        return self.__repr__()
