"""
jive.ui.audio — Audio effects and playback for the Jivelite Python3 port.

Ported from ``Audio.lua`` in the original jivelite project.

In the original Jivelite, Audio is implemented mostly in C and provides
sound-effect loading and playback via SDL_mixer.  This Python port
provides the same API surface as a stub/placeholder, with optional
pygame.mixer integration when available.

Usage::

    from jive.ui.audio import Audio

    # Load a sound effect
    sound = Audio.load_sound("click.wav", channel=1)

    # Play it
    sound.play()

    # Enable/disable all effects
    Audio.effects_enable(False)

Copyright 2010 Logitech. All Rights Reserved. (original Lua/C code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import (
    Any,
    Optional,
)

from jive.utils.log import logger

__all__ = ["Audio", "Sound"]

log = logger("jivelite.ui")

# Try to import pygame.mixer — it may not be available in headless / CI
# environments or when pygame is not fully initialised.
_mixer = None
try:
    import pygame.mixer as _mixer
except Exception:  # pragma: no cover
    pass


class Sound:
    """
    A loaded sound effect that can be played, enabled, or disabled.

    Wraps a ``pygame.mixer.Sound`` when available, otherwise acts as a
    silent stub.

    Parameters
    ----------
    pygame_sound : pygame.mixer.Sound or None
        The underlying pygame sound object.  ``None`` for a stub.
    channel : int
        The mixer channel hint (0-based).
    """

    def __init__(
        self,
        pygame_sound: Any = None,
        channel: int = 0,
    ) -> None:
        self._sound: Any = pygame_sound
        self._channel: int = channel
        self._enabled: bool = True

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    def play(self) -> None:
        """
        Play the sound effect once.

        Does nothing if the sound is disabled, if effects are globally
        disabled, or if no underlying pygame sound is available.
        """
        if not self._enabled:
            return
        if not Audio.is_effects_enabled():
            return
        if self._sound is None:
            return
        try:
            self._sound.play()
        except Exception:
            log.warn("Sound.play() failed")

    def stop(self) -> None:
        """Stop playback of this sound effect."""
        if self._sound is None:
            return
        try:
            self._sound.stop()
        except Exception:
            log.warn("Sound.stop() failed")

    # ------------------------------------------------------------------
    # Enable / disable
    # ------------------------------------------------------------------

    def enable(self, enabled: bool = True) -> None:
        """
        Enable or disable this individual sound effect.

        Parameters
        ----------
        enabled : bool
            ``True`` to enable, ``False`` to disable.
        """
        self._enabled = enabled

    def is_enabled(self) -> bool:
        """Return ``True`` if this sound effect is enabled."""
        return self._enabled

    isEnabled = is_enabled

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def channel(self) -> int:
        """Return the mixer channel hint for this sound."""
        return self._channel

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        has_sound = self._sound is not None
        return (
            f"Sound(channel={self._channel}, "
            f"enabled={self._enabled}, "
            f"loaded={has_sound})"
        )

    def __str__(self) -> str:
        return self.__repr__()


class Audio:
    """
    Audio effects manager (class-level / static API).

    Mirrors the Lua ``jive.ui.Audio`` class which provides class-level
    methods for loading sounds and toggling global effects.

    In the original C implementation, this wraps SDL_mixer channels.
    Here we use ``pygame.mixer`` when available, falling back to silent
    stubs.
    """

    _effects_enabled: bool = True
    _mixer_initialised: bool = False

    # ------------------------------------------------------------------
    # Mixer initialisation
    # ------------------------------------------------------------------

    @classmethod
    def _ensure_mixer(cls) -> bool:
        """
        Lazily initialise the pygame mixer if not already done.

        Returns ``True`` if the mixer is available, ``False`` otherwise.
        """
        if cls._mixer_initialised:
            return _mixer is not None

        cls._mixer_initialised = True

        if _mixer is None:
            log.debug("pygame.mixer not available — audio stubs active")
            return False

        try:
            if not _mixer.get_init():
                _mixer.init()
            log.debug("pygame.mixer initialised")
            return True
        except Exception:
            log.warn("Failed to initialise pygame.mixer")
            return False

    # ------------------------------------------------------------------
    # Sound loading
    # ------------------------------------------------------------------

    @classmethod
    def load_sound(
        cls,
        filename: str,
        channel: int = 0,
    ) -> Sound:
        """
        Load a sound effect from a WAV file.

        Parameters
        ----------
        filename : str
            Path to the WAV (or OGG) file to load.
        channel : int, optional
            Mixer channel hint (default 0).  In the original C code,
            different channels are used for UI sounds vs. other effects.

        Returns
        -------
        Sound
            A :class:`Sound` object.  If loading fails, returns a silent
            stub that can still be called without errors.
        """
        if not cls._ensure_mixer():
            log.debug("load_sound(%r) — returning silent stub", filename)
            return Sound(None, channel)

        try:
            pg_sound = _mixer.Sound(filename)
            log.debug("Loaded sound: %s", filename)
            return Sound(pg_sound, channel)
        except Exception:
            log.warn("Failed to load sound:", filename)
            return Sound(None, channel)

    @classmethod
    def loadSound(cls, filename: str, channel: int = 0) -> Sound:
        """Alias for :meth:`load_sound` (Lua API compatibility)."""
        return cls.load_sound(filename, channel)

    # ------------------------------------------------------------------
    # Global effects enable / disable
    # ------------------------------------------------------------------

    @classmethod
    def effects_enable(cls, enabled: bool = True) -> None:
        """
        Enable or disable all sound effects globally.

        Parameters
        ----------
        enabled : bool
            ``True`` to enable effects, ``False`` to silence them.
        """
        cls._effects_enabled = enabled
        log.debug("Audio effects %s", "enabled" if enabled else "disabled")

    effectsEnable = effects_enable

    @classmethod
    def is_effects_enabled(cls) -> bool:
        """Return ``True`` if sound effects are globally enabled."""
        return cls._effects_enabled

    isEffectsEnabled = is_effects_enabled

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"Audio(effects_enabled={self._effects_enabled}, "
            f"mixer_init={self._mixer_initialised})"
        )

    def __str__(self) -> str:
        return self.__repr__()
