import threading


class RuntimeController:
    """
    Thread-safe coordination class using threading.Events.

    This acts as the "Traffic Cop" for the application, allowing the
    threads to communicate state without race conditions.
    """

    def __init__(self) -> None:
        # Event is False by default.
        self._stop_event: threading.Event = threading.Event()
        self._view_ready_event: threading.Event = threading.Event()

    def should_stop(self) -> bool:
        """Returns True if the application has been signaled to stop."""
        return self._stop_event.is_set()

    def signal_stop(self) -> None:
        """
        Signals all threads to stop immediately.

        This sets the internal event flag. Any thread waiting on
        wait_for_stop() will wake up immediately.
        """
        self._stop_event.set()

    def is_view_ready(self) -> bool:
        """Checks if the UI is fully initialized and safe to draw on."""
        return self._view_ready_event.is_set()

    def set_view_ready(self, ready: bool = True) -> None:
        """
        Updates the UI readiness state.

        Args:
            ready: True if Curses is initialized and sized; False during resizing or shutdown.
        """
        if ready:
            self._view_ready_event.set()
        else:
            self._view_ready_event.clear()

    def wait_for_stop(self, timeout: float) -> bool:
        """
        Blocks the calling thread for 'timeout' seconds, OR until stop is signaled.

        This is a 'Smart Sleep'. It replaces time.sleep().

        Returns:
            True if the stop signal was received (wake up!),
            False if the timeout expired (continue working).
        """
        return self._stop_event.wait(timeout)
