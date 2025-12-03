from __future__ import annotations

# Built-in libraries
import curses
import logging
import os
import random
import string
from enum import Enum
from typing import Dict, Optional, Tuple

# Custom-made libraries
from control import RuntimeController

LOG = logging.getLogger(__name__)

# All printable characters except whitespace
PRINTABLES: str = "".join(c for c in string.printable if not c.isspace())


class PixelColor(Enum):
    """
    Logical color names mapped to *pair IDs* (1...n).
    """

    RED = 1
    GREEN = 2
    YELLOW = 3
    BLUE = 4
    MAGENTA = 5
    CYAN = 6
    WHITE = 7


class CursesRenderer:
    """
    Manages all direct interaction with the Curses library.
    Handles screen drawing, resizing, and user input.
    """

    def __init__(self, control: RuntimeController) -> None:
        """
        Initialize internal state.

        Args:
            control: The shared thread-safe flag controller.
        """
        os.environ.setdefault("TERM", "xterm-256color")

        # Internal state (protected variables)
        self._stdscr: Optional[curses.window] = None
        self._screen_height: int = 0
        self._screen_width: int = 0
        self._capacity: int = 0

        # Shared control flags
        self._control: RuntimeController = control

        # Buffer: {(x, y): (char, color)}
        # Used to track occupied spots and ensure unique pixels.
        self._pixel_buffer: Dict[Tuple[int, int], Tuple[str, PixelColor]] = {}

        # Speed of the drawing (read by PixelSpawner)
        self.DRAW_INTERVAL: float = 0.05

        # Minimum screen area (width * height) required to run
        self._MIN_SCREEN_AREA = 4

    @property
    def stdscr(self) -> curses.window:
        """Safe accessor for the main curses window."""
        if self._stdscr is None:
            raise RuntimeError("stdscr not initialized; call run() first.")
        return self._stdscr

    @staticmethod
    def _get_color() -> PixelColor:
        return random.choice(list(PixelColor))

    @staticmethod
    def _get_pixel() -> str:
        return random.choice(PRINTABLES)

    @staticmethod
    def _colors_init() -> None:
        """Initializes standard curses color pairs."""
        curses.start_color()
        curses.use_default_colors()

        if not curses.has_colors():
            return

        for color in PixelColor:
            # Map enum to curses constants (e.g., PixelColor.RED -> curses.COLOR_RED)
            fg = getattr(curses, f"COLOR_{color.name}", curses.COLOR_WHITE)
            curses.init_pair(color.value, fg, -1)

    def _set_ready(self, is_ready: bool) -> None:
        """Helper to update the thread-safe flag."""
        self._control.set_view_ready(is_ready)

    def _calc_capacity(self) -> None:
        """Stores screen dimensions and max pixel capacity."""
        self._screen_height, self._screen_width = self.stdscr.getmaxyx()
        self._capacity = self._screen_height * self._screen_width

    def _get_coordinates(self) -> Tuple[int, int]:
        """
        Return a random (x, y) coordinate that is not yet occupied.
        """
        # Safety valve: If buffer is full, return (0,0) to prevent
        # the while loop from spinning infinitely.
        if len(self._pixel_buffer) >= self._capacity:
            return 0, 0

        while True:
            y: int = random.randrange(self._screen_height)
            x: int = random.randrange(self._screen_width)

            # Collision check
            if (x, y) not in self._pixel_buffer:
                return x, y

    def _draw_pixel(self, pixel: str, color: PixelColor, x: int, y: int) -> None:
        """Draws a pixel to the screen and updates the internal buffer."""

        # Bounds check (Standard safety)
        if not (0 <= x < self._screen_width) or not (0 <= y < self._screen_height):
            return

        key: Tuple[int, int] = (x, y)

        # Optimization: Don't overwrite existing pixels
        if key in self._pixel_buffer:
            return

        attrs: int = curses.color_pair(color.value)

        try:
            self.stdscr.addch(y, x, pixel, attrs)
            self._pixel_buffer[key] = (pixel, color)
        except curses.error:
            # CURSES QUIRK:
            # Writing to the very bottom-right character of a window often
            # throws an exception (ERR), even if the character is successfully
            # written. We catch this and count it as a success.
            if (x, y) == (self._screen_width - 1, self._screen_height - 1):
                self._pixel_buffer[key] = (pixel, color)

    def _reset_screen(self) -> None:
        """
        Clears the drawing area and resets counters.
        Called when screen fills up or resizes.
        """
        # Pause background drawing
        self._set_ready(False)

        self._pixel_buffer.clear()
        self.stdscr.clear()

        # Resume background drawing
        self._set_ready(True)

    def _check_fit(self) -> bool:
        """Validates if the screen is large enough to run."""
        return self._capacity > self._MIN_SCREEN_AREA

    def _validate_screen_size(self) -> None:
        """Checks dimensions and handles failure if too small."""
        if self._check_fit():
            self._set_ready(True)
        else:
            LOG.error(
                f"Terminal too small! Area {self._capacity} < Min {self._MIN_SCREEN_AREA}"
            )
            self._control.signal_stop()
            raise SystemExit(1)

    def _handle_resize(self) -> None:
        """
        Handles terminal resizing events.
        Re-calculates geometry and clears the screen.
        """
        self._set_ready(False)
        self._calc_capacity()

        # Full reset needed because coordinates shift on resize
        self._pixel_buffer.clear()
        self.stdscr.clear()

        self._validate_screen_size()

    def _application(self, stdscr: curses.window) -> None:
        """
        Main Curses Event Loop.
        Monitors keyboard input and resize events.
        """
        self._stdscr = stdscr

        # Standard Curses Setup
        curses.curs_set(0)  # Hide cursor
        self.stdscr.keypad(True)  # Handle special keys
        curses.noecho()  # Don't print keys to screen
        curses.cbreak()  # React to keys instantly

        self._colors_init()
        self._calc_capacity()

        self._validate_screen_size()

        try:
            while not self._control.should_stop():
                # Timeout is crucial: it prevents getch() from blocking forever,
                # allowing the loop to check 'should_stop()' periodically.
                self.stdscr.timeout(100)

                key: int = self.stdscr.getch()

                # Standard Resize Event (SIGWINCH from OS)
                if key == curses.KEY_RESIZE:
                    self._handle_resize()

                # Polling Resize Check (Fail-safe)
                # Sometimes KEY_RESIZE is missed; this catches physical changes.
                elif curses.is_term_resized(self._screen_height, self._screen_width):
                    self._handle_resize()

                # User Exit
                elif key in (ord("q"), 27):  # q or ESC
                    break

        except KeyboardInterrupt:
            # Handle Ctrl+C gracefully
            pass
        finally:
            # Ensure background threads stop trying to draw
            self._set_ready(False)
            self._control.signal_stop()

    def run(self) -> None:
        """Entry point to start the Curses wrapper."""
        try:
            curses.wrapper(self._application)
        except curses.error as exc:
            LOG.error(f"[curses] initialization error: {exc}")
            self._control.signal_stop()
            raise SystemExit(1)

    def pulse(self) -> None:
        """
        Public API called by the background thread to draw one pixel.
        """
        if self._stdscr is None:
            return

        # Loop effect: If full, wipe and start over
        if len(self._pixel_buffer) >= self._capacity:
            self._reset_screen()
            return

        # Logic
        x, y = self._get_coordinates()
        pixel: str = self._get_pixel()
        color: PixelColor = self._get_color()

        # Render
        self._draw_pixel(pixel, color, x, y)
        self.stdscr.refresh()
