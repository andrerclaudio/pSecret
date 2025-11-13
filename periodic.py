# Built-in libraries
import logging
import threading
import time

# Custom-made libraries
from control import AppControlFlags
from view import ViewConnector

LOG = logging.getLogger(__name__)


class Job(threading.Thread):
    """
    Executes recurring tasks in a separate thread with synchronized control.

    The job periodically calls the associated view's `pulse()` method while
    the application is running and the view is marked as ready. It uses a
    shared condition object to synchronize access to the control flags.

    Attributes:
        _control (AppControlFlags): Shared application control flags.
        _condition (threading.Condition): Synchronization primitive used
            to guard access to the shared flags.
        _view (ViewConnector): View object responsible for drawing to
            the curses screen.
        name (str): Name of the thread (inherited from `threading.Thread`).
    """

    def __init__(
        self,
        control: AppControlFlags,
        condition: threading.Condition,
        view: ViewConnector,
        thread_name: str,
    ) -> None:
        """
        Initialize and start a managed job thread.

        The thread is started immediately after initialization and will
        continue running until `control.keep_running` is set to False.

        Args:
            control: Shared application state controller used to determine
                whether the application is still running and if the view
                is ready.
            condition: Coordination primitive that guards access to the
                shared control flags.
            view: Curses view connector that exposes the `pulse()` method
                and the `PULSE_TIMEOUT` interval.
            thread_name: Human-readable identifier for this job thread.
        """

        threading.Thread.__init__(self)
        self.name = thread_name

        self._control: AppControlFlags = control
        self._condition: threading.Condition = condition
        self._view: ViewConnector = view

        self.start()

    def __app_is_running(self) -> bool:
        """
        Check if the application is still marked as running.

        Returns:
            True if the application should continue running, False otherwise.
        """
        with self._condition:
            return self._control.keep_running

    def __view_is_ready(self) -> bool:
        """
        Check if the curses view is initialized and ready for drawing.

        Returns:
            True if drawing operations are allowed, False otherwise.
        """
        with self._condition:
            return self._control.view_ready

    def run(self) -> None:
        """
        Main execution loop for the background job.

        The loop:
            - Sleeps for the interval defined by the view's `PULSE_TIMEOUT`.
            - If the view is ready, calls `view.pulse()` to perform a draw.
            - Exits cleanly once the application is no longer running.
        """

        LOG.info(f"Initializing thread '{self.name}'")

        try:
            while self.__app_is_running():
                time.sleep(self._view.PULSE_TIMEOUT)

                if self.__view_is_ready():
                    self._view.pulse()

            LOG.info(f"[{self.name}] Finished successfully!")

        except Exception as e:
            LOG.error(f"Task failure in '{self.name}': {e}", exc_info=False)
