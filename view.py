from __future__ import annotations

# Built-in libraries
import curses
import logging
import os
import random
import string
import threading
from enum import Enum
from typing import Dict, Optional, Tuple

# Custom-made libraries
from control import AppControlFlags

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


class ViewConnector:
    """
    Manage screen operations using curses.

    Usage:
        ViewConnector(control, condition).run()

    Design notes:
    - Avoids calling `curses.initscr()` directly; uses `curses.wrapper()` to
      ensure the terminal is restored even if an exception occurs.
    - Maintains a simple "framebuffer" (`__pixel_buffer`) that caches the last
      drawn character and color per (x, y) so unchanged cells are not rewritten.
      This reduces flicker and unnecessary drawing.
    """

    def __init__(
        self,
        control: AppControlFlags,
        condition: threading.Condition,
    ) -> None:
        """
        Initialize internal state without touching curses.

        Curses setup (screen, colors, and input configuration) is deferred
        to `run()`, which wraps the internal application with
        `curses.wrapper()`.
        """
        os.environ.setdefault("TERM", "xterm-256color")

        self.__stdscr: Optional[curses.window] = None
        self.__screen_height: int = 0
        self.__screen_width: int = 0

        # Total number of available cells on screen
        self.__capacity: int = 0

        self._control: AppControlFlags = control
        self._condition: threading.Condition = condition

        # Buffer of what we've last drawn: {(x, y): (char, color)}
        # This lets us skip redundant writes when glyph and color haven't changed.
        self.__pixel_buffer: Dict[Tuple[int, int], Tuple[str, PixelColor]] = {}

        # Interval used by background jobs to control pulse frequency.
        self.PULSE_TIMEOUT = 0.001

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

    def __view_is_ready(self, flag: bool) -> None:
        """
        Update the shared 'view ready' flag.

        Args:
            flag: True when the curses view is fully initialized and safe
                to use, False when it is being created or shut down.
        """
        with self._condition:
            self._control.view_ready = flag

    def __get_color(self) -> PixelColor:
        """
        Return a randomly chosen PixelColor value.

        Used to give each new pixel a random color pair.
        """
        return random.choice(list(PixelColor))

    def __get_pixel(self) -> str:
        """
        Return a single randomly chosen printable character.

        The character is selected from ASCII printable characters that
        are not whitespace.
        """
        return random.choice(PRINTABLES)

    def __get_coordinates(self) -> Tuple[int, int]:
        """
        Return a random (x, y) coordinate on the screen.

        When possible, it prefers coordinates that have not yet been used
        in the current pixel buffer, so every cell is visited before the
        screen is cleared.
        """
        while True:
            y: int = random.randrange(self.__screen_height)
            x: int = random.randrange(self.__screen_width)

            key: Tuple[int, int] = (x, y)
            if key not in self.__pixel_buffer:
                return (x, y)

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
            - If the coordinate is already in the pixel buffer, the write
              is skipped to avoid overwriting existing pixels.
        """

        # Bounds check
        if not (0 <= x < self.__screen_width) or not (0 <= y < self.__screen_height):
            return

        # Validate char
        if len(pixel) != 1 or not pixel.isprintable():
            return

        key: Tuple[int, int] = (x, y)
        if key in self.__pixel_buffer:
            return  # this coordinate was already taken

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
        Initialize curses color pairs based on the PixelColor enum.

        Each PixelColor value is used as the color-pair ID, with the
        foreground color taken from its name (e.g., PixelColor.RED ->
        curses.COLOR_RED). The background is set to -1 (use terminal
        default) for better theme compatibility.

        Raises:
            curses.error: If the terminal does not support colors.
        """

        curses.start_color()
        curses.use_default_colors()

        # Verify terminal supports colors
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

    def __handle_resize(self) -> None:
        """
        Handle terminal resize events.

        - Updates the cached screen width/height.
        - Clears the screen and the local pixel buffer.
        - Draws a new random pixel on the resized screen.
        - Refreshes the display after the redraw.
        """

        self.__screen_height, self.__screen_width = self.stdscr.getmaxyx()
        self.__capacity = self.__screen_width * self.__screen_height
        self.stdscr.clear()
        self.__pixel_buffer.clear()

        x, y = self.__get_coordinates()
        pixel: str = self.__get_pixel()
        color: PixelColor = self.__get_color()

        self.__draw_pixel(pixel, color, x, y)
        self.stdscr.refresh()

    def __application(self, stdscr: curses.window) -> None:
        """
        Main curses application (entry for `curses.wrapper`).

        Behaviour:
            - Initializes the curses environment and color pairs.
            - Waits for key presses in a loop.
            - Reacts to terminal resizes by redrawing the screen.
            - Exits when 'q' or ESC is pressed.

        The function owns curses state until it returns; `curses.wrapper`
        restores terminal modes afterwards even if an exception bubbles up.
        """

        # Bind the stdscr provided by wrapper and initialize state
        self.__stdscr = stdscr
        self.__screen_height, self.__screen_width = self.stdscr.getmaxyx()
        self.__capacity = self.__screen_width * self.__screen_height

        # Setup terminal behavior
        curses.curs_set(0)  # Hide cursor (may raise on some terminals)
        self.stdscr.keypad(True)  # Enable keypad so arrow keys/ESC are decoded
        curses.noecho()  # Do not echo pressed keys
        curses.cbreak()  # React to keys immediately (no Enter needed)

        # Initialize color pairs and place the initial cursor
        self.__colors_init()
        self.stdscr.refresh()

        self.__view_is_ready(True)

        try:
            while True:
                key: int = self.stdscr.getch()

                # React to terminal resizes
                if curses.is_term_resized(self.__screen_height, self.__screen_width):
                    self.__handle_resize()

                # Exit on 'q' or ESC
                if key in (ord("q"), 27):
                    break

        except KeyboardInterrupt:
            # Graceful Ctrl+C exit
            pass

        finally:
            # Restore a clean screen before wrapper restores terminal modes
            self.stdscr.clear()
            self.stdscr.refresh()

    def run(self) -> None:
        """
        Entry point: wrap the application to ensure proper terminal teardown.

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

    def pulse(self) -> None:
        """
        Draw a single random pixel and immediately refresh the screen.

        When all screen positions have been used once (pixel buffer full),
        the screen is cleared, the buffer is reset, and the process starts over.
        """

        if self.__stdscr is None:
            raise RuntimeError("stdscr not initialized; call run() first.")

        # Check if there is space
        if self.__capacity > 0:
            # If we've already drawn to every cell
            used = len(self.__pixel_buffer)
            if used >= self.__capacity:
                # Reset screen and buffer and start over
                self.stdscr.clear()
                self.__pixel_buffer.clear()
                self.stdscr.refresh()

            x, y = self.__get_coordinates()
            pixel: str = self.__get_pixel()
            color: PixelColor = self.__get_color()

            self.__draw_pixel(pixel, color, x, y)
            self.stdscr.refresh()
