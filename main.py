#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Minimal curses-based pixel drawer.
"""

# Built-in libraries
import logging
import sys
import threading
import time

# Custom-made libraries
from control import AppControlFlags
from periodic import Job
from view import ViewConnector

# Initialize logger configuration
logging.basicConfig(
    level=logging.ERROR, format="%(asctime)s [%(levelname)s]: %(message)s"
)
LOG = logging.getLogger(__name__)


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

        view = ViewConnector(
            control=app_control_flags,
            condition=condition_flag,
        )

        t = Job(
            control=app_control_flags,
            condition=condition_flag,
            view=view,
            thread_name=str("Pulse thread"),
        )
        threads.append(t)

        # Wait until all threads are fully started before proceeding
        for t in threads:
            while not t.is_alive():
                time.sleep(0.01)  # Small sleep to avoid busy-waiting

        # Blocking
        view.run()

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
