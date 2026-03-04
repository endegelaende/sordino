"""
jive.applets.HttpAuth.HttpAuthMeta — Meta class for HttpAuth.

Ported from ``share/jive/applets/HttpAuth/HttpAuthMeta.lua`` in the
original jivelite project.

The Meta class:

* Declares version compatibility (1, 1)
* Provides empty default settings
* Registers the ``squeezeCenterPassword`` service
* Restores saved credentials to SlimServer on startup

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

__all__ = ["HttpAuthMeta"]

log = logger("applet.HttpAuth")


class HttpAuthMeta(AppletMeta):
    """Meta-information for the HttpAuth applet.

    Registers the ``squeezeCenterPassword`` service and restores
    previously saved credentials to SlimServer instances.
    """

    def jive_version(self) -> Tuple[int, int]:
        return (1, 1)

    def default_settings(self) -> Optional[Dict[str, Any]]:
        return {}

    def register_applet(self) -> None:
        self.register_service("squeezeCenterPassword")

        settings = self.get_settings()
        if not settings:
            return

        # Store credentials in the module-level _credentials dict so that
        # SlimServer instances pick them up when they connect.
        try:
            from jive.slim import slim_server as _ss_mod

            for server_uuid, cred in settings.items():
                if isinstance(cred, dict):
                    _ss_mod._credentials[server_uuid] = cred
        except ImportError:
            log.debug("slim_server module not available — credentials not restored")
