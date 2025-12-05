from __future__ import annotations

# Built-in libraries
import curses
import logging
import os
import random
import secrets
import string
import time
from enum import Enum
from typing import Dict, List, Optional, Tuple

# Custom-made libraries
from control import RuntimeController

LOG = logging.getLogger(__name__)

# All printable characters except whitespace
PRINTABLES: str = "".join(c for c in string.printable if not c.isspace())


class SpawnState(Enum):
    """
    State machine for the visual effects.

    DRAWING: Randomly filling the screen with pixels.
    SORTING: Organizing the chaotic pixels into a structured pattern.
    WAITING: Holding the final image for a few seconds before resetting.
    """

    DRAWING = 0
    SORTING = 1
    WAITING = 2


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

        # A pre-shuffled list of all available (x, y) spots
        self._available_coords: List[Tuple[int, int]] = []

        # Shared control flags
        self._control: RuntimeController = control

        # Buffer: {(x, y): (char, color)}
        # Used to track occupied spots and ensure unique pixels.
        self._pixel_buffer: Dict[Tuple[int, int], Tuple[str, PixelColor]] = {}

        # Speed of the drawing (read by PixelSpawner)
        self.DRAW_INTERVAL: float = 0.05

        # Minimum screen area (width * height) required to run
        self._MIN_SCREEN_AREA = 10

        # State Management
        self._spawn_state: int = SpawnState.DRAWING.value

        # Sorting Variables
        # The final ordered list of pixels we want to achieve.
        self._sorted_targets: List[Tuple[str, PixelColor]] = []
        # Tracks the current index (0 to capacity) we are fixing in the sort loop.
        self._sort_cursor: int = 0

        # Timer Variable
        self._TIMEOUT_TO_RESET: int = 2
        self._wait_start_time: float = 0.0

    @property
    def stdscr(self) -> curses.window:
        """Safe accessor for the main curses window."""
        if self._stdscr is None:
            raise RuntimeError("stdscr not initialized; call run() first.")
        return self._stdscr

    @staticmethod
    def _get_color() -> PixelColor:
        return secrets.choice(list(PixelColor))

    @staticmethod
    def _get_pixel() -> str:
        return secrets.choice(PRINTABLES)

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
        """Stores screen dimensions, max pixel capacity, and pre-calculates coordinates."""
        self._screen_height, self._screen_width = self.stdscr.getmaxyx()
        self._capacity = self._screen_height * self._screen_width

        # Generate a list of ALL possible coordinates: [(0,0), (0,1), ... (w,h)]
        self._available_coords = [
            (x, y)
            for y in range(self._screen_height)
            for x in range(self._screen_width)
        ]

        # Shuffle them immediately using SystemRandom (strongest shuffle)
        # This ensures the "filling" pattern is completely unpredictable.
        random.SystemRandom().shuffle(self._available_coords)

    def _get_coordinates(self) -> Tuple[int, int]:
        """
        Pop a random coordinate from the pre-shuffled list.
        """
        if not self._available_coords:
            # If empty, return dummy data
            return 0, 0

        # O(1) operation to get a unique
        return self._available_coords.pop()

    def _draw_pixel(self, pixel: str, color: PixelColor, x: int, y: int) -> None:
        """Draws a pixel to the screen and updates the internal buffer."""

        # Bounds check (Standard safety)
        if not (0 <= x < self._screen_width) or not (0 <= y < self._screen_height):
            return

        key: Tuple[int, int] = (x, y)
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

    def __print_small_screen_error_msg(self) -> None:
        """
        Render a simple error message when the terminal is too small.
        """
        message = "Terminal too small."

        # If the message is longer than the screen, truncate.
        if len(message) > self._screen_width:
            message = message[: self._screen_width]

        # Center horizontally
        x = max(0, (self._screen_width - len(message)) // 2)

        # Center vertically
        y = max(0, self._screen_height // 2)

        attrs = curses.color_pair(PixelColor.WHITE.value)

        try:
            self.stdscr.addstr(y, x, message, attrs)
        except curses.error:
            pass  # ignore bottom-right curses glitch

    def _reset_cycle(self) -> None:
        """Resets the screen and state to start over."""
        self._set_ready(False)
        self._pixel_buffer.clear()
        self.stdscr.clear()

        # Re-calculate/Re-shuffle coordinates for the new round
        self._calc_capacity()

        self._sort_cursor = 0
        self._spawn_state = SpawnState.DRAWING.value
        self._set_ready(True)

    def _validate_screen_size(self) -> None:
        """Checks dimensions and handles failure if too small."""

        # Validates if the screen is large enough to run.
        if self._capacity > self._MIN_SCREEN_AREA:
            self._set_ready(True)

        else:
            self.__print_small_screen_error_msg()

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

        self._spawn_state = SpawnState.DRAWING.value

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

    def spawn(self) -> None:
        """
        Public API called by the background thread to draw one pixel.
        Handles the logic for DRAWING (filling), SORTING (ordering), and WAITING.
        """
        if self._stdscr is None:
            return

        # -----------------------------
        # STATE 0: RANDOM DRAWING
        # -----------------------------
        if self._spawn_state == SpawnState.DRAWING.value:
            # Check if screen is full (Capacity Reached)
            if len(self._pixel_buffer) >= self._capacity:
                self._spawn_state = SpawnState.SORTING.value

                # Snapshot current pixels (The "Mess")
                current_pixels = list(self._pixel_buffer.values())

                # Generate a RANDOM order for the colors for this specific cycle.
                #    We don't want "Red" to always be at the top.
                shuffled_colors = random.sample(list(PixelColor), k=len(PixelColor))

                # Create a priority map: {PixelColor.BLUE: 0, PixelColor.RED: 1, ...}
                color_priority = {color: i for i, color in enumerate(shuffled_colors)}

                # Generate the "Master Plan"
                # Primary Key   = Color Rank (Group by color, following random order)
                # Secondary Key = Char Index (Within a color, sort by Printable sequence: 0-9, a-z...)
                self._sorted_targets = sorted(
                    current_pixels,
                    key=lambda p: (color_priority[p[1]], PRINTABLES.find(p[0])),
                )

                # Reset cursor to the top-left (0, 0)
                self._sort_cursor = 0
                return

            # Normal Drawing Logic
            x, y = self._get_coordinates()
            pixel = self._get_pixel()
            color = self._get_color()
            self._draw_pixel(pixel, color, x, y)
            self.stdscr.refresh()

        # -----------------------------
        # STATE 1: SORTING (Line by Line)
        # -----------------------------
        elif self._spawn_state == SpawnState.SORTING.value:
            # Check if sorting is finished (Cursor reached the end)
            if self._sort_cursor >= len(self._sorted_targets):
                self._spawn_state = SpawnState.WAITING.value
                self._wait_start_time = time.time()
                return

            # Calculate Target Location (Where we are writing TO)
            # Converts linear cursor to (x, y) coordinates.
            dest_y = self._sort_cursor // self._screen_width
            dest_x = self._sort_cursor % self._screen_width
            dest_pos = (dest_x, dest_y)

            # Identify what SHOULD be there according to the Master Plan
            target_char, target_color = self._sorted_targets[self._sort_cursor]
            target_val = (target_char, target_color)

            # Check what is ALREADY there
            # Type Safety: We use brackets [] because we know the key exists
            # if the buffer is full. Using .get() causes Type Checker errors.
            if dest_pos not in self._pixel_buffer:
                # Fallback in case of race conditions/resizes, though rare.
                self._sort_cursor += 1
                return

            current_val = self._pixel_buffer[dest_pos]

            # Optimization: If the correct pixel is already there, skip ahead!
            if current_val == target_val:
                self._sort_cursor += 1
                return

            # Find the pixel we need (searching only in the unsorted area)
            # We skip 'start_flat_index' so we don't pick pixels we already placed.
            found_coords = self.find_exact_pixel(
                target_char, target_color, start_flat_index=self._sort_cursor
            )

            if found_coords:
                found_x, found_y = found_coords

                # --- SWAP OPERATION ---
                # Move the 'wrong' pixel (currently at dest) to the 'found' spot.
                # This preserves the pixel; we don't delete it, just move it out of the way.
                self._draw_pixel(current_val[0], current_val[1], found_x, found_y)

                # Move the 'correct' target pixel to the destination spot.
                self._draw_pixel(target_char, target_color, dest_x, dest_y)

                self.stdscr.refresh()

            self._sort_cursor += 1

        # -----------------------------
        # STATE 2: WAITING (5 Seconds)
        # -----------------------------
        elif self._spawn_state == SpawnState.WAITING.value:
            # Non-blocking wait: check system time every frame
            if time.time() - self._wait_start_time > self._TIMEOUT_TO_RESET:
                self._reset_cycle()

    def find_exact_pixel(
        self, target_char: str, target_color: PixelColor, start_flat_index: int = 0
    ) -> Optional[Tuple[int, int]]:
        """
        Scans the buffer to find the coordinates of a specific pixel (char + color).

        Args:
            start_flat_index: Optimization to skip the beginning of the buffer
                              (used when we know those pixels are already sorted).
        """
        target_val = (target_char, target_color)

        for (x, y), val in self._pixel_buffer.items():
            # Convert (x,y) to a flat integer index (row-major order) to compare with cursor
            flat_idx = y * self._screen_width + x

            # Skip pixels we have already sorted/placed
            if flat_idx < start_flat_index:
                continue

            if val == target_val:
                return x, y
        return None
