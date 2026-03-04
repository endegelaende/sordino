"""
jive.ui.textarea — Textarea widget for the Jivelite Python3 port.

Ported from ``Textarea.lua`` and ``jive_textarea.c`` in the original
jivelite project.

A Textarea widget displays multi-line text with automatic word-wrapping
and optional scrollbar support. It supports:

* **Word wrapping** — text is automatically wrapped to fit the widget width
* **Scrolling** — scroll up/down through text that exceeds visible area
* **Shadow text** — optional shadow colour for text rendering
* **Alignment** — text alignment (left, center, top, etc.)
* **Background tile** — optional bgImg behind the text
* **Scrollbar** — integrated scrollbar widget when content overflows
* **Pixel-offset scrolling** — smooth scrolling support via drag/flick
* **Header widget** — support for being embedded as a header in a Menu

Copyright 2010 Logitech. All Rights Reserved. (original Lua/C code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import math
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    List,
    Optional,
    Tuple,
)

from jive.ui.constants import (
    ALIGN_BOTTOM,
    ALIGN_CENTER,
    ALIGN_TOP,
    ALIGN_TOP_LEFT,
    EVENT_CONSUME,
    EVENT_IR_DOWN,
    EVENT_IR_REPEAT,
    EVENT_MOUSE_ALL,
    EVENT_MOUSE_DOWN,
    EVENT_MOUSE_DRAG,
    EVENT_MOUSE_HOLD,
    EVENT_MOUSE_MOVE,
    EVENT_MOUSE_PRESS,
    EVENT_MOUSE_UP,
    EVENT_SCROLL,
    EVENT_UNUSED,
    LAYER_ALL,
    LAYER_CONTENT,
    WH_FILL,
    WH_NIL,
    XY_NIL,
)
from jive.ui.widget import Widget
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.ui.event import Event
    from jive.ui.font import Font
    from jive.ui.surface import Surface
    from jive.ui.tile import JiveTile  # type: ignore[attr-defined]

__all__ = ["Textarea"]

log = logger("jivelite.ui")


class Textarea(Widget):
    """
    A multi-line text display widget with word-wrapping and scrolling.

    Parameters
    ----------
    style : str
        The style key used to look up skin parameters.
    text : str
        The initial text to display.
    """

    __slots__ = (
        "text",
        "top_line",
        "visible_lines",
        "num_lines",
        "line_height",
        "pixel_offset_y",
        "pixel_offset_y_header_widget",
        "current_shift_direction",
        "hide_scrollbar",
        "is_header_widget",
        "is_menu_child",
        "_font",
        "_fg",
        "_sh",
        "_is_sh",
        "_bg_tile",
        "_text_offset",
        "_y_offset",
        "_align",
        "_lines",
        "_line_width",
        "_has_scrollbar",
        "scrollbar",
        "drag_origin",
        "drag_y_since_shift",
        "slider_drag_in_progress",
        "body_drag_in_progress",
    )

    def __init__(self, style: str, text: str = "") -> None:
        if not isinstance(style, str):
            raise TypeError(f"style must be a string, got {type(style).__name__}")

        super().__init__(style)

        # Public state
        self.text: str = text
        self.top_line: int = 0
        self.visible_lines: int = 0
        self.num_lines: int = 0
        self.line_height: int = 0
        self.pixel_offset_y: int = 0
        self.pixel_offset_y_header_widget: int = 0
        self.current_shift_direction: int = 0
        self.hide_scrollbar: bool = False
        self.is_header_widget: bool = False
        self.is_menu_child: bool = False

        # Internal peer state (mirroring TextareaWidget in C)
        self._font: Optional[Font] = None
        self._fg: int = 0x000000FF  # black
        self._sh: int = 0xFFFFFFFF  # white
        self._is_sh: bool = False
        self._bg_tile: Optional[JiveTile] = None
        self._text_offset: int = 0
        self._y_offset: int = 0
        self._align: int = int(ALIGN_TOP_LEFT)

        # Word-wrap state
        self._lines: List[int] = []  # indices into self.text for start of each line
        self._line_width: int = 0
        self._has_scrollbar: bool = False

        # Scrollbar child
        from jive.ui.slider import Scrollbar

        self.scrollbar: Scrollbar = Scrollbar(
            "scrollbar",
            closure=lambda sb, value, done: self._scroll_to(value),
        )
        self.scrollbar.parent = self

        # Drag state
        self.drag_origin: Dict[str, Any] = {}  # type: ignore[name-defined]
        self.drag_y_since_shift: int = 0
        self.slider_drag_in_progress: bool = False
        self.body_drag_in_progress: bool = False

        # Event listeners
        self.add_action_listener("page_up", self, Textarea._page_up_action)
        self.add_action_listener("page_down", self, Textarea._page_down_action)

        self.add_listener(
            EVENT_SCROLL | EVENT_MOUSE_ALL | EVENT_IR_DOWN | EVENT_IR_REPEAT,
            lambda event: self._event_handler(event),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_text(self) -> str:
        """Return the text contained in this Textarea."""
        return self.text

    getText = get_text

    def set_value(self, text: str) -> None:
        """Set the text in the Textarea."""
        old_text = self.text
        if text != old_text:
            self.text = text
            self._invalidate()
            self.re_layout()

    setValue = set_value

    def set_hide_scrollbar(self, setting: bool) -> None:
        """Control scrollbar visibility."""
        self.hide_scrollbar = setting

    def set_is_menu_child(self, setting: bool) -> None:
        """Mark this textarea as embedded within a menu item."""
        self.is_menu_child = setting

    def is_scrollable(self) -> bool:
        """Return True if the textarea content is scrollable."""
        return True

    def set_pixel_offset_y(self, value: int) -> None:
        """Set the pixel offset for smooth scrolling."""
        self.pixel_offset_y = value + self.pixel_offset_y_header_widget

    # ------------------------------------------------------------------
    # Scrolling
    # ------------------------------------------------------------------

    def scroll_by(self, scroll: int) -> None:
        """Scroll by *scroll* lines (negative = up, positive = down)."""
        self._scroll_to(self.top_line + scroll)

    scrollBy = scroll_by

    def _scroll_to(self, top_line: int) -> None:
        if top_line < 0:
            top_line = 0
        if top_line + self.visible_lines > self.num_lines:
            top_line = self.num_lines - self.visible_lines
        if top_line < 0:
            top_line = 0

        self.top_line = top_line
        self.scrollbar.set_scrollbar(
            0, self.num_lines, self.top_line + 1, self.visible_lines
        )
        self.re_draw()

    def _page_up_action(self) -> int:
        self.scroll_by(-(self.visible_lines - 1))
        return EVENT_CONSUME

    def _page_down_action(self) -> int:
        self.scroll_by(self.visible_lines - 1)
        return EVENT_CONSUME

    # ------------------------------------------------------------------
    # Drag support
    # ------------------------------------------------------------------

    def reset_drag_data(self) -> None:
        """Reset drag/pixel-offset state."""
        self.set_pixel_offset_y(0)
        self.drag_y_since_shift = 0

    def handle_drag(self, drag_amount_y: int, by_item_only: bool = False) -> None:
        """Handle drag gesture for smooth scrolling."""
        if drag_amount_y == 0:
            return

        self.drag_y_since_shift += drag_amount_y

        if self.line_height > 0 and (
            (
                self.drag_y_since_shift > 0
                and self.drag_y_since_shift // self.line_height > 0
            )
            or (
                self.drag_y_since_shift < 0
                and self.drag_y_since_shift // self.line_height < 0
            )
        ):
            item_shift = self.drag_y_since_shift // self.line_height
            self.drag_y_since_shift = self.drag_y_since_shift % self.line_height

            if not by_item_only:
                self.set_pixel_offset_y(-1 * self.drag_y_since_shift)
            else:
                self.set_pixel_offset_y(0)

            if item_shift > 0 and self.current_shift_direction <= 0:
                self.current_shift_direction = 1
            elif item_shift < 0 and self.current_shift_direction >= 0:
                self.current_shift_direction = -1

            self.scroll_by(item_shift)

            if self.is_at_top() or self.is_at_bottom():
                self.reset_drag_data()
        else:
            if not by_item_only:
                self.set_pixel_offset_y(-1 * self.drag_y_since_shift)

            if self.is_at_bottom():
                self.reset_drag_data()

            self.re_draw()

    def is_at_bottom(self) -> bool:
        """Return True if scrolled to the bottom."""
        return self.top_line + self.visible_lines >= self.num_lines

    def is_at_top(self) -> bool:
        """Return True if scrolled to the top."""
        return self.top_line == 0

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def _event_handler(self, event: Event) -> int:
        etype = event.get_type()

        if etype == EVENT_SCROLL:
            self.scroll_by(event.get_scroll())
            return EVENT_CONSUME

        if etype == EVENT_IR_DOWN or etype == EVENT_IR_REPEAT:
            if event.is_ir_code("arrow_up") or event.is_ir_code("arrow_down"):  # type: ignore[attr-defined]
                scroll_amount = 1 if event.is_ir_code("arrow_down") else -1  # type: ignore[attr-defined]
                self.scroll_by(scroll_amount)
                return EVENT_CONSUME

        if etype in (EVENT_MOUSE_PRESS, EVENT_MOUSE_HOLD, EVENT_MOUSE_MOVE):
            return EVENT_CONSUME

        if etype == EVENT_MOUSE_DOWN:
            self.slider_drag_in_progress = False
            self.body_drag_in_progress = False
            return EVENT_CONSUME

        if etype in (EVENT_MOUSE_DRAG, EVENT_MOUSE_DOWN):
            if self.scrollbar.mouse_inside(event) or (
                self.slider_drag_in_progress and etype != EVENT_MOUSE_DOWN
            ):
                self.slider_drag_in_progress = True
                self.set_pixel_offset_y(0)
                return self.scrollbar._event(event)
            else:
                if etype == EVENT_MOUSE_DOWN:
                    x, y = event.get_mouse()[:2]
                    self.drag_origin["x"] = x
                    self.drag_origin["y"] = y
                    self.current_shift_direction = 0
                else:
                    if self.drag_origin.get("y") is None:
                        x, y = event.get_mouse()[:2]
                        self.drag_origin["x"] = x
                        self.drag_origin["y"] = y

                    mouse_x, mouse_y = event.get_mouse()[:2]
                    drag_amount_y = self.drag_origin["y"] - mouse_y
                    self.drag_origin["x"] = mouse_x
                    self.drag_origin["y"] = mouse_y
                    self.handle_drag(drag_amount_y)

            return EVENT_CONSUME

        if etype == EVENT_MOUSE_UP:
            if self.slider_drag_in_progress:
                return self.scrollbar._event(event)

            self.drag_origin.clear()
            self.slider_drag_in_progress = False
            self.body_drag_in_progress = False
            return EVENT_CONSUME

        return EVENT_UNUSED

    # ------------------------------------------------------------------
    # Skin (jiveL_textarea_skin)
    # ------------------------------------------------------------------

    def re_skin(self) -> None:
        """Reset all textarea-specific cached skin state, then call super."""
        self._font = None
        self._fg = 0x000000FF
        self._sh = 0xFFFFFFFF
        self._is_sh = False
        self._bg_tile = None
        self._text_offset = 0
        self._y_offset = 0
        self._align = 0
        self.line_height = 0
        self.num_lines = 0
        self.visible_lines = 0
        self.top_line = 0
        self._lines = []
        super().re_skin()

    def _skin(self) -> None:
        from jive.ui.style import (
            style_align,
            style_color,
            style_font,
            style_int,
            style_tile,
        )

        self._widget_pack()

        font = style_font(self, "font")
        if font is not None:
            self._font = font

        color_val, is_set = style_color(self, "sh", 0xFFFFFFFF)
        self._sh = color_val
        self._is_sh = is_set  # type: ignore[assignment]

        fg_val, _ = style_color(self, "fg", 0x000000FF)
        self._fg = fg_val

        bg_tile = style_tile(self, "bgImg", None)
        if bg_tile is not self._bg_tile:
            self._bg_tile = bg_tile

        if self._font is not None:
            self.line_height = style_int(self, "lineHeight", self._font.height())
            self._text_offset = self._font.offset()
        else:
            self.line_height = style_int(self, "lineHeight", 16)
            self._text_offset = 0

        self._align = style_align(self, "align", int(ALIGN_TOP_LEFT))

        self._invalidate()

    # ------------------------------------------------------------------
    # Word wrapping (wordwrap from jive_textarea.c)
    # ------------------------------------------------------------------

    def _invalidate(self) -> None:
        """Clear word-wrap data, forcing recalculation on next layout."""
        self._lines = []
        self.num_lines = 0

    def _wordwrap(
        self, text: str, visible_lines: int, scrollbar_width: int, has_scrollbar: bool
    ) -> None:
        """
        Word-wrap *text* to fit the widget bounds.

        Populates ``self._lines`` with character indices marking the
        start of each wrapped line.
        """
        bx, by, bw, bh = self.get_bounds()
        pl, pt, pr, pb = self.get_padding()

        width = bw - pl - pr

        if width <= 0:
            self._lines = [0, len(text)]
            self.num_lines = 1
            return

        self._has_scrollbar = has_scrollbar
        if has_scrollbar and not self.is_header_widget:
            width -= scrollbar_width

        lines: List[int] = [0]
        ptr = 0
        word_break: Optional[int] = None
        line_width = 0

        while ptr < len(text):
            ch = text[ptr]

            if ch == "\n":
                # Line break
                ptr += 1
                word_break = None
                lines.append(ptr)
                line_width = 0
                continue

            # Word break characters
            if ch == "." and ptr + 1 < len(text) and text[ptr + 1] != " ":
                pass  # dot not followed by space — not a word break
            elif ch in (" ", ",", "-", "."):
                word_break = ptr + 1

            # Calculate width of this character
            if self._font is not None:
                char_width = self._font.width(text[ptr : ptr + 1])
            else:
                char_width = 8  # fallback

            line_width += char_width

            # Check if line exceeds width
            if line_width >= width and ptr > lines[-1]:
                # Need scrollbar?
                if (
                    not has_scrollbar
                    and len(lines) > visible_lines
                    and not (self.is_header_widget or self.hide_scrollbar)
                ):
                    return self._wordwrap(text, visible_lines, scrollbar_width, True)

                # Wrap at word break if available
                if word_break is not None and word_break > lines[-1]:
                    ptr = word_break
                    word_break = None

                # Trim newlines and leading spaces
                while ptr < len(text) and text[ptr] == "\n":
                    ptr += 1
                while ptr < len(text) and text[ptr] == " ":
                    ptr += 1

                lines.append(ptr)
                line_width = 0
                continue

            ptr += 1

        # Trailing sentinel
        num_lines = len(lines)

        # Check if scrollbar needed after wrap
        if (
            not has_scrollbar
            and num_lines > visible_lines
            and not (self.is_header_widget or self.hide_scrollbar)
        ):
            return self._wordwrap(text, visible_lines, scrollbar_width, True)

        # Store the line-end sentinel
        lines.append(len(text))
        self.num_lines = num_lines
        self._lines = lines

    # ------------------------------------------------------------------
    # Layout (jiveL_textarea_layout)
    # ------------------------------------------------------------------

    def _layout(self) -> None:
        if self._font is None:
            return

        bx, by, bw, bh = self.get_bounds()
        pl, pt, pr, pb = self.get_padding()

        # Measure scrollbar
        sw = 0
        sh = bh

        if self.scrollbar is not None:
            sb_bounds = self.scrollbar.get_preferred_bounds()
            if sb_bounds[2] is not None and sb_bounds[2] != WH_FILL:
                sw = sb_bounds[2]
            if sb_bounds[3] is not None and sb_bounds[3] != WH_FILL:
                sh = sb_bounds[3]

            sb_border = self.scrollbar.get_border()
            sw += sb_border[0] + sb_border[2]  # left + right
            sh += sb_border[1] + sb_border[3]  # top + bottom

        # Invalidate wordwrap if width changed
        if self._line_width != bw:
            self._invalidate()
            self._line_width = bw

        # Word wrap text
        text = str(self.text) if self.text is not None else ""
        if not text:
            self.num_lines = 0
            return

        if self.line_height <= 0:
            self.line_height = max(1, self._font.height())

        visible_lines = bh // self.line_height if self.line_height > 0 else 1

        if self.num_lines == 0:
            self._wordwrap(text, visible_lines, sw, False)

        # Vertical alignment
        widget_height = bh - pt - pb
        max_height = self.num_lines * self.line_height

        if max_height < widget_height:
            self._y_offset = (widget_height - max_height) // 2
        else:
            self._y_offset = 0

        # Clamp visible / top line
        if visible_lines > self.num_lines:
            visible_lines = self.num_lines

        if self.top_line + visible_lines > self.num_lines:
            self.top_line = max(0, self.num_lines - visible_lines)

        self.visible_lines = visible_lines

        # Position scrollbar
        if self.scrollbar is not None and self._has_scrollbar:
            sb_border = self.scrollbar.get_border()
            sx = bx + bw - sw + sb_border[0]
            sy = by + sb_border[1]
            s_w = sw - sb_border[0] - sb_border[2]
            s_h = sh - sb_border[1]

            self.scrollbar.set_bounds(sx, sy, s_w, s_h)
            self.scrollbar.set_scrollbar(
                0, self.num_lines, self.top_line + 1, visible_lines
            )

    # ------------------------------------------------------------------
    # Draw (jiveL_textarea_draw)
    # ------------------------------------------------------------------

    def draw(self, surface: Surface, layer: int = LAYER_ALL) -> None:
        draw_layer = layer & self._layer

        if not draw_layer or self.num_lines == 0:
            return

        bx, by, bw, bh = self.get_bounds()
        pl, pt, pr, pb = self.get_padding()

        # Background tile
        if self._bg_tile is not None:
            self._bg_tile.blit(surface, bx, by, bw, bh)

        # Clip to widget bounds
        clip_y = by + pt
        clip_h = bh - pt

        if self.is_header_widget:
            y_offset = self._y_offset
            parent = self.get_parent()
            if parent is not None:
                try:
                    _, _, _, ph = parent.get_bounds()
                    clip_h = ph - pt - pb
                except Exception as exc:
                    log.warning("get_bounds for clip: %s", exc)
        else:
            y_offset = 0
            clip_h = bh - pt

        surface.push_clip(bx, clip_y, bw, clip_h)

        try:
            text = str(self.text) if self.text is not None else ""
            if not text or self._font is None:
                return

            y = by + pt - self._text_offset + y_offset

            top_line = self.top_line
            bottom_line = top_line + self.visible_lines

            for i in range(top_line, min(bottom_line + 1, self.num_lines)):
                line_start = self._lines[i]
                line_end = self._lines[i + 1] if i + 1 < len(self._lines) else len(text)

                # Get line text, strip trailing newline
                line_text = text[line_start:line_end]
                if line_text.endswith("\n"):
                    line_text = line_text[:-1]

                if not line_text:
                    y += self.line_height
                    continue

                # Compute x position based on alignment
                x = bx + pl
                align = self._align
                if align in (int(ALIGN_CENTER), int(ALIGN_TOP), int(ALIGN_BOTTOM)):
                    line_w = self._font.width(line_text)
                    x = Widget.halign(align, bx + pl, bw - pl - pr, line_w)

                # Shadow text
                if self._is_sh:
                    from jive.ui.surface import Surface as SurfaceClass

                    sh_surf = self._font.render(line_text, self._sh)
                    if sh_surf is not None:
                        if not isinstance(sh_surf, SurfaceClass):
                            sh_surf = SurfaceClass(sh_surf)  # type: ignore[assignment]
                        surface.blit(sh_surf, x + 1, y + 1)  # type: ignore[arg-type]

                # Foreground text
                from jive.ui.surface import Surface as SurfaceClass

                fg_surf = self._font.render(line_text, self._fg)
                if fg_surf is not None:
                    if not isinstance(fg_surf, SurfaceClass):
                        fg_surf = SurfaceClass(fg_surf)  # type: ignore[assignment]
                    surface.blit(fg_surf, x, y)  # type: ignore[arg-type]

                y += self.line_height

        finally:
            surface.pop_clip()

        # Draw scrollbar
        if self._has_scrollbar and not self.is_header_widget:
            if self.scrollbar is not None:
                self.scrollbar.draw(surface, layer)

    # ------------------------------------------------------------------
    # Preferred bounds (jiveL_textarea_get_preferred_bounds)
    # ------------------------------------------------------------------

    def get_preferred_bounds(
        self,
    ) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[int]]:
        self.check_layout()

        if self.num_lines == 0:
            return (None, None, 0, 0)

        bx, by, bw, bh = self.get_bounds()
        pl, pt, pr, pb = self.get_padding()

        w = bw + pl + pr
        h = (self.num_lines * self.line_height) + pt + pb

        pb_list = self.preferred_bounds
        px = pb_list[0] if pb_list[0] is not None and pb_list[0] != XY_NIL else None
        py = pb_list[1] if pb_list[1] is not None and pb_list[1] != XY_NIL else None
        pw = pb_list[2] if pb_list[2] is not None and pb_list[2] != WH_NIL else w
        ph = pb_list[3] if pb_list[3] is not None and pb_list[3] != WH_NIL else h

        return (px, py, pw, ph)

    # ------------------------------------------------------------------
    # jive_widget_pack — read common style properties
    # ------------------------------------------------------------------

    def _widget_pack(self) -> None:
        """
        Read common widget style properties: preferred bounds,
        padding, border, layer, z-order, hidden.
        """
        from jive.ui.style import style_insets, style_int

        sx = style_int(self, "x", XY_NIL)
        sy = style_int(self, "y", XY_NIL)
        sw = style_int(self, "w", WH_NIL)
        sh = style_int(self, "h", WH_NIL)

        self.preferred_bounds[0] = None if sx == XY_NIL else sx
        self.preferred_bounds[1] = None if sy == XY_NIL else sy
        self.preferred_bounds[2] = None if sw == WH_NIL else sw
        self.preferred_bounds[3] = None if sh == WH_NIL else sh

        pad = style_insets(self, "padding", [0, 0, 0, 0])
        self.padding[:] = pad[:4] if len(pad) >= 4 else pad + [0] * (4 - len(pad))

        bdr = style_insets(self, "border", [0, 0, 0, 0])
        self.border[:] = bdr[:4] if len(bdr) >= 4 else bdr + [0] * (4 - len(bdr))

        self._layer = style_int(self, "layer", int(LAYER_CONTENT))
        self._z_order = style_int(self, "zOrder", 0)
        self._hidden = bool(style_int(self, "hidden", 0))

    # ------------------------------------------------------------------
    # Iterate — textarea has scrollbar child
    # ------------------------------------------------------------------

    def iterate(
        self, closure: Callable[..., Any], include_hidden: bool = False
    ) -> None:
        """Iterate over child widgets (scrollbar)."""
        if self.scrollbar is not None:
            closure(self.scrollbar)

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        text_preview = ""
        if self.text:
            text_preview = str(self.text)[:20]
        return f"Textarea({text_preview!r}...)"

    def __str__(self) -> str:
        return self.__repr__()
