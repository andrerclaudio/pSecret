from __future__ import annotations

# Built-in libraries
import curses
import logging
import os
import random
import string
from enum import Enum
from typing import Dict, Optional, Tuple

LOG = logging.getLogger(__name__)


# All printable characters except whitespace
PRINTABLES: str = "".join(c for c in string.printable if not c.isspace())


class PixelColor(Enum):
    """
    Logical color names mapped to *pair IDs* (1..n) for curses color pairs.

    The enum value is the color pair ID. Each ID is initialized so that the
    foreground color comes from the enum name (e.g., BLUE -> curses.COLOR_BLUE)
    and the background is the terminal default (-1).

    These are **not** RGB values; they correspond to terminal palette colors.
    """

    RED = 1
    GREEN = 2
    YELLOW = 3
    BLUE = 4
    MAGENTA = 5
    CYAN = 6
    WHITE = 7
    BLACK = 8


class ViewConnector:
    """
    Manage screen operations using curses.

    Usage:
        ViewConnector().run()

    Design notes:
    - Avoid calling `curses.initscr()` directly; use `curses.wrapper()` to ensure
      the terminal is restored even if an exception occurs.
    - A simple "framebuffer" (`__pixel_buffer`) caches the last drawn character
      and color per (x, y) so unchanged cells are not rewritten (reduces flicker).
    """

    def __init__(self) -> None:
        """
        Prepare internal state. Does not touch curses until `run()`.
        """
        os.environ.setdefault("TERM", "xterm-256color")

        self.__stdscr: Optional[curses.window] = None
        self.__screen_height: int = 0
        self.__screen_width: int = 0
        self.__cursor_x: int = 0
        self.__cursor_y: int = 0

        # Buffer of what we've last drawn: {(x, y): (char, color)}
        # This lets us skip redundant writes when glyph and color haven't changed.
        self.__pixel_buffer: Dict[Tuple[int, int], Tuple[str, PixelColor]] = {}

    @property
    def stdscr(self) -> curses.window:
        """
        Access the active curses window after wrapper has initialized it.

        Returns:
            curses.window: The active stdscr window managed by curses.

        Raises:
            RuntimeError: If accessed before `curses.wrapper()` sets the window.
        """

        if self.__stdscr is None:
            raise RuntimeError("stdscr not initialized; call run() first.")

        return self.__stdscr

    def __clamp(self, x: int, y: int) -> tuple[int, int]:
        """
        Clamp (x, y) to the current screen bounds.

        Args:
            x: Proposed column index (0-based).
            y: Proposed row index (0-based).

        Returns:
            tuple[int, int]: (x, y) adjusted to be within [0..width-1] and [0..height-1].
        """

        x = max(0, min(self.__screen_width - 1, x))
        y = max(0, min(self.__screen_height - 1, y))

        return x, y

    def __move_cursor(self, pixel: str, color: PixelColor, dx: int, dy: int) -> None:
        """
        Move the demo cursor by (dx, dy), clamped to the screen, then redraw it
        using the given glyph (`pixel`) and color.

        The previous cell is cleared *visually* by drawing a space (with BLACK),
        and the new position is drawn with the specified glyph/color. The screen
        is refreshed at the end.

        Args:
            pixel: Single-character, printable glyph to draw at the new position.
            color: Color pair (from PixelColor) used to draw the glyph.
            dx: Delta applied to the current x (columns).
            dy: Delta applied to the current y (rows).

        Note:
            This "clear" does not fully reset terminal attributes to defaults; it
            replaces the glyph with a space using a color pair.
        """

        old_x: int
        old_y: int
        new_x: int
        new_y: int

        old_x, old_y = self.__cursor_x, self.__cursor_y
        new_x, new_y = self.__clamp(old_x + dx, old_y + dy)

        # No-op if the clamped position did not change
        if (new_x, new_y) == (old_x, old_y):
            return

        # Clear previous cell and draw new one
        # NOTE: This writes a space using PixelColor.BLACK; visually clears,
        # but leaves the cell's attributes as last written.
        self.__draw_pixel(" ", PixelColor.BLACK, old_x, old_y)
        self.__draw_pixel(pixel, color, new_x, new_y)

        self.__cursor_x, self.__cursor_y = new_x, new_y
        self.stdscr.refresh()

    def __draw_pixel(self, pixel: str, color: PixelColor, x: int, y: int) -> None:
        """
        Draw a single printable character at (x, y) with the given color.

        Args:
            pixel: Single-character string to draw (must be printable).
            color: PixelColor enum specifying the color pair to use.
            x: Column index (0-based).
            y: Row index (0-based).

        Behavior:
            - Out-of-bounds writes are ignored.
            - Non-printable or multi-character strings are ignored.
            - If (char, color) matches the cached value for (x, y), the write is skipped.
        """

        # Bounds check
        if not (0 <= x < self.__screen_width) or not (0 <= y < self.__screen_height):
            return

        # Validate char
        if len(pixel) != 1 or not pixel.isprintable():
            return

        key: Tuple[int, int] = (x, y)
        prev: Optional[Tuple[str, PixelColor]] = self.__pixel_buffer.get(key)

        if prev == (pixel, color):
            return  # Nothing changed: avoid redundant write

        # Calculate attributes and draw
        attrs: int = curses.color_pair(color.value)

        try:
            self.stdscr.addch(y, x, pixel, attrs)
            self.__pixel_buffer[key] = (pixel, color)
        except curses.error:
            # Drop cache entry to be safe.
            self.__pixel_buffer.pop(key, None)

    def __colors_init(self) -> None:
        """
        Initialize curses color pairs.

        Each PixelColor value is used as the color-pair ID, with foreground color
        taken from its name (e.g., PixelColor.RED -> curses.COLOR_RED).
        Background is set to -1 (use terminal default) for better theme compatibility.

        Raises:
            curses.error: If the terminal does not support colors.
        """

        curses.start_color()
        curses.use_default_colors()

        # Verify terminal supports colors;
        if not curses.has_colors():
            raise curses.error("Terminal does not support colors.")

        for color in PixelColor:
            # getattr(curses, "COLOR_RED") etc.
            fg: Optional[int] = getattr(curses, f"COLOR_{color.name}", None)
            if fg is None:
                # Fallback: default to white if a color name isn't present
                fg = curses.COLOR_WHITE

            # Pair number = enum value (1..n). Background = -1 (default).
            curses.init_pair(color.value, fg, -1)

    def __handle_resize(self, pixel: str, color: PixelColor) -> None:
        """
        Handle terminal resize.

        - Updates internal width/height.
        - Clears the screen and the local pixel buffer.
        - Clamps the cursor into the new bounds.
        - Redraws the cursor with the specified glyph/color.
        - Refreshes the display.

        Args:
            pixel: Glyph to redraw at the (possibly clamped) cursor position.
            color: Color with which to redraw the glyph.
        """

        self.__screen_height, self.__screen_width = self.stdscr.getmaxyx()
        self.stdscr.clear()
        self.__pixel_buffer.clear()

        # Keep the cursor in-bounds and redraw it after clearing
        self.__cursor_x, self.__cursor_y = self.__clamp(
            self.__cursor_x, self.__cursor_y
        )
        self.__draw_pixel(pixel, color, self.__cursor_x, self.__cursor_y)
        self.stdscr.refresh()

    def __application(self, stdscr: curses.window) -> None:
        """
        Main curses application (entry for `curses.wrapper`).

        Controls:
            - Arrow keys move the cursor.
            - This demo uses different glyph/color per direction.
            - 'q' or ESC exits the application.

        The function owns curses state until it returns; wrapper restores terminal
        modes afterwards even if an exception bubbles up.
        """
        # Bind the stdscr provided by wrapper and initialize state
        self.__stdscr = stdscr
        self.__screen_height, self.__screen_width = self.stdscr.getmaxyx()

        # Setup terminal behavior
        curses.curs_set(0)  # Hide cursor (may raise on some terminals)
        self.stdscr.keypad(True)  # Enable keypad so arrow keys/ESC are decoded
        curses.noecho()  # Do not echo pressed keys
        curses.cbreak()  # React to keys immediately (no Enter needed)

        # Initialize color pairs and place the initial cursor
        self.__colors_init()
        self.__cursor_x, self.__cursor_y = 0, 0
        self.__draw_pixel(
            random.choice(PRINTABLES), PixelColor.BLUE, self.__cursor_x, self.__cursor_y
        )
        self.stdscr.refresh()

        try:
            while True:
                key: int = self.stdscr.getch()

                # React to terminal resizes
                if curses.is_term_resized(self.__screen_height, self.__screen_width):
                    self.__handle_resize(random.choice(PRINTABLES), PixelColor.BLUE)

                # Exit on 'q' or ESC
                if key in (ord("q"), 27):
                    break

                pixel: str = random.choice(PRINTABLES)
                color: PixelColor = random.choice(list(PixelColor))

                # Movement via helper (clamped)
                if key == curses.KEY_LEFT:
                    self.__move_cursor(pixel, color, -1, 0)
                elif key == curses.KEY_RIGHT:
                    self.__move_cursor(pixel, color, +1, 0)
                elif key == curses.KEY_UP:
                    self.__move_cursor(pixel, color, 0, -1)
                elif key == curses.KEY_DOWN:
                    self.__move_cursor(pixel, color, 0, +1)

        except KeyboardInterrupt:
            # Graceful Ctrl+C exit
            pass

        finally:
            # Restore a clean screen before wrapper restores terminal modes
            self.stdscr.clear()
            self.stdscr.refresh()

    def run(self) -> None:
        """
        Entrypoint: wrap the application to ensure proper terminal teardown.

        Raises:
            SystemExit: Exits with code 1 if curses fails to initialize
                        (e.g., unsupported TERM, not a TTY, or no color support).
        """

        try:
            curses.wrapper(self.__application)

        except curses.error as exc:
            # Common causes: TERM is unsupported, not a real TTY, or no color support.
            LOG.error(f"[curses] initialization error: {exc}")
            raise SystemExit(1)
