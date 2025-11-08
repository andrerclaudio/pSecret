# Built-in libraries
import curses
import os
from enum import Enum
from typing import Dict, Optional


class PixelColor(Enum):
    BLACK = 8
    BLUE = 4
    CYAN = 6
    GREEN = 2
    MAGENTA = 5
    RED = 1
    WHITE = 7
    YELLOW = 3


class ViewConnector:
    """Manage screen operations using curses."""

    def __init__(self) -> None:
        # Ensure TERM is set to xterm-256color for proper color support
        os.environ["TERM"] = "xterm-256color"

        self.__stdscr: Optional[curses.window] = None
        self.__screen_height: int = 0
        self.__screen_width: int = 0
        self.__pixel_buffer: Dict[str, str] = {}

    @property
    def stdscr(self) -> curses.window:
        if self.__stdscr is None:
            raise RuntimeError("stdscr not initialized.")
        return self.__stdscr

    def __draw_pixel(self, pixel: str, color: PixelColor, x: int, y: int) -> None:
        color_pair = curses.color_pair(color.value)
        key = f"{x}:{y}"
        if self.__pixel_buffer.get(key) != pixel:
            self.__pixel_buffer[key] = pixel
            try:
                self.stdscr.addch(y, x, pixel, color_pair)
            except curses.error:
                self.__pixel_buffer.pop(key, None)

    def __colors_init(self) -> None:
        # Called only after wrapper gives us a real window.
        curses.start_color()
        curses.use_default_colors()
        for color in PixelColor:
            curses.init_pair(color.value, getattr(curses, f"COLOR_{color.name}"), -1)

    def __interpolate(self) -> None:
        update_the_screen = False
        if update_the_screen:
            self.stdscr.refresh()

    def __check_fit(self) -> bool:
        return True

    def __handle_resize(self) -> None:
        self.__screen_height, self.__screen_width = self.stdscr.getmaxyx()
        if not self.__check_fit():
            # Let wrapper unwind cleanly; don't endwin() manually.
            raise SystemExit(1)
        self.stdscr.clear()
        self.__pixel_buffer.clear()

    def __application(self, stdscr: curses.window) -> None:
        self.__stdscr = stdscr
        self.__screen_height, self.__screen_width = self.stdscr.getmaxyx()
        self.__colors_init()
        curses.curs_set(0)

        self.__draw_pixel("A", PixelColor.BLUE, 0, 0)

        try:
            while True:
                key = self.stdscr.getch()

                if curses.is_term_resized(self.__screen_height, self.__screen_width):
                    self.__handle_resize()

                if key in (ord("q"), 27):  # 'q' or ESC
                    break
        except KeyboardInterrupt:
            pass
        finally:
            self.stdscr.clear()
            self.stdscr.refresh()
            # No sys.exit() here; wrapper will restore the TTY.

    def run(self) -> None:
        try:
            curses.wrapper(self.__application)
        except curses.error:
            raise SystemExit(1)
