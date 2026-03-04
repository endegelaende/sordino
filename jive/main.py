"""
jive.main — CLI entry point for the ``jivelite`` command.

This module provides the :func:`main` function referenced by the
``[project.scripts]`` section in ``pyproject.toml``::

    [project.scripts]
    jivelite = "jive.main:main"

It bootstraps the full JiveMain application, which in turn initialises
the Framework (pygame window), AppletManager, skin loading, and the
main event loop.

Usage::

    # From the command line (after ``pip install -e .``):
    jivelite

    # Or directly:
    python -m jive.main

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional, Sequence


def main(argv: Optional[Sequence[str]] = None) -> None:
    """Entry point for the ``sordino`` command."""

    # On Windows, set the AppUserModelID so the taskbar shows the
    # embedded .ico from the EXE instead of the default pygame icon.
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("sordino.jive.app")  # type: ignore[union-attr]
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        prog="sordino",
        description=(
            "Sordino — JiveLite-compatible Squeezebox controller UI for Resonance and Lyrion Music Server"
        ),
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=False,
        help="Run with SDL dummy video driver (no display)",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        default=False,
        help="Print version and exit",
    )

    args = parser.parse_args(argv)

    if args.version:
        try:
            from importlib.metadata import version as pkg_version

            ver = pkg_version("sordino")
        except Exception:
            ver = "unknown"
        print(f"sordino {ver}")
        return

    if args.headless:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

    # Install debug diagnostics if JIVELITE_DEBUG=1
    from jive.debug_bridge import auto_install

    auto_install()

    # Late import so that pygame is not initialised at module-load time
    # and so that SDL_VIDEODRIVER is set before anything touches pygame.
    from jive.jive_main import JiveMain

    try:
        JiveMain()
    except KeyboardInterrupt:
        print("\njivelite: interrupted — exiting.")
        sys.exit(0)


if __name__ == "__main__":
    main()
