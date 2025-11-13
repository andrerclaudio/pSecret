class AppControlFlags:
    """
    Shared flags used to coordinate application behaviour across threads.

    The flags are read and updated by multiple threads to signal when the
    application should keep running and whether the curses-based view is
    initialized and ready to be used.

    Attributes:
        _keep_running (bool): Internal flag indicating if the application
            should continue executing.
        _view_ready (bool): Internal flag indicating if the curses view is
            fully initialized and ready to receive updates.
    """

    def __init__(self) -> None:
        self._keep_running: bool = True
        self._view_ready: bool = True

    @property
    def keep_running(self) -> bool:
        """Indicates whether the application should continue running."""
        return self._keep_running

    @keep_running.setter
    def keep_running(self, value: bool) -> None:
        """
        Update the running flag.

        When set to False, cooperative threads should finish their work
        and shut down gracefully.
        """
        self._keep_running = value

    @property
    def view_ready(self) -> bool:
        """
        Indicates whether the curses view is initialized and ready.

        When False, worker threads should avoid drawing to the screen.
        """
        return self._view_ready

    @view_ready.setter
    def view_ready(self, value: bool) -> None:
        """
        Update the view readiness flag.

        Args:
            value: True when the curses view has been initialized and is
                safe to use, False when it is being created or torn down.
        """
        self._view_ready = value
