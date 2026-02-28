"""
SlimMenus applet package.

Manages server-driven home-menu items pushed from Lyrion Music Server
(formerly SqueezeCenter / Logitech Media Server) via the ``menustatus``
Comet subscription and the ``menu`` JSON-RPC command.

SlimMenus is responsible for:

- Subscribing to ``/slim/menustatus/<playerId>`` on the current server
  to receive real-time menu additions, removals, and updates.
- Fetching the initial menu tree from connected servers via the
  ``menu 0 100 direct:1`` request.
- Merging server-provided nodes and items into the JiveMain home menu.
- Handling server/player changes by tearing down old menus and
  requesting new ones.
- Providing the ``goHome``, ``hideConnectingToPlayer``, and
  ``warnOnAnyNetworkFailure`` services.

Ported from ``applets/SlimMenus/`` in the original jivelite Lua project.
"""
