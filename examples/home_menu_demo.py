#!/usr/bin/env python3
"""
home_menu_demo.py — Visual Home Menu demo for the Jivelite Python port.

Opens an 800×480 window (JogglerSkin resolution) showing the home menu
populated with items from the ported applets: NowPlaying, SelectPlayer,
SlimBrowser, SlimDiscovery, SlimMenus, and standard JiveMain nodes.

Navigation:
    ↑/↓          Select menu item
    Enter/→      Activate item (opens sub-node or prints callback)
    Backspace/←  Go back to parent node
    ESC          Quit

Usage:
    python examples/home_menu_demo.py
"""

from __future__ import annotations

import os
import sys
import time

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import pygame
import pygame.font as _pgfont
import pygame.freetype as _pgft

from jive.ui.constants import (
    ALIGN_CENTER,
    ALIGN_LEFT,
    EVENT_ACTION,
    EVENT_CONSUME,
    EVENT_KEY_PRESS,
    EVENT_UNUSED,
    LAYER_CONTENT,
    LAYOUT_CENTER,
    LAYOUT_NORTH,
    LAYOUT_SOUTH,
    WH_FILL,
)
from jive.ui.font import Font
from jive.ui.framework import framework
from jive.ui.label import Label
from jive.ui.style import skin
from jive.ui.surface import Surface
from jive.ui.tile import Tile
from jive.ui.timer import Timer
from jive.ui.window import Window

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCREEN_W = 800
SCREEN_H = 480
TITLE = "Jivelite Python — Home Menu"
BG_COLOR = 0x111118FF
HEADER_BG = 0x1A1A2EFF
ITEM_BG = 0x16213EFF
ITEM_SEL_BG = 0x0F3460FF
ITEM_PRESSED_BG = 0x533483FF
TEXT_COLOR = 0xE0E0FFFF
TEXT_DIM = 0x8888AAFF
ACCENT = 0x00D2FFFF
DIVIDER_COLOR = 0x222244FF

# Home menu item definitions — simulating what the ported applets register
HOME_MENU_ITEMS = [
    {
        "id": "hm_myMusicSelector",
        "text": "My Music",
        "icon_char": "♫",
        "weight": 2,
        "node": "home",
        "has_children": True,
        "children_node": "_myMusic",
    },
    {
        "id": "radios",
        "text": "Internet Radio",
        "icon_char": "📻",
        "weight": 20,
        "node": "home",
        "has_children": True,
        "children_node": "radios",
    },
    {
        "id": "myApps",
        "text": "My Apps",
        "icon_char": "⬡",
        "weight": 30,
        "node": "home",
        "has_children": True,
        "children_node": "myApps",
    },
    {
        "id": "favorites",
        "text": "Favorites",
        "icon_char": "★",
        "weight": 35,
        "node": "home",
    },
    {
        "id": "selectPlayer",
        "text": "Select Player",
        "icon_char": "🔊",
        "weight": 45,
        "node": "home",
        "has_children": True,
        "children_node": "selectPlayer",
    },
    {
        "id": "extras",
        "text": "Extras",
        "icon_char": "✦",
        "weight": 50,
        "node": "home",
        "has_children": True,
        "children_node": "extras",
    },
    {
        "id": "settings",
        "text": "Settings",
        "icon_char": "⚙",
        "weight": 1005,
        "node": "home",
        "has_children": True,
        "children_node": "settings",
    },
]

MY_MUSIC_ITEMS = [
    {"id": "myMusicArtists", "text": "Artists", "icon_char": "👤", "weight": 10},
    {"id": "myMusicAlbums", "text": "Albums", "icon_char": "💿", "weight": 20},
    {"id": "myMusicGenres", "text": "Genres", "icon_char": "🎭", "weight": 30},
    {"id": "myMusicYears", "text": "Years", "icon_char": "📅", "weight": 40},
    {"id": "myMusicNewMusic", "text": "New Music", "icon_char": "✨", "weight": 50},
    {"id": "myMusicPlaylists", "text": "Playlists", "icon_char": "📋", "weight": 55},
    {"id": "myMusicSearch", "text": "Search", "icon_char": "🔍", "weight": 60},
    {"id": "myMusicRandomMix", "text": "Random Mix", "icon_char": "🎲", "weight": 70},
    {
        "id": "hm_otherLibrary",
        "text": "Switch Library",
        "icon_char": "🔄",
        "weight": 100,
    },
]

RADIO_ITEMS = [
    {"id": "radioLocal", "text": "Local Radio", "icon_char": "📍", "weight": 10},
    {"id": "radioMusic", "text": "Music", "icon_char": "🎵", "weight": 20},
    {"id": "radioSports", "text": "Sports", "icon_char": "⚽", "weight": 30},
    {"id": "radioNews", "text": "News", "icon_char": "📰", "weight": 40},
    {"id": "radioTalk", "text": "Talk", "icon_char": "💬", "weight": 50},
    {"id": "radioWorld", "text": "World", "icon_char": "🌍", "weight": 60},
]

SELECT_PLAYER_ITEMS = [
    {
        "id": "player_picore",
        "text": "piCorePlayer [Living Room]",
        "icon_char": "🔊",
        "weight": 10,
        "detail": "192.168.1.42 • Playing",
    },
    {
        "id": "player_squeezelite",
        "text": "Squeezelite [Kitchen]",
        "icon_char": "🔈",
        "weight": 20,
        "detail": "192.168.1.55 • Stopped",
    },
    {
        "id": "player_boom",
        "text": "Squeezebox Boom [Bedroom]",
        "icon_char": "🔇",
        "weight": 30,
        "detail": "192.168.1.68 • Off",
    },
]

SETTINGS_ITEMS = [
    {"id": "settingsAudio", "text": "Audio Settings", "icon_char": "🎚", "weight": 40},
    {
        "id": "settingsBrightness",
        "text": "Brightness",
        "icon_char": "☀",
        "weight": 45,
    },
    {
        "id": "screenSettings",
        "text": "Screen Settings",
        "icon_char": "🖥",
        "weight": 60,
    },
    {
        "id": "advancedSettings",
        "text": "Advanced Settings",
        "icon_char": "🔧",
        "weight": 105,
    },
    {"id": "settingsAbout", "text": "About", "icon_char": "ℹ", "weight": 110},
]

EXTRAS_ITEMS = [
    {
        "id": "extrasImageViewer",
        "text": "Image Viewer",
        "icon_char": "🖼",
        "weight": 20,
    },
    {
        "id": "extrasScreensavers",
        "text": "Screensavers",
        "icon_char": "🌙",
        "weight": 30,
    },
    {"id": "games", "text": "Games", "icon_char": "🎮", "weight": 70},
]

MY_APPS_ITEMS = [
    {"id": "appSpotify", "text": "Spotify", "icon_char": "🟢", "weight": 10},
    {"id": "appTidal", "text": "TIDAL", "icon_char": "🔵", "weight": 20},
    {"id": "appQobuz", "text": "Qobuz", "icon_char": "🟣", "weight": 30},
    {"id": "appDeezer", "text": "Deezer", "icon_char": "🟠", "weight": 40},
    {"id": "appYouTube", "text": "YouTube", "icon_char": "🔴", "weight": 50},
]

NODE_MAP = {
    "_myMusic": ("My Music", MY_MUSIC_ITEMS),
    "radios": ("Internet Radio", RADIO_ITEMS),
    "selectPlayer": ("Select Player", SELECT_PLAYER_ITEMS),
    "settings": ("Settings", SETTINGS_ITEMS),
    "extras": ("Extras", EXTRAS_ITEMS),
    "myApps": ("My Apps", MY_APPS_ITEMS),
}


# ---------------------------------------------------------------------------
# Font helper
# ---------------------------------------------------------------------------


def _resolve_font() -> str:
    _pgfont.init()
    for name in ("segoeui", "arial", "liberationsans", "dejavusans", "freesans"):
        path = _pgfont.match_font(name)
        if path:
            return path
    default = _pgft.get_default_font()
    if default:
        return default
    raise RuntimeError("No usable TrueType font found")


# ---------------------------------------------------------------------------
# HomeMenuApp — self-contained demo
# ---------------------------------------------------------------------------


class HomeMenuApp:
    """Self-contained home menu demo with keyboard navigation."""

    def __init__(self, screen: pygame.Surface, font_path: str) -> None:
        self.screen = screen
        self.font_path = font_path
        self.running = True
        self.clock = pygame.time.Clock()

        # Fonts
        self.font_title = pygame.font.Font(font_path, 26)
        self.font_item = pygame.font.Font(font_path, 22)
        self.font_detail = pygame.font.Font(font_path, 14)
        self.font_icon = pygame.font.Font(font_path, 22)
        self.font_status = pygame.font.Font(font_path, 13)
        self.font_header = pygame.font.Font(font_path, 15)
        self.font_breadcrumb = pygame.font.Font(font_path, 14)

        # Try loading a symbol font for icons, fall back to main font
        try:
            segoe_symbols = _pgfont.match_font("segoeuisymbol")
            if segoe_symbols:
                self.font_icon = pygame.font.Font(segoe_symbols, 24)
        except Exception:
            pass

        # Navigation state
        self.node_stack: list[tuple[str, str, list[dict], int]] = []
        self.current_node = "home"
        self.current_title = "Home"
        self.items = sorted(HOME_MENU_ITEMS, key=lambda x: x.get("weight", 50))
        self.selected = 0
        self.scroll_offset = 0

        # Animation
        self.transition_alpha = 255
        self.transition_dir = 0  # 0=none, 1=push_left, -1=push_right
        self.transition_offset = 0

        # Layout
        self.header_h = 52
        self.item_h = 58
        self.status_h = 32
        self.visible_items = (SCREEN_H - self.header_h - self.status_h) // self.item_h
        self.content_y = self.header_h
        self.content_h = SCREEN_H - self.header_h - self.status_h

        # Clock for status bar
        self.start_time = time.time()

    # ------------------------------------------------------------------

    def _navigate_to(self, node_id: str) -> None:
        if node_id not in NODE_MAP:
            return
        title, items = NODE_MAP[node_id]
        items = sorted(items, key=lambda x: x.get("weight", 50))

        # Push current state
        self.node_stack.append(
            (self.current_node, self.current_title, self.items, self.selected)
        )
        self.current_node = node_id
        self.current_title = title
        self.items = items
        self.selected = 0
        self.scroll_offset = 0
        self.transition_dir = 1
        self.transition_offset = SCREEN_W

    def _navigate_back(self) -> None:
        if not self.node_stack:
            return
        node, title, items, sel = self.node_stack.pop()
        self.current_node = node
        self.current_title = title
        self.items = items
        self.selected = sel
        self.scroll_offset = max(0, self.selected - self.visible_items + 2)
        self.transition_dir = -1
        self.transition_offset = -SCREEN_W

    # ------------------------------------------------------------------

    def handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
                return

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                    return

                elif event.key == pygame.K_UP:
                    if self.selected > 0:
                        self.selected -= 1
                        if self.selected < self.scroll_offset:
                            self.scroll_offset = self.selected

                elif event.key == pygame.K_DOWN:
                    if self.selected < len(self.items) - 1:
                        self.selected += 1
                        if self.selected >= self.scroll_offset + self.visible_items:
                            self.scroll_offset = self.selected - self.visible_items + 1

                elif event.key in (pygame.K_RETURN, pygame.K_RIGHT):
                    item = self.items[self.selected]
                    if item.get("has_children"):
                        self._navigate_to(item["children_node"])
                    else:
                        print(
                            f"[home_menu_demo] Activated: {item['text']} ({item['id']})"
                        )

                elif event.key in (pygame.K_BACKSPACE, pygame.K_LEFT):
                    self._navigate_back()

                elif event.key == pygame.K_PAGEUP:
                    self.selected = max(0, self.selected - self.visible_items)
                    self.scroll_offset = max(0, self.scroll_offset - self.visible_items)

                elif event.key == pygame.K_PAGEDOWN:
                    self.selected = min(
                        len(self.items) - 1,
                        self.selected + self.visible_items,
                    )
                    max_scroll = max(0, len(self.items) - self.visible_items)
                    self.scroll_offset = min(
                        max_scroll,
                        self.scroll_offset + self.visible_items,
                    )

            elif event.type == pygame.MOUSEBUTTONDOWN:
                mx, my = event.pos
                if my > self.header_h and my < SCREEN_H - self.status_h:
                    clicked_idx = (
                        my - self.header_h
                    ) // self.item_h + self.scroll_offset
                    if 0 <= clicked_idx < len(self.items):
                        self.selected = clicked_idx
                        item = self.items[self.selected]
                        if item.get("has_children"):
                            self._navigate_to(item["children_node"])
                        else:
                            print(
                                f"[home_menu_demo] Activated: {item['text']}"
                                f" ({item['id']})"
                            )

            elif event.type == pygame.MOUSEWHEEL:
                if event.y > 0:
                    if self.selected > 0:
                        self.selected -= 1
                        if self.selected < self.scroll_offset:
                            self.scroll_offset = self.selected
                elif event.y < 0:
                    if self.selected < len(self.items) - 1:
                        self.selected += 1
                        if self.selected >= self.scroll_offset + self.visible_items:
                            self.scroll_offset = self.selected - self.visible_items + 1

    # ------------------------------------------------------------------

    def update(self) -> None:
        # Animate transition
        if self.transition_offset != 0:
            speed = max(20, abs(self.transition_offset) // 4)
            if self.transition_offset > 0:
                self.transition_offset = max(0, self.transition_offset - speed)
            else:
                self.transition_offset = min(0, self.transition_offset + speed)

    # ------------------------------------------------------------------

    def draw(self) -> None:
        self.screen.fill(self._rgba(BG_COLOR))

        x_off = self.transition_offset

        self._draw_header(x_off)
        self._draw_items(x_off)
        self._draw_scrollbar()
        self._draw_status_bar()

    def _rgba(self, color: int) -> tuple[int, int, int]:
        return ((color >> 24) & 0xFF, (color >> 16) & 0xFF, (color >> 8) & 0xFF)

    def _rgba4(self, color: int) -> tuple[int, int, int, int]:
        return (
            (color >> 24) & 0xFF,
            (color >> 16) & 0xFF,
            (color >> 8) & 0xFF,
            color & 0xFF,
        )

    def _draw_header(self, x_off: int = 0) -> None:
        # Header background
        header_rect = pygame.Rect(0, 0, SCREEN_W, self.header_h)
        pygame.draw.rect(self.screen, self._rgba(HEADER_BG), header_rect)

        # Bottom line
        pygame.draw.line(
            self.screen,
            self._rgba(ACCENT),
            (0, self.header_h - 2),
            (SCREEN_W, self.header_h - 2),
            2,
        )

        # Breadcrumb
        if self.node_stack:
            breadcrumb_parts = [s[1] for s in self.node_stack] + [self.current_title]
            breadcrumb = " › ".join(breadcrumb_parts)
            bc_surf = self.font_breadcrumb.render(
                breadcrumb, True, self._rgba(TEXT_DIM)
            )
            self.screen.blit(bc_surf, (16 + x_off, 4))

        # Title
        title_surf = self.font_title.render(
            self.current_title, True, self._rgba(TEXT_COLOR)
        )
        ty = (self.header_h - title_surf.get_height()) // 2
        if self.node_stack:
            ty = self.header_h - title_surf.get_height() - 4

            # Back arrow
            back_surf = self.font_title.render("‹", True, self._rgba(ACCENT))
            self.screen.blit(back_surf, (8 + x_off, ty))
            self.screen.blit(title_surf, (30 + x_off, ty))
        else:
            self.screen.blit(title_surf, (16 + x_off, ty))

        # Player name (right side)
        player_text = "piCorePlayer [Living Room]"
        player_surf = self.font_detail.render(player_text, True, self._rgba(ACCENT))
        px = SCREEN_W - player_surf.get_width() - 16
        py = (self.header_h - player_surf.get_height()) // 2
        self.screen.blit(player_surf, (px, py))

    def _draw_items(self, x_off: int = 0) -> None:
        visible_end = min(self.scroll_offset + self.visible_items, len(self.items))

        for i in range(self.scroll_offset, visible_end):
            item = self.items[i]
            y = self.content_y + (i - self.scroll_offset) * self.item_h
            is_selected = i == self.selected

            # Item background
            item_rect = pygame.Rect(0 + x_off, y, SCREEN_W, self.item_h)

            if is_selected:
                # Gradient-like selection highlight
                sel_surf = pygame.Surface((SCREEN_W, self.item_h), pygame.SRCALPHA)
                sel_surf.fill(self._rgba4(ITEM_SEL_BG))
                # Accent line on left
                pygame.draw.rect(sel_surf, self._rgba4(ACCENT), (0, 0, 4, self.item_h))
                self.screen.blit(sel_surf, (0 + x_off, y))
            else:
                if (i - self.scroll_offset) % 2 == 0:
                    alt_surf = pygame.Surface((SCREEN_W, self.item_h), pygame.SRCALPHA)
                    alt_surf.fill((*self._rgba(ITEM_BG), 80))
                    self.screen.blit(alt_surf, (0 + x_off, y))

            # Icon
            icon_char = item.get("icon_char", "•")
            try:
                icon_surf = self.font_icon.render(icon_char, True, self._rgba(ACCENT))
            except Exception:
                icon_surf = self.font_icon.render("•", True, self._rgba(ACCENT))

            icon_x = 20 + x_off
            icon_y = y + (self.item_h - icon_surf.get_height()) // 2
            self.screen.blit(icon_surf, (icon_x, icon_y))

            # Text
            text_color = (
                self._rgba(TEXT_COLOR) if is_selected else self._rgba(TEXT_COLOR)
            )
            text_surf = self.font_item.render(item["text"], True, text_color)
            text_x = 64 + x_off
            text_y = y + (self.item_h - text_surf.get_height()) // 2

            # If there's a detail line, shift text up
            detail = item.get("detail")
            if detail:
                text_y = y + 8
                detail_surf = self.font_detail.render(
                    detail, True, self._rgba(TEXT_DIM)
                )
                self.screen.blit(detail_surf, (text_x, y + 32))

            self.screen.blit(text_surf, (text_x, text_y))

            # Arrow indicator for items with children
            if item.get("has_children"):
                arrow_color = (
                    self._rgba(ACCENT) if is_selected else self._rgba(TEXT_DIM)
                )
                arrow_surf = self.font_item.render("›", True, arrow_color)
                ax = SCREEN_W - 30 + x_off
                ay = y + (self.item_h - arrow_surf.get_height()) // 2
                self.screen.blit(arrow_surf, (ax, ay))

            # Bottom divider
            div_y = y + self.item_h - 1
            pygame.draw.line(
                self.screen,
                self._rgba(DIVIDER_COLOR),
                (16 + x_off, div_y),
                (SCREEN_W - 16 + x_off, div_y),
                1,
            )

    def _draw_scrollbar(self) -> None:
        if len(self.items) <= self.visible_items:
            return

        total = len(self.items)
        bar_h = max(20, int(self.content_h * self.visible_items / total))
        bar_y = self.content_y + int(
            (self.content_h - bar_h) * self.scroll_offset / (total - self.visible_items)
        )

        # Track
        track_rect = pygame.Rect(SCREEN_W - 6, self.content_y, 4, self.content_h)
        pygame.draw.rect(self.screen, self._rgba(DIVIDER_COLOR), track_rect)

        # Thumb
        thumb_rect = pygame.Rect(SCREEN_W - 6, bar_y, 4, bar_h)
        pygame.draw.rect(self.screen, self._rgba(ACCENT), thumb_rect)

    def _draw_status_bar(self) -> None:
        y = SCREEN_H - self.status_h

        # Background
        status_rect = pygame.Rect(0, y, SCREEN_W, self.status_h)
        pygame.draw.rect(self.screen, self._rgba(HEADER_BG), status_rect)

        # Top line
        pygame.draw.line(
            self.screen, self._rgba(DIVIDER_COLOR), (0, y), (SCREEN_W, y), 1
        )

        # Left: applet info
        ported_applets = [
            "NowPlaying",
            "SelectPlayer",
            "SlimBrowser",
            "SlimDiscovery",
            "SlimMenus",
            "JogglerSkin",
            "QVGAbaseSkin",
        ]
        info_text = f"Ported: {', '.join(ported_applets)}"
        info_surf = self.font_status.render(info_text, True, self._rgba(TEXT_DIM))
        self.screen.blit(info_surf, (10, y + 8))

        # Center: navigation hint
        hint = "↑↓ Navigate  Enter/→ Select  ←/Backspace Back  ESC Quit"
        hint_surf = self.font_status.render(hint, True, self._rgba(TEXT_DIM))
        hx = (SCREEN_W - hint_surf.get_width()) // 2
        # Only show if it fits (otherwise skip)
        if hint_surf.get_width() + info_surf.get_width() + 40 < SCREEN_W:
            self.screen.blit(hint_surf, (hx, y + 8))

        # Right: item count + test count
        count_text = f"{self.selected + 1}/{len(self.items)}  •  2675 tests ✓"
        count_surf = self.font_status.render(count_text, True, self._rgba(ACCENT))
        cx = SCREEN_W - count_surf.get_width() - 10
        self.screen.blit(count_surf, (cx, y + 8))

    # ------------------------------------------------------------------

    def run(self) -> None:
        while self.running:
            self.handle_events()
            self.update()
            self.draw()
            pygame.display.flip()
            self.clock.tick(60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    pygame.init()

    font_path = _resolve_font()
    print(f"[home_menu_demo] Using font: {font_path}")

    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    pygame.display.set_caption(TITLE)

    # Set window icon text (if possible)
    try:
        icon_surf = pygame.Surface((32, 32), pygame.SRCALPHA)
        icon_surf.fill((0, 210, 255, 255))
        pygame.display.set_icon(icon_surf)
    except Exception:
        pass

    app = HomeMenuApp(screen, font_path)
    print(f"[home_menu_demo] Window opened ({SCREEN_W}×{SCREEN_H})")
    print(
        f"[home_menu_demo] Use ↑↓ to navigate, Enter to select, Backspace to go back, ESC to quit"
    )

    try:
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        pygame.quit()
        print("[home_menu_demo] Done.")


if __name__ == "__main__":
    main()
