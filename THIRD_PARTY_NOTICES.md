# Third-Party Notices

This file documents the licenses of third-party software used by Sordino.

Sordino itself is licensed under the **BSD 3-Clause License**.
See [LICENSE](LICENSE) for the full text.

---

## Upstream Project

Sordino is a Python 3 port of [JiveLite](https://github.com/ralph-irving/jivelite),
the community UI for the Lyrion Music Server (formerly Logitech Media Server / Squeezebox).

| Project | License | Copyright | Source |
|---------|---------|-----------|--------|
| **JiveLite** | BSD-3-Clause | 2010 Logitech, Inc.; 2013–2014 Adrian Smith | [ralph-irving/jivelite](https://github.com/ralph-irving/jivelite) |

The original codebase is C (SDL rendering) + Lua (UI logic). Sordino replaces
both layers with pure Python on top of pygame. The original BSD-3-Clause license
is preserved; see [LICENSE](LICENSE) for the combined copyright notice.

### Original Contributors (retained from JiveLite LICENSE)

| Contributor | Contribution |
|-------------|-------------|
| **Logitech, Inc.** | Original SqueezePlay / JiveLite codebase |
| **Adrian Smith** (triode1@btinternet) | JiveLite amendments and maintenance |
| **GWENDESIGN / Felix Mueller** | Grid layout code |
| **presslab-us** | Visualizer support ([presslab-us/jivelite](https://github.com/presslab-us/jivelite)) |
| **justblair** | Joggler skin ([justblair.co.uk](http://www.justblair.co.uk/more-fixing-of-squeezeplay-for-the-joggler.html)) |

---

## Bundled Assets

### Fonts

The bundled fonts are from the **GNU FreeFont** project and are redistributed
from the upstream JiveLite repository.

| Font | License | Source |
|------|---------|--------|
| **FreeSans.ttf** | GPL-3.0-or-later with Font Exception | [GNU FreeFont](https://www.gnu.org/software/freefont/) |
| **FreeSansBold.ttf** | GPL-3.0-or-later with Font Exception | [GNU FreeFont](https://www.gnu.org/software/freefont/) |

The **GPL Font Exception** permits embedding and distributing the font with
any work, regardless of the work's license. The exception reads:

> As a special exception, if you create a document which uses this font, and
> embed this font or unaltered portions of this font into the document, this
> font does not by itself cause the resulting document to be covered by the
> GNU General Public License. [...] However, if you modify the font, you may
> extend this exception to your version of the font, but you are not obligated
> to do so.

This exception means distributing FreeSans as a data file alongside BSD-3-Clause
code is fully permitted — the font's GPL does not extend to the rest of the project.

### Skin Images

Skin images (JogglerSkin, HDSkin, HDGridSkin, QVGAbaseSkin, etc.) originate from
the upstream JiveLite repository and are covered by the same BSD-3-Clause license
as the rest of the JiveLite project. These images are not bundled in the Sordino
git repository — they are copied from the sibling JiveLite checkout into `jive/data/`
at build time by the release workflow (`.github/workflows/release.yml`).

### Wallpaper Images

The wallpaper images in `jive/applets/SetupWallpaper/wallpaper/` originate from
the JiveLite repository (BSD-3-Clause).

---

## Python Dependencies (pip)

### Runtime (required)

| Package | License | URL |
|---------|---------|-----|
| **pygame-ce** | LGPL-2.1 (with zlib/libpng exception) | https://github.com/pygame-community/pygame-ce |

pygame-ce (Community Edition) wraps SDL2, SDL_image, SDL_mixer, and SDL_ttf.
It is licensed under LGPL-2.1, which permits use by BSD-licensed projects
without imposing copyleft on the application — the library is dynamically linked.

Transitive runtime dependencies of pygame-ce:

| Library | License | Notes |
|---------|---------|-------|
| SDL2 | zlib | https://libsdl.org/ |
| SDL2_image | zlib | https://github.com/libsdl-org/SDL_image |
| SDL2_mixer | zlib | https://github.com/libsdl-org/SDL_mixer |
| SDL2_ttf | zlib | https://github.com/libsdl-org/SDL_ttf |
| FreeType | FTL (BSD-like) or GPL-2.0 | https://freetype.org/ (FTL chosen) |
| zlib | zlib | https://zlib.net/ |
| libpng | libpng-2.0 (BSD-like) | http://www.libpng.org/ |
| libjpeg-turbo | BSD-3-Clause / IJG | https://libjpeg-turbo.org/ |

### Alternative Runtime (optional)

| Package | License | URL |
|---------|---------|-----|
| **pygame** (legacy) | LGPL-2.1 | https://github.com/pygame/pygame |

Users can install `pygame` instead of `pygame-ce` via
`pip install sordino[pygame-legacy]`. Same license terms apply.

### Dev only (not shipped)

| Package | License | URL |
|---------|---------|-----|
| pytest | MIT | https://github.com/pytest-dev/pytest |
| pytest-cov | MIT | https://github.com/pytest-dev/pytest-cov |
| mypy | MIT | https://github.com/python/mypy |
| ruff | MIT | https://github.com/astral-sh/ruff |

### Freeze only (not shipped in pip packages)

| Package | License | URL |
|---------|---------|-----|
| PyInstaller | GPL-2.0 (with bootloader exception) | https://github.com/pyinstaller/pyinstaller |

The **PyInstaller bootloader exception** explicitly permits distributing
frozen executables under any license. The exception reads:

> In addition to the permissions in the GNU General Public License, the
> authors give you unlimited permission to link or embed compiled bootloader
> and related files into combinations with other programs, and to distribute
> those combinations without any restriction coming from the use of those
> files.

This means frozen Sordino executables remain BSD-3-Clause.

---

## Python Standard Library

Sordino uses only the Python standard library beyond the dependencies listed
above. The Python standard library is licensed under the **PSF License
Agreement** (PSF-2.0), which is permissive and compatible with BSD-3-Clause.

---

## Server Counterpart

Sordino is designed to work with:

| Server | License | URL |
|--------|---------|-----|
| **Resonance** | GPL-2.0 | https://github.com/endegelaende/resonance-server |
| **Lyrion Music Server** | GPL-2.0 | https://github.com/LMS-Community/slimserver |

These are separate network services communicating over HTTP/Cometd — they are
not linked or bundled with Sordino. License compatibility is not a concern for
separate programs communicating over a network protocol.

---

## License Compatibility

Sordino is **BSD-3-Clause**. All dependencies are compatible:

| License | Packages | Compatibility |
|---------|----------|---------------|
| **BSD-3-Clause** | JiveLite (upstream), libjpeg-turbo | Same license family |
| **LGPL-2.1** | pygame-ce, pygame | Compatible — dynamically linked, not embedded |
| **zlib** | SDL2, SDL2_image, SDL2_mixer, SDL2_ttf, zlib | Permissive, compatible with BSD |
| **libpng-2.0** | libpng | Permissive (BSD-like), compatible |
| **FTL** | FreeType | Permissive (BSD-like), compatible |
| **GPL-3.0 + Font Exception** | FreeSans, FreeSansBold | Exception permits embedding as data files |
| **MIT** | pytest, mypy, ruff, pytest-cov | Permissive, compatible (dev only) |
| **PSF-2.0** | Python standard library | Permissive, compatible |
| **GPL-2.0 + Bootloader Exception** | PyInstaller | Exception permits frozen distribution under any license |

**Summary:** No dependency imposes copyleft obligations on Sordino. The project
can be freely distributed under BSD-3-Clause in all forms (source, wheel, frozen
executable).

---

*Last updated: June 2025*