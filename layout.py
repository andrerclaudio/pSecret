from __future__ import annotations

# Built-in libraries
from dataclasses import dataclass
from typing import List, Tuple
from enum import Enum

BOX_STATUS: str = (
    "┌──                                STATUS                                ──┐\n"
    "│                                                                          │\n"
    "│ Cluster                                                                  │\n"
    "│ ········································································ │\n"
    "│                          Elapsed Time  00:00:00                          │\n"
    "│                                                                          │\n"
    "│                                                                          │\n"
    "│                                                                          │\n"
    "│                                                                          │\n"
    "│                                                                          │\n"
    "└──────────────────────────────────────────────────────────────────────────┘\n"
)

BOX_INFORMATION: str = (
    "┌──────────────────────────────────────────────────────────────────────────┐\n"
    "│                                                                          │\n"
    "│                                                                          │\n"
    "│                                                                          │\n"
    "│                                                                          │\n"
    "│                                                                          │\n"
    "│                                                                          │\n"
    "│                                                                          │\n"
    "│                                                                          │\n"
    "│                                                                          │\n"
    "└──────────────────────────────────────────────────────────────────────────┘\n"
)

TOP_GAP: int = 1
BOTTON_GAP: int = 1
SIDE_GAP: int = 1
VERTICAL_MIDDLE_GAP: int = 2

CLUSTER_COUNT_ORIGIN_X_DELTA = 10
CLUSTER_COUNT_ORIGIN_Y_DELTA = 2

PERCENTAGE_BAR_ORIGIN_X_DELTA = 2
PERCENTAGE_BAR_ORIGIN_Y_DELTA = 3


class BoxKind(Enum):
    BOX_STATUS = 1
    BOX_INFORMATION = 2
    BOX_DEFRAG = 3
    BOX_SMALL_SCREEN_ERROR = 4


@dataclass(frozen=True)
class TextBlock:
    """
    Logical description of a text block to be drawn on screen.

    `text` is a multi-line ASCII block.
    `origin_x` and `origin_y` are 0-based column/row positions.
    `kind` identifies which logical box this is.
    """

    text: str
    origin_x: int
    origin_y: int
    kind: BoxKind


class LayoutManager:
    """
    Compute the layout for the current screen scenario.

    This class knows:
    - The static text blocks (status, information).
    - The vertical gaps between them.
    - How to compute the "defrag" box dimensions and positions.

    It does *not* call curses directly; it only returns `TextBlock`s.

    Call `check_fit()` before using `build_layout()` to ensure the
    computed layout fits into the given screen size.
    """

    def __init__(self) -> None:
        # Load boxes details
        self._box_status = BOX_STATUS
        self._box_information = BOX_INFORMATION
        self._top_gap = TOP_GAP
        self._middle_gap = VERTICAL_MIDDLE_GAP
        self._bottom_gap = BOTTON_GAP
        self._side_gap = SIDE_GAP

    @staticmethod
    def measure_text_block(text: str) -> Tuple[int, int]:
        """
        Measure a multi-line ASCII block and return (width, height).

        - `text` may end with a newline.
        - Width is the longest line.
        - Height is the number of lines.
        """
        lines = text.splitlines()

        if not lines:
            return (0, 0)

        height = len(lines)
        width = max(len(line) for line in lines)
        return width, height

    @staticmethod
    def build_box(width: int, height: int) -> str:
        """
        Build a rectangular ASCII box with the given width and height.

        Returns:
            A multi-line string where each line ends with '\n'.

        Notes:
            - If width or height is less than 2, an empty string is returned.
        """
        if width < 2 or height < 2:
            return ""

        # Top border
        top = "┌" + "─" * (width - 2) + "┐\n"

        # Middle rows
        middle_rows = ""
        for _ in range(height - 2):
            middle_rows += "│" + " " * (width - 2) + "│\n"

        # Bottom border
        bottom = "└" + "─" * (width - 2) + "┘\n"

        return top + middle_rows + bottom

    def __compute_two_box_positions(
        self,
        screen_width: int,
        left_width: int,
        right_width: int,
    ) -> tuple[int, int, int]:
        """
        Compute horizontal positions for two bottom boxes.

        Layout (after `check_fit` has succeeded):
            [side_gap] [left box] [horizontal_middle_gap >= 1]
            [right box] [side_gap]

        Args:
            screen_width: Total number of columns available.
            left_width:  Width of the left box (status box).
            right_width: Width of the right box (information box).

        Returns:
            A tuple (left_x, right_x, horizontal_middle_gap), where:
                - left_x  is the origin X for the left box.
                - right_x is the origin X for the right box.
                - horizontal_middle_gap is the number of columns between them.

        Assumptions:
            - `check_fit(screen_width, screen_height)` has already
              returned True for the relevant screen size, so there is
              always room for at least 1 column between the boxes.
        """

        # Remaining space after accounting for side gaps and box widths.
        horizontal_middle_gap = screen_width - (
            2 * self._side_gap + left_width + right_width
        )

        # After `check_fit`, horizontal_middle_gap is guaranteed >= 1.
        left_x = self._side_gap
        right_x = self._side_gap + left_width + horizontal_middle_gap

        return left_x, right_x, horizontal_middle_gap

    def check_fit(self, screen_width: int, screen_height: int) -> bool:
        """
        Decide whether the standard layout fits in the given screen size.

        Conditions:
        - Horizontally, the bottom row must fit:
          [SIDE_GAP] [STATUS] [>= 1 column gap] [INFORMATION] [SIDE_GAP]
        - Vertically, the top "defrag" box must have at least 3 rows.

        This method should be called before `build_layout()`; callers
        can fall back to an alternative layout if it returns False.
        """

        status_w, status_h = self.measure_text_block(self._box_status)
        info_w, _ = self.measure_text_block(self._box_information)

        # --- Horizontal fit -----------------------------------------------
        # Wanted at least 1 column between the two bottom boxes.
        min_horizontal = 2 * self._side_gap + status_w + 1 + info_w
        if screen_width < min_horizontal:
            return False

        # --- Vertical fit -------------------------------------------------
        # defrag_height = screen_height - (top + middle + status_h + bottom)
        # Required that >= 3.
        min_defrag_height = 3
        min_vertical = (
            self._top_gap
            + self._middle_gap
            + status_h
            + self._bottom_gap
            + min_defrag_height
        )

        if screen_height < min_vertical:
            return False

        return True

    def build_small_screen_error_layout(
        self,
        screen_width: int,
        screen_height: int,
    ) -> List[TextBlock]:
        """
        Build the minimal layout used when the screen is too small.

        The layout consists of a single TextBlock containing the message
        "Terminal too small for layout." centered in the available area.

        Intended usage:
            Call this when `check_fit(screen_width, screen_height)` has
            returned False.
        """
        message = "Terminal too small for layout."

        # If the message is longer than the screen, truncate.
        if len(message) > screen_width:
            message = message[:screen_width]

        # Center horizontally
        origin_x = max(0, (screen_width - len(message)) // 2)

        # Center vertically
        origin_y = max(0, screen_height // 2)

        return [
            TextBlock(
                text=message,
                origin_x=origin_x,
                origin_y=origin_y,
                kind=BoxKind.BOX_SMALL_SCREEN_ERROR,
            )
        ]

    def build_layout(
        self,
        screen_width: int,
        screen_height: int,
    ) -> List[TextBlock]:
        """
        Compute all text blocks that compose the standard layout.

        The layout is made of:
            - A "defrag" box at the top (big box).
            - A status box at the bottom-left.
            - An information box at the bottom-right.

        Args:
            screen_width:  Total number of columns.
            screen_height: Total number of rows.

        Returns:
            A list of TextBlock objects (defrag, status, information).

        Precondition:
            `check_fit(screen_width, screen_height)` must have returned
            True for the same dimensions; otherwise the computed sizes
            may not fit on screen.
        """
        blocks: List[TextBlock] = []

        box_status_width, box_status_height = self.measure_text_block(self._box_status)
        box_information_width, _ = self.measure_text_block(self._box_information)

        boxes_y_position: int = screen_height - (box_status_height + self._bottom_gap)

        (box_status_x_position, box_information_x_position, gap_between_boxes_width) = (
            self.__compute_two_box_positions(
                screen_width=screen_width,
                left_width=box_status_width,
                right_width=box_information_width,
            )
        )

        box_defrag_width: int = (
            box_status_width + gap_between_boxes_width + box_information_width
        )

        box_defrag_height: int = screen_height - (
            self._top_gap + self._middle_gap + box_status_height + self._bottom_gap
        )

        box_defrag: str = self.build_box(
            width=box_defrag_width,
            height=box_defrag_height,
        )

        # Defrag box (top)
        blocks.append(
            TextBlock(
                text=box_defrag,
                origin_x=box_status_x_position,
                origin_y=self._top_gap,
                kind=BoxKind.BOX_DEFRAG,
            )
        )

        # Status box (bottom-left)
        blocks.append(
            TextBlock(
                text=self._box_status,
                origin_x=box_status_x_position,
                origin_y=boxes_y_position,
                kind=BoxKind.BOX_STATUS,
            )
        )

        # Information box (bottom-right)
        blocks.append(
            TextBlock(
                text=self._box_information,
                origin_x=box_information_x_position,
                origin_y=boxes_y_position,
                kind=BoxKind.BOX_INFORMATION,
            )
        )

        return blocks
