#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Application Entry Point.
Orchestrates the Runtime Controller, the Renderer, and the Background Worker.
"""

import logging
import sys

from control import RuntimeController
from tasks import PixelSpawner
from view import CursesRenderer

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s]: %(message)s"
)
LOG = logging.getLogger(__name__)


def application() -> None:
    LOG.info("Starting application...")

    # Initialize Control (Thread-safe communication channel)
    controller = RuntimeController()

    # Initialize Components
    view = CursesRenderer(control=controller)

    spawner = PixelSpawner(
        control=controller,
        view=view,
        thread_name="PixelSpawner",
    )

    try:
        # Start Background Threads
        spawner.start()

        # Transfer control to Curses (Blocking)
        view.run()

    except Exception as e:
        LOG.error(f"Critical error: {e}", exc_info=True)

    finally:
        LOG.info("Stopping background threads...")

        # Signal threads to stop waiting and exit loops
        controller.signal_stop()

        # Wait for thread to finish its current task
        if spawner.is_alive():
            spawner.join(timeout=2.0)

        LOG.info("Exiting.")
        sys.exit(0)


if __name__ == "__main__":
    application()
