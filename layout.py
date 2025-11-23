from __future__ import annotations

# Built-in libraries
from dataclasses import dataclass
from typing import List, Tuple

BOX_STATUS: str = (
    "┌────────────────────────────────      STATUS      ────────────────────────────────┐\n"
    "│                                                                                  │\n"
    "│                                                                                  │\n"
    "│                                                                                  │\n"
    "│                                                                                  │\n"
    "│                                                                                  │\n"
    "│                                                                                  │\n"
    "│                                                                                  │\n"
    "│                                                                                  │\n"
    "│                                                                                  │\n"
    "└──────────────────────────────────────────────────────────────────────────────────┘\n"
)

BOX_INFORMATION: str = (
    "┌──────────────────────────────────────────────────────────────────────────────────┐\n"
    "│                                                                                  │\n"
    "│                                                                                  │\n"
    "│                                                                                  │\n"
    "│                                                                                  │\n"
    "│                                                                                  │\n"
    "│                                                                                  │\n"
    "│                                                                                  │\n"
    "│                                                                                  │\n"
    "│                                                                                  │\n"
    "└──────────────────────────────────────────────────────────────────────────────────┘\n"
)

TOP_GAP: int = 1
BOTTON_GAP: int = 1
SIDE_GAP: int = 1
VERTICAL_MIDDLE_GAP: int = 2


@dataclass(frozen=True)
class TextBlock:
    """
    Logical description of a text block to be drawn on screen.

    `text` is a multi-line ASCII block (may end with '\n').
    `origin_x` and `origin_y` are 0-based column/row positions.
    """

    text: str
    origin_x: int
    origin_y: int


class LayoutManager:
    """
    Compute the layout for the current screen scenario.

    This class knows:
    - The static text blocks (status, information).
    - The vertical gaps between them.
    - How to compute the "defrag" box dimensions and positions.

    It does *not* call curses directly; it only returns `TextBlock`s.
    """

    def __init__(self) -> None:
        # Load boxex details
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
        Returned as a multi-line string with '\n' at the end of each line.
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
        Position two boxes horizontally with symmetric side gaps:
        [side_gap] [left box] [horizontal_middle_gap] [right box] [side_gap]
        """

        # Remaining space after accounting for side gaps and box widths
        horizontal_middle_gap = screen_width - (
            2 * self._side_gap + left_width + right_width
        )

        if horizontal_middle_gap < 0:
            # No space for nice symmetric layout.
            # Fallback: pack boxes left.
            left_x = self._side_gap
            right_x = left_x + left_width + 1  # 1-char safety gap
            return left_x, right_x, 1

        left_x = self._side_gap
        right_x = self._side_gap + left_width + horizontal_middle_gap

        return left_x, right_x, horizontal_middle_gap

    def build_layout(
        self,
        screen_width: int,
        screen_height: int,
    ) -> List[TextBlock]:
        """
        Compute all text blocks that compose the scenario for a given screen.

        Returns:
            A list of TextBlock objects (defrag box, status, information).
        """
        blocks: List[TextBlock] = []

        # 1) Measure bottom boxes
        box_status_width, box_status_height = self.measure_text_block(self._box_status)
        box_information_width, _ = self.measure_text_block(self._box_information)

        # 2) Vertical placement of status / information boxes
        boxes_y_position: int = screen_height - (box_status_height + self._bottom_gap)

        # 3) Horizontal positions for the two boxes
        (box_status_x_position, box_information_x_position, gap_between_boxes_width) = (
            self.__compute_two_box_positions(
                screen_width=screen_width,
                left_width=box_status_width,
                right_width=box_information_width,
            )
        )

        # 4) Defrag box dimensions (big top box)
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

        # 5) Pack everything as TextBlock objects
        # Defrag box (top)
        blocks.append(
            TextBlock(
                text=box_defrag,
                origin_x=box_status_x_position,
                origin_y=self._top_gap,
            )
        )

        # Status box (bottom-left)
        blocks.append(
            TextBlock(
                text=self._box_status,
                origin_x=box_status_x_position,
                origin_y=boxes_y_position,
            )
        )

        # Information box (bottom-right)
        blocks.append(
            TextBlock(
                text=self._box_information,
                origin_x=box_information_x_position,
                origin_y=boxes_y_position,
            )
        )

        return blocks
