"""
jive.system — System properties and hardware capability management.

Ported from ``jive/System.lua`` in the original jivelite project.

The System class provides access to system-specific properties including:

* **Hardware capabilities** — touch, IR, power key, volume knob, etc.
* **Machine identification** — architecture, machine type, UUID, MAC address
* **File system** — user paths (settings, applets), file finding on search path
* **Atomic writes** — safe file writing with rename-on-close

In the original Lua code, ``System`` is partly implemented in C (for
``getMachine``, ``getArch``, ``getUserDir``, ``findFile``, ``getUUID``,
``getMacAddress``, ``atomicWrite``, etc.).  This Python port provides
pure-Python implementations using ``pathlib``, ``platform``, ``uuid``,
and ``tempfile``.

Usage::

    from jive.system import System

    system = System()

    # Check capabilities
    system.set_capabilities({"touch": 1, "ir": 1})
    assert system.has_touch()
    assert system.has_ir()
    assert not system.has_volume_knob()

    # User paths
    user_dir = system.get_user_dir()
    settings_dir = system.get_settings_dir()

    # Find a file on the search path
    path = system.find_file("applets/NowPlaying/NowPlayingApplet.lua")

    # Atomic write
    system.atomic_write("/path/to/settings.json", '{"volume": 50}')

Copyright 2010 Logitech. All Rights Reserved. (original Lua/C code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import os
import platform
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Union

from jive.utils.log import logger

log = logger("jivelite")

__all__ = ["System"]

# ---------------------------------------------------------------------------
# All known capabilities (from the Lua original)
# ---------------------------------------------------------------------------

_ALL_CAPABILITIES: frozenset[str] = frozenset(
    {
        "touch",
        "ir",
        "powerKey",
        "presetKeys",
        "alarmKey",
        "homeAsPowerKey",
        "muteKey",
        "volumeKnob",
        "audioByDefault",
        "wiredNetworking",
        "deviceRotation",
        "coreKeys",
        "sdcard",
        "usb",
        "batteryCapable",
        "hasDigitalOut",
        "hasTinySC",
        "IRBlasterCapable",
    }
)


class System:
    """System properties and hardware capabilities.

    In the original jivelite code ``System`` is a singleton whose C
    portion is compiled into the binary.  Here we provide a plain
    Python class that can be instantiated once at startup and shared
    via ``jive_main``.

    For testing or headless operation, callers can override
    ``machine``, ``arch``, ``user_dir``, and ``search_paths`` via
    constructor arguments.
    """

    # JIVE_VERSION — mirrors the Lua global.
    JIVE_VERSION: str = "7.8"

    def __init__(
        self,
        *,
        machine: Optional[str] = None,
        arch: Optional[str] = None,
        user_dir: Optional[Union[str, Path]] = None,
        search_paths: Optional[Sequence[Union[str, Path]]] = None,
        mac_address: Optional[str] = None,
        uuid_str: Optional[str] = None,
    ) -> None:
        # Machine / arch --------------------------------------------------
        self._machine: str = machine or "jivelite"
        self._arch: str = arch or platform.machine() or "unknown"

        # Identity --------------------------------------------------------
        self._uuid: str = uuid_str or str(uuid.uuid4())
        self._mac_address: str = mac_address or self._generate_mac()

        # Capabilities ----------------------------------------------------
        self._capabilities: Dict[str, int] = {}
        self._touchpad_bottom_correction: int = 0

        # Paths -----------------------------------------------------------
        if user_dir is not None:
            self._user_dir = Path(user_dir)
        else:
            self._user_dir = self._default_user_dir()

        if search_paths is not None:
            self._search_paths: List[Path] = [Path(p) for p in search_paths]
        else:
            self._search_paths = self._default_search_paths()

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    def get_uuid(self) -> str:
        """Return the SqueezePlay UUID."""
        return self._uuid

    def get_mac_address(self) -> str:
        """Return the MAC address used as a unique device ID."""
        return self._mac_address

    def get_arch(self) -> str:
        """Return the system architecture (e.g. ``x86_64``, ``armv7l``)."""
        return self._arch

    def get_machine(self) -> str:
        """Return the machine type (e.g. ``jivelite``, ``jive``, ``squeezeplay``)."""
        return self._machine

    def set_machine(self, machine: str) -> None:
        """Override the machine type."""
        self._machine = machine

    def is_hardware(self) -> bool:
        """Return ``True`` if running on real Squeezebox hardware."""
        return self._machine != "jivelite"

    # ------------------------------------------------------------------
    # Capabilities
    # ------------------------------------------------------------------

    def set_capabilities(self, capabilities: Dict[str, int]) -> None:
        """Set the hardware capabilities dict.

        Unknown capability names are logged as warnings.
        """
        for cap in capabilities:
            if cap not in _ALL_CAPABILITIES:
                log.warn("Unknown capability: %s", cap)
        self._capabilities = dict(capabilities)

    def add_capability(self, name: str, value: int = 1) -> None:
        """Add a single capability."""
        if name not in _ALL_CAPABILITIES:
            log.warn("Unknown capability: %s", name)
        self._capabilities[name] = value

    def remove_capability(self, name: str) -> None:
        """Remove a single capability."""
        self._capabilities.pop(name, None)

    def has_capability(self, name: str) -> bool:
        """Generic capability check."""
        return name in self._capabilities

    # --- Convenience capability methods (match Lua API 1:1) ---

    def has_tiny_sc(self) -> bool:
        return "hasTinySC" in self._capabilities

    def has_digital_out(self) -> bool:
        return "hasDigitalOut" in self._capabilities

    def has_touch(self) -> bool:
        return "touch" in self._capabilities

    def has_ir(self) -> bool:
        return "ir" in self._capabilities

    def has_home_as_power_key(self) -> bool:
        return "homeAsPowerKey" in self._capabilities

    def has_power_key(self) -> bool:
        return "powerKey" in self._capabilities

    def has_mute_key(self) -> bool:
        return "muteKey" in self._capabilities

    def has_volume_knob(self) -> bool:
        return "volumeKnob" in self._capabilities

    def has_audio_by_default(self) -> bool:
        return "audioByDefault" in self._capabilities

    def has_wired_networking(self) -> bool:
        return "wiredNetworking" in self._capabilities

    def has_soft_power(self) -> bool:
        return self.has_touch() or self.has_power_key()

    def has_device_rotation(self) -> bool:
        return "deviceRotation" in self._capabilities

    def has_core_keys(self) -> bool:
        return "coreKeys" in self._capabilities

    def has_preset_keys(self) -> bool:
        return "presetKeys" in self._capabilities

    def has_alarm_key(self) -> bool:
        return "alarmKey" in self._capabilities

    def has_usb(self) -> bool:
        return "usb" in self._capabilities

    def has_sd_card(self) -> bool:
        return "sdcard" in self._capabilities

    def has_local_storage(self) -> bool:
        return self.has_usb() or self.has_sd_card() or not self.is_hardware()

    def has_battery_capability(self) -> bool:
        return "batteryCapable" in self._capabilities

    def has_ir_blaster_capability(self) -> bool:
        return "IRBlasterCapable" in self._capabilities

    # --- Touchpad correction ---

    def get_touchpad_bottom_correction(self) -> int:
        return self._touchpad_bottom_correction

    def set_touchpad_bottom_correction(self, value: int) -> None:
        self._touchpad_bottom_correction = value

    # ------------------------------------------------------------------
    # User paths
    # ------------------------------------------------------------------

    def get_user_dir(self) -> Path:
        """Return the user-specific directory for settings, applets, etc."""
        return self._user_dir

    def get_settings_dir(self) -> Path:
        """Return the user settings directory."""
        return self._user_dir / "settings"

    def get_user_applets_dir(self) -> Path:
        """Return the user-installed applets directory."""
        return self._user_dir / "applets"

    def init_user_path_dirs(self) -> None:
        """Create user directories if they don't exist."""
        for d in (self._user_dir, self.get_settings_dir(), self.get_user_applets_dir()):
            d.mkdir(parents=True, exist_ok=True)
            log.debug("Ensured directory: %s", d)

    # ------------------------------------------------------------------
    # Search paths
    # ------------------------------------------------------------------

    @property
    def search_paths(self) -> List[Path]:
        """Return the list of directories searched for applets/files."""
        return list(self._search_paths)

    @search_paths.setter
    def search_paths(self, paths: Sequence[Union[str, Path]]) -> None:
        self._search_paths = [Path(p) for p in paths]

    def add_search_path(self, path: Union[str, Path], *, prepend: bool = False) -> None:
        """Add a directory to the search path."""
        p = Path(path)
        if p not in self._search_paths:
            if prepend:
                self._search_paths.insert(0, p)
            else:
                self._search_paths.append(p)

    def find_file(self, relative_path: Union[str, Path]) -> Optional[Path]:
        """Find a file on the search path.

        Searches each directory in :attr:`search_paths` for
        *relative_path*.  Returns the first match as an absolute
        ``Path``, or ``None`` if not found.
        """
        rel = Path(relative_path)
        for base in self._search_paths:
            candidate = base / rel
            if candidate.exists():
                return candidate
        return None

    def find_all_files(self, relative_path: Union[str, Path]) -> List[Path]:
        """Find all occurrences of a file on the search path."""
        rel = Path(relative_path)
        results: List[Path] = []
        for base in self._search_paths:
            candidate = base / rel
            if candidate.exists():
                results.append(candidate)
        return results

    # ------------------------------------------------------------------
    # Atomic write
    # ------------------------------------------------------------------

    @staticmethod
    def atomic_write(filepath: Union[str, Path], content: str) -> None:
        """Write *content* to *filepath* atomically.

        Writes to a temporary file in the same directory, then renames
        it to the target path.  This avoids partial writes on crash.

        On Windows, ``os.replace`` is used which is atomic on NTFS for
        same-volume renames.
        """
        target = Path(filepath)
        target.parent.mkdir(parents=True, exist_ok=True)

        # Write to a temporary file in the same directory
        fd, tmp_path = tempfile.mkstemp(
            dir=str(target.parent),
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            # Atomic rename
            os.replace(tmp_path, str(target))
        except BaseException:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _default_user_dir() -> Path:
        """Determine the default user directory.

        Follows the same convention as the C implementation:
        - Linux/macOS: ``~/.jivelite``
        - Windows: ``%APPDATA%/jivelite`` or ``~/.jivelite``
        """
        if os.name == "nt":
            appdata = os.environ.get("APPDATA")
            if appdata:
                return Path(appdata) / "jivelite"
        return Path.home() / ".jivelite"

    @staticmethod
    def _generate_mac() -> str:
        """Generate a pseudo-MAC address from the system UUID.

        Returns a colon-separated MAC string like ``00:04:20:xx:xx:xx``.
        The first three octets match the Logitech OUI used by
        SqueezePlay.
        """
        node = uuid.getnode()
        octets = []
        for i in range(5, -1, -1):
            octets.append((node >> (8 * i)) & 0xFF)
        # Use Logitech OUI prefix, keep last 3 octets from the node
        return "00:04:20:{:02x}:{:02x}:{:02x}".format(octets[3], octets[4], octets[5])

    @staticmethod
    def _default_search_paths() -> List[Path]:
        """Build the default search paths.

        Looks for a ``share/jive`` directory relative to the script
        or package location.  Also includes the user applets directory.
        """
        paths: List[Path] = []

        # 1. Try the directory of the running package
        pkg_dir = Path(__file__).resolve().parent
        # e.g. jivelite-py/jive -> jivelite-py
        project_root = pkg_dir.parent

        # Common locations for applets / share data
        candidates = [
            project_root / "share" / "jive",
            project_root / "share",
            project_root,
            # Original jivelite layout
            pkg_dir.parent.parent / "share" / "jive",
        ]

        for c in candidates:
            if c.is_dir() and c not in paths:
                paths.append(c)

        return paths

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        caps = ", ".join(sorted(self._capabilities.keys())) or "none"
        return (
            f"System(machine={self._machine!r}, arch={self._arch!r}, "
            f"uuid={self._uuid!r}, capabilities=[{caps}])"
        )
