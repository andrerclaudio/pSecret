import logging
import threading

from control import RuntimeController
from view import CursesRenderer

LOG = logging.getLogger(__name__)


class PixelSpawner(threading.Thread):
    """
    Background worker thread that triggers drawing events.
    Inherits from threading.Thread to run in parallel with the UI.
    """

    def __init__(
        self,
        control: RuntimeController,
        view: CursesRenderer,
        thread_name: str,
    ) -> None:
        threading.Thread.__init__(self, name=thread_name)
        self._control = control
        self._view = view

    def run(self) -> None:
        """
        Main lifecycle of the background thread.
        Runs until control.should_stop() returns True.
        """
        LOG.info(f"Thread '{self.name}' started.")

        try:
            # Main Worker Loop
            while not self._control.should_stop():
                # SMART WAIT:
                # Instead of time.sleep(), we wait on the stop event.
                # If the user hits 'q' instantly, this returns True immediately,
                # allowing the thread to exit without finishing a sleep cycle.
                stop_signal_received: bool = self._control.wait_for_stop(
                    self._view.DRAW_INTERVAL
                )

                if stop_signal_received:
                    break

                # Critical Check:
                # Only attempt to draw if the Curses window is valid.
                # This prevents drawing while the terminal is resizing or quiting.
                if self._control.is_view_ready():
                    self._view.pulse()

            LOG.info(f"[{self.name}] Shutdown complete.")

        except Exception as e:
            LOG.error(f"Task failure in '{self.name}': {e}", exc_info=True)
