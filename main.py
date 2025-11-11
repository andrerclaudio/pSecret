#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Minimal curses-based pixel drawer.
"""

# Built-in libraries
import logging
import signal
import sys
import threading
import time
from functools import partial

# Custom-made libraries
from view import ViewConnector

# Initialize logger configuration
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s [%(levelname)s]: %(message)s"
)
LOG = logging.getLogger(__name__)


class AppControlFlags:
    """
    This class provides flags for controlling application behavior, such as whether to keep runningand
    wait between operations.

    Attributes:
        _keep_running (bool): Flag indicating if the application should continue executing.
        _wait (bool): Flag determining operation timing intervals.
    """

    def __init__(self) -> None:
        self._keep_running = True
        self._wait = True

    @property
    def keep_running(self) -> bool:
        """Indicates if the application should continue running."""
        return self._keep_running

    @keep_running.setter
    def keep_running(self, value: bool) -> None:
        """Enforces a change to whether the application will run in the background."""
        self._keep_running = value


class Job(threading.Thread):
    """
    Executes recurring tasks in a separate thread with synchronized control and prioritization.

    Provides coordinated task execution with thread-safe state management,
    priority-based scheduling, and graceful shutdown capabilities.

    Attributes:
        control (AppControlFlags): Shared application control flags for system state.
        condition (threading.Condition): Synchronization primitive for wait/notify.
        active (bool): Indication about what is the Thread state.Defaults to OFF.
        thread_name (str): Unique identifier for this job instance.
    """

    def __init__(
        self,
        control: AppControlFlags,
        condition: threading.Condition,
        thread_name: str,
    ) -> None:
        """
        Initialize a managed job thread.

        Args:
            control: Shared application state controller
            condition: Coordination primitive for thread scheduling
            active: Hold the thread state (ON or OFF)
            thread_name: Unique identifier for this job
        """
        threading.Thread.__init__(self)
        self.name = thread_name

        self._control: AppControlFlags = control
        self._condition: threading.Condition = condition

        self.start()

    def __app_is_running(self) -> bool:
        """
        Check if the application is running.

        Returns:
            bool: True if the application should continue running, False otherwise.
        """
        with self._condition:
            return self._control.keep_running

    def run(self) -> None:
        """
        Main execution loop managing task lifecycle and coordination.

        Implements priority-based task scheduling with configurable delays
        and system state monitoring for graceful termination.
        """
        LOG.info(f"Initializing thread '{self.name}'")

        try:
            while self.__app_is_running():
                # do nothing
                time.sleep(1)

            LOG.info(f"[{self.name}] Finished successfully!")

        except Exception as e:
            LOG.error(f"Task failure in '{self.name}': {e}", exc_info=False)


if __name__ == "__main__":
    LOG.info("Starting the application!")

    try:
        # General Application control flags
        app_control_flags = AppControlFlags()

        # Define a lock for synchronization
        lock: threading.Lock = threading.Lock()
        condition_flag: threading.Condition = threading.Condition(lock=lock)

        # Stores Job thread objects and later joins them.
        # Its purpose is to track active threads.
        threads = []

        t = Job(
            control=app_control_flags,
            condition=condition_flag,
            thread_name=str("Any thread"),
        )
        threads.append(t)

        # Wait until all threads are fully started before proceeding
        for t in threads:
            while not t.is_alive():
                time.sleep(0.01)  # Small sleep to avoid busy-waiting

        # Blocking
        ViewConnector().run()

        with condition_flag:
            # Release the resouces
            app_control_flags.keep_running = False

        # Keep the main thread running until the application is stopped
        for t in threads:
            # Wait for all threads to finish
            t.join()

        LOG.info("Releasing resources ...")

    except Exception as e:
        LOG.error(f"An error occurred: {e}", exc_info=True)

    finally:
        sys.exit(0)
