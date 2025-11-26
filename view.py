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
from layout import (
    CLUSTER_COUNT_ORIGIN_X_DELTA,
    CLUSTER_COUNT_ORIGIN_Y_DELTA,
    PERCENTAGE_BAR_ORIGIN_X_DELTA,
    PERCENTAGE_BAR_ORIGIN_Y_DELTA,
    BoxKind,
    LayoutManager,
)

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
        self.PULSE_TIMEOUT = 0.1

        # Set the domint color for layout objects
        self.__dominant_colors = PixelColor.WHITE
        # Initialize th layout Manager
        self.__layout = LayoutManager()

        #
        self.__defrag_start_x: int = 0
        self.__defrag_start_y: int = 0
        self.__defrag_end_x: int = 0
        self.__defrag_end_y: int = 0

        self.__status_cluster_counter_start_x: int = 0
        self.__status_cluster_counter_start_y: int = 0
        self.cluster_counter: int = 0

        self.__status_percentage_bar_start_x: int = 0
        self.__status_percentage_bar_start_y: int = 0
        self.__status_percentage_bar_blocks_added: int = 0

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
            y: int = random.randrange(self.__defrag_start_y, self.__defrag_end_y)
            x: int = random.randrange(self.__defrag_start_x, self.__defrag_end_x)

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
            # Do not add it in the buffer if it is just SPACE character
            if pixel != " ":
                self.__pixel_buffer[key] = (pixel, color)
            self.stdscr.addch(y, x, pixel, attrs)
        except curses.error:
            # Bottom-right corner, which is a classic curses trouble spot
            if (x, y) != (self.__screen_width - 1, self.__screen_height - 1):
                # Drop cache entry to be safe.
                self.__pixel_buffer.pop(key, None)

    def __draw_text_block(
        self,
        text: str,
        color: PixelColor,
        origin_x: int,
        origin_y: int,
        box: BoxKind,
    ) -> None:
        """
        Draw a multi-line text block starting at (origin_x, origin_y).
        Newlines in `text` move to the next row and reset X to origin_x.
        """

        x = origin_x
        y = origin_y

        #
        if box == BoxKind.BOX_DEFRAG:
            self.__defrag_start_x = x + 1
            self.__defrag_start_y = y + 1

        if box == BoxKind.BOX_STATUS:
            self.__status_cluster_counter_start_x = x + CLUSTER_COUNT_ORIGIN_X_DELTA
            self.__status_cluster_counter_start_y = y + CLUSTER_COUNT_ORIGIN_Y_DELTA
            self.__status_percentage_bar_start_x = x + PERCENTAGE_BAR_ORIGIN_X_DELTA
            self.__status_percentage_bar_start_y = y + PERCENTAGE_BAR_ORIGIN_Y_DELTA

        for ch in text:
            if not ch.isprintable():
                if box == BoxKind.BOX_DEFRAG:
                    #
                    self.__defrag_end_y = y

                y += 1
                x = origin_x
                continue

            self.__draw_pixel(
                pixel=ch,
                color=color,
                x=x,
                y=y,
            )

            if box == BoxKind.BOX_DEFRAG:
                #
                self.__defrag_end_x = x

            x += 1

    def __draw_layout(self) -> None:
        """
        Ask LayoutManager to compute the layout and draw all blocks.
        """
        blocks = self.__layout.build_layout(
            screen_width=self.__screen_width,
            screen_height=self.__screen_height,
        )

        for block in blocks:
            self.__draw_text_block(
                text=block.text,
                color=self.__dominant_colors,
                origin_x=block.origin_x,
                origin_y=block.origin_y,
                box=block.kind,
            )

        self.__capacity = (self.__defrag_end_x - self.__defrag_start_x) * (
            self.__defrag_end_y - self.__defrag_start_y
        )
        self.stdscr.refresh()

    def __print_error_msg(self) -> None:
        """
        Render a simple error message when the terminal is too small.
        """
        error_blocks = self.__layout.build_small_screen_error_layout(
            screen_width=self.__screen_width,
            screen_height=self.__screen_height,
        )

        attrs = curses.color_pair(self.__dominant_colors.value)

        for block in error_blocks:
            try:
                self.stdscr.addstr(
                    block.origin_y,
                    block.origin_x,
                    block.text,
                    attrs,
                )
            except curses.error:
                pass  # ignore bottom-right curses glitch

        self.stdscr.refresh()

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

        - Updates the cached screen width/height and capacity.
        - Clears the screen and local pixel buffer.
        - Re-evaluates whether the standard layout still fits:
            - If it fits, redraws the full layout.
            - Otherwise, prints the small-screen error message.
        """

        self.__view_is_ready(False)

        self.__screen_height, self.__screen_width = self.stdscr.getmaxyx()
        self.stdscr.clear()
        self.__pixel_buffer.clear()
        self.cluster_counter = 0

        # Check if the layout fits in the current terminal
        if self.__layout.check_fit(self.__screen_width, self.__screen_height):
            self.__draw_layout()
            self.__view_is_ready(True)
        else:
            self.__print_error_msg()

    def __application(self, stdscr: curses.window) -> None:
        """
        Main curses application (entry for `curses.wrapper`).

        Behaviour:
            - Initializes the curses environment and color pairs.
            - Checks if the layout fits; if not, shows a centered error
              message instead of the full layout.
            - Waits for key presses in a loop.
            - Reacts to terminal resizes by redrawing the screen or the
              error message as needed.
            - Exits when 'q' or ESC is pressed.

        The function owns curses state until it returns; `curses.wrapper`
        restores terminal modes afterwards even if an exception bubbles up.
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
        self.stdscr.refresh()

        # Check if the layout fits in the current terminal
        if self.__layout.check_fit(self.__screen_width, self.__screen_height):
            self.__draw_layout()
            self.__view_is_ready(True)
        else:
            self.__print_error_msg()

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
            # Avoit new entries befire we clean the whole screen
            self.__view_is_ready(False)
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

        # If we've already drawn to every cell
        if self.cluster_counter >= self.__capacity:
            # TODO: What to do next?
            self.__view_is_ready(False)

        x, y = self.__get_coordinates()
        pixel: str = self.__get_pixel()
        color: PixelColor = self.__get_color()

        self.__draw_pixel(pixel, color, x, y)
        self.cluster_counter += 1

        self.stdscr.addstr(
            self.__status_cluster_counter_start_y,
            self.__status_cluster_counter_start_x,
            f"{self.cluster_counter:06d}",
            curses.color_pair(self.__dominant_colors.value),
        )

        self._update_progress_bar()

        self.stdscr.refresh()

    def _update_progress_bar(self) -> None:
        # Clamp cluster_counter so we never go past 100%
        progress = min(self.cluster_counter, self.__capacity) / self.__capacity

        BAR_WIDTH = 72  # width of the bar in characters

        # Target number of blocks that *should* be filled now
        target_blocks = int(progress * BAR_WIDTH)

        # How many blocks we have already drawn
        current_blocks = self.__status_percentage_bar_blocks_added

        # Draw until the visual bar catches up with the logical progress
        while current_blocks < target_blocks and current_blocks < BAR_WIDTH:
            x = self.__status_percentage_bar_start_x + current_blocks

            self.stdscr.addstr(
                self.__status_percentage_bar_start_y,
                x,
                "▓",
                curses.color_pair(self.__dominant_colors.value),
            )

            current_blocks += 1
            self.__status_percentage_bar_blocks_added = current_blocks
