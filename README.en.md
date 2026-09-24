# GMAGC: find a gobo from a photo

[Русская версия](README.md)

Author: @ANDY_BUM ([Telegram](https://t.me/Andy_bum)). The project is free; if it is useful to you, you can [support the author](https://boosty.to/djmaker/donate). License: [MIT](LICENSE).

GMAGC finds, in a gobo library (a folder in the grandMA structure), the file that best matches a **photo of a projection** on a wall or screen. It returns several best candidates: name, path and match score; identical gobos from different manufacturer folders are gathered into one card.

**Status: a desktop app with search and a server, an Android client with a camera, auto-update, a Windows installer (v0.10.0), and Windows, macOS and Android builds.** In the desktop window you choose the library folder, build the index and search for a gobo by photo (a file, the clipboard, or a phone over Wi-Fi); results show a preview, the name, the path (a click copies it to the clipboard) and the score. The Android app connects to the PC over Wi-Fi (it reads the QR code automatically, without pressing a button) and shoots the projection with a full-screen camera (with zoom and focus); the screen is locked in portrait. The core, the server, the client, the command line, the benchmark and the helper scripts are covered by tests (see `docs/superpowers/specs`).

**Interface languages: Russian and English.** The language is chosen on the “Settings” screen of both apps (“Auto (as in the system)”, “Русский”, “English”) and switches at once, without a restart.

## How it works

Photo → projection detection (a bright, low-saturation area; the pattern's spots merge into one) → normalization to 224×224 → 48 query variants (24 rotations × mirror) → feature vector → cosine search over the index cache → soft shape comparison for the 20 best families of duplicates → results by family. Everything works **offline**.

The feature vector is replaceable (`Embedder`): by default it is a simple 16×16 pixel vector, no model. The ready-made DINOv2-small neural network turned out worse and slower on this data; details are in `docs/benchmarks/2026-09-19-core-matcher.md`.

## Quick start

Python 3.12+ is required (tested on 3.14).

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:PYTHONPATH = "apps\desktop\src"    # bash: export PYTHONPATH=apps/desktop/src

# once (and after changes in the library; on a repeated run only new files are appended)
.venv\Scripts\python.exe -m gmagc_desktop.cli index D:\path\to\gobos --index .gmagc-cache\index.npz

# search by photo
.venv\Scripts\python.exe -m gmagc_desktop.cli search photo.jpg --index .gmagc-cache\index.npz --library D:\path\to\gobos --top 10
```

Example search output: ` 1.  87.3%  vendor/ell.png  (+1 copies)`. Exit codes: `0` success; `1` no index, it is empty or does not fit the model; `2` no projection found in the photo; `3` an input file could not be read (photo, model, library folder).

## Measurements

On 17 real photos (11 labeled; for 6 the needed gobo is not in the library): the right answer is in the top five for **91%** (10 of 11), and first for 64%. Search takes ~80 ms; indexing 11 thousand files takes about a minute. The sample is small (one wall, one camera), so the figures show the order of magnitude.

## Desktop app

At start a splash with the logo is shown for a moment while the settings and the index load. The look is always dark. On the left is a sidebar with navigation across four screens: “Gobo search”, “Phone”, “Library” and “Settings” (at the bottom of the sidebar: the app status, the author and the version). The search screen header shows metrics: the number of gobos in the database, the time of the last search and the best match score. At the bottom of the window is a status bar (index built / not built, the device, the Python and Flet versions).

1. “Choose folder…”: the gobo library folder. The index is built in the background (with progress and cancel) and saved; “Update the index” (or **F5**) appends only new files. If the library changed after the index was built (new, changed or deleted files), a reminder to update it appears under the status. The previous index file is kept next to the new one as `index.npz.previous` before it is overwritten: if the new file is lost or damaged, the next start picks up the backup instead of a long rebuild from scratch.
2. “Choose a photo…” or “Paste from clipboard” (**Ctrl+V**; a picture or a file copied in Explorer): the source photo, the found projection and the best matches are shown. Under the photo and under the projection there are three sliders each (brightness, contrast, exposure): the first ones adjust the source photo before the projection itself is found in the frame, the second ones adjust the already found projection before it is compared with the library. This helps when the photo is blurred or overexposed. They reset to neutral values with every new photo, each group with its own “Reset” button.
3. **A click on a result card copies the absolute path of the file, with the file name, to the clipboard** (`C:\...\file.png` on Windows, `/Users/.../file.png` on macOS); the folder icon on the card opens the file manager with the file selected. If the score of the first result is below 72%, the app warns that the match is unreliable. If no projection is found in the photo, it suggests shooting closer and darkening the background.
4. If a result is wrong, the thumbs-down icon on the card (“This is wrong”) lets you point to the correct file in the library. For the next similar queries the correct file is placed first (with a high score), and the earlier wrong result stays below in the list, it does not disappear. This is not retraining of the model (the ready-made DINOv2 network was tested on this data and turned out worse, see above), just a simple layer over “wrong → correct” pairs, stored next to the index and reset when the library changes. It also works for results that came from a phone.

The “Settings” screen brings together “Large text”, autostart, “Number of search results” (10, 20, 50 or 100; 50 by default; on a real library 100 results take about half a second; this does not affect the phone), “grandMA3 fixture types folder” and “…grandMA2 (importexport)” (where the PC puts profiles sent from a phone; empty means the app finds the installed consoles itself), the language selector, “Export settings” / “Import settings” (a `.json` file, handy when reinstalling or moving to another PC; the server and the access code from an imported file apply after a restart), the core check, the update check, the author support links and “Send the log by email”. The last item opens an email to the author with the version, the OS and the index status and shows the log file (`gmagc.log`, rotation 1 MB) in Explorer/Finder; you attach it to the email manually, the app itself does not send mail.

## Phone server

The server starts **together with the app** (the “Phone server” switch on the “Phone” screen turns it off and remembers the choice). The “Phone” screen shows the PC address, a QR code and a **permanent access code** of 8 characters (the “Copy code” and “New code” buttons). The PC and the phone must be on the same Wi-Fi network; on the first start Windows asks for permission in the firewall, and it must be given for private networks. Port 8765; if it is busy, the next one is taken (it is visible in the window and in the QR). Requests from the phone are shown in the main window at once and go to the “Phone requests” list (the last 10; a click opens the result).

“Start when the computer turns on” (Windows and macOS) adds GMAGC to the current user's startup (the `HKCU\...\Run` registry key on Windows, a LaunchAgent on macOS), without administrator rights and without minimizing to the tray: the window opens as usual.

The protocol (HTTP, local network only, no cloud); the shared code is in `packages/common/gmagc_common`:
- `GET /api/health`: the API version, whether there is an index (no code needed);
- `GET /api/status`: files, families, whether indexing is running;
- `POST /api/match[?top=N]`: the request body is a JPEG/PNG (up to 10 MB); the reply is the outcome, time, results (name, full path on the PC, score, copies, a base64 preview) and the found projection;
- `POST /api/fixtures`: the request body is the JSON of a fixture profile (up to 1 MB); the PC itself writes the grandMA3 type (`manufacturer@model.xml`) and the grandMA2 types (one file per mode) into the console folders; the reply says what was written and what was skipped (skips are codes, the phone chooses the text in its own language). Errors: `bad_profile` (this is not a profile or it is not ready for export) and `no_target` (neither a found nor a specified console folder).

All methods except `health` require `Authorization: Bearer <code>`; after 5 wrong codes from one address the server answers 429 for 30 seconds. Errors come as JSON (`{"error": "unauthorized", "message": "..."}`).

You can check without a phone with a script that does what the phone would do (shrinks the photo to 1280 px and sends it):

```powershell
.venv\Scripts\python.exe scripts\phone_sim.py --host 192.168.1.5 --port 8765 --code ABCD-2345 photo.jpg
# or from a QR link: --link "gmagc://connect?host=192.168.1.5&port=8765&code=ABCD2345"
```

Exit codes: `0` success, `1` the server answered with an error, `2` no connection, `3` wrong arguments or an unreadable photo.

The settings and the index cache are in `%LOCALAPPDATA%\@ANDY_BUM\GMAGC\` (macOS `~/Library/Application Support/GMAGC`, otherwise `~/.local/share/gmagc`); the path can be overridden with the `GMAGC_DATA_DIR` variable. Dragging files from the OS is not supported in Flet 1.0.0, so photos are chosen with buttons.

## Android app

Install `GMAGC-android-<version>.apk` (allow installation from unknown sources) and keep the phone on the **same Wi-Fi network** as the PC running GMAGC (the “Phone” block in the PC window shows the address, the QR and the code). The look is always dark, regardless of the system theme.

1. **Connection.** At the top are the logo and the name, below them the address and code fields at full width, the “Connect” button and the “Scan the QR code from the PC” button (point the camera at the QR code in the PC window: it is read and connects automatically, without pressing a button; zoom and tapping the frame to focus help). If automatic scanning does not work, a “Scan QR” button appears instead (a manual shot). The connection is remembered and restored at start. At the bottom of the screen the “Settings” / “Help” / “About” navigation is fixed in place; the “Fixture profiles” button sits under the scan button.
2. **Camera** (full screen, the viewfinder corners are marked with colored brackets; all controls float over the frame). Top left: the “Gallery” / “Fixture profiles” / “Settings” / “About” navigation; top right: a Wi-Fi icon (green is connected, red is not) instead of a title. Zoom: a vertical slider and magnifier buttons on the right, or a two-finger pinch. Focus: the icon at the bottom left (tapping the frame also sets focus and exposure metering, a yellow marker). The round “Take a photo” button at the bottom center sends the frame to the PC, “Choose a photo” at the bottom right picks one from the device gallery (large files are compressed to 8 MB). The “Back” button from the camera returns straight to the connection screen.
3. **Results.** Preview, name, path on the PC, score, “N more files”. **A click on a card or “Copy path” puts the absolute path of the file, with its name, on the clipboard.** “Shoot again” returns to the camera.
4. **Gallery** is the history of this session's photos (the last 10); a click on an entry shows the same result again without sending the photo to the PC once more.
5. **Settings** are the language, the update check and “Change PC” (forgets the current connection).
6. **About** shows the version, the author and the support links.

Errors are shown in plain text (no connection, wrong code, the index on the PC is not built, too many wrong codes); on a network failure the “Retry” button sends the same shot again without shooting anew. At the bottom of the connection screen a “Last error” line stays for diagnostics. On a PC (`flet run apps/mobile/src/main.py`) a placeholder is shown instead of the camera; connecting and “Choose a photo” work (for debugging: `GMAGC_MOBILE_DEMO_LINK` connects using a QR link, `GMAGC_MOBILE_DEMO_PHOTO` searches for a file at once).

The “Profiles” window creates fixture profiles for grandMA2 and grandMA3 from scratch: manufacturer, name, modes, channels (from templates: dimmer, Pan/Tilt, color, gobo, prism and others; 8 or 16 bit; the DMX address is filled in automatically), and value ranges with names. The check shows overlapping addresses and gaps in ranges; all edits are saved at once. The “Share” buttons hand over **ready files** through the system menu (to a messenger, mail, or a computer): the profile JSON, the fixture type XML for grandMA3 (put it into `C:\ProgramData\MALightingTechnology\gma3_library\fixturetypes` and import it in MA3) and one XML per mode for grandMA2 (into MA2's `importexport`; in MA2 one file describes one mode). The scripts `scripts/export_ma3.py` and `scripts/export_ma2.py` do the same from the profile JSON. The “Iris”, “Frost”, CTO, “Control” and “Custom channel” channels are exported empty for MA2 for now, and wheel slots are not created. The “Send to PC” button sends the profile over Wi-Fi (the phone must be connected to the PC): the PC itself puts the types for grandMA3 and grandMA2 into the console folders (found automatically or set in the PC app settings) and tells the phone which files were written (see `docs/superpowers/specs/2026-09-24-gmagc-fixture-editor-design.md`).

## Updates

The apps learn about a new version on GitHub Releases by themselves: a few seconds after start, no more than once a day, plus a “Check for updates” button (in the PC “Settings” screen and the Android “Settings” screen). The check can be turned off with the “Check for updates on start” switch. If there is no network or no reply from GitHub, nothing happens quietly and the app stays fully offline.

- **PC (Windows, macOS):** when a new version exists, a bar “Version X is available (you have Y)” appears at the top of the window with the buttons “Update”, “What's new” (the release page) and “Skip”. “Update” downloads the archive, **checks its SHA-256 against the `.sha256` file from the same release** (without a sum or on a mismatch the file is not installed), unpacks it into a temporary folder and closes the app; a small script replaces the files, the previous version stays next to it in `<app folder>.previous`, and the new version starts. The settings and the index are stored outside the app folder and are not touched. If the folder is not writable or something does not match, the reason and a link to the release page are shown.
- **Android:** a bar “Version X is available” with a “Download” button opens the APK in the browser, then the usual Android installation follows (the system does not allow installing an APK silently). The update installs over the old one because all APKs are signed with one permanent key (see below); versions before 0.5.2 were signed with temporary keys, so they must be removed once and installed again.
- HTTPS only and `github.com` / `*.githubusercontent.com` addresses (every redirect is checked). The builds are not signed and the sum is in the same release: it protects against a damaged download but not against a hacked GitHub account, so installation happens only on a button press.
- For debugging, `GMAGC_UPDATE_URL=http://127.0.0.1:<port>/latest` replaces GitHub (only a local address is accepted).

## Support the author

The program is free. A window asking for support is shown on the 5th launch and then no more than once every 30 days (the buttons “Support”, “Later”, “Do not show again”); the links “Support the author” ([donate](https://boosty.to/djmaker/donate)), “Author's Telegram” ([@Andy_bum](https://t.me/Andy_bum)) and “GMAGC channel” ([@gmagclight](https://t.me/gmagclight)) are always available: in the top menu on a PC and on the “About” screen on Android.

## Builds (Windows, macOS, Android)

The builds are made by GitHub Actions: on a `v*` tag (for example `v0.2.0`) the release gets `GMAGC-desktop-windows-<version>.zip`, `GMAGC-Setup-<version>.exe` (the same thing as an installer: it installs into `%LocalAppData%\Programs\GMAGC` without administrator rights, adds a shortcut and an entry in “Apps & features”; built with [Inno Setup](https://jrsoftware.org/isinfo.php) from `packaging/windows/gmagc.iss`), `GMAGC-desktop-macos-<version>.zip`, `GMAGC-android-<version>.apk` and the `.sha256` files. The same builds can be started manually (Actions → the workflow → Run workflow, the artifacts are in the run); they do not run on Pull Requests so as not to load the already limited pool of macOS runners in parallel with the tests. Auto-update always uses the zip: the `.exe` has to be installed manually only once.

The desktop app searches by photo and accepts shots from the phone, the Android app shoots and sends them (see above and below). The apps are not signed:
- macOS: right-click the app → “Open”;
- Windows: SmartScreen → “More info” → “Run anyway”;
- Android: allow installation from unknown sources.

**Android signing.** The APK is signed with a permanent key (otherwise the phone does not let a new version be installed over the old one): the key and the password are kept outside the repository by the author (`GMAGC-keys`) and in the GitHub secrets `ANDROID_KEYSTORE_B64` and `ANDROID_KEYSTORE_PASSWORD`; the workflow checks the signature fingerprint (`apksigner verify`). **Losing the key means the already installed apps cannot be updated**, so a copy of the key must be kept in a safe place. Builds from forks without the secrets are signed with a temporary debug key.

The APK is built only for **arm64-v8a** (`target_arch`, about 58 MB; all modern phones; for 32-bit ARM and x86_64 emulators build your own APK: `flet build apk apps/mobile --arch armeabi-v7a`).

The Android build settings are in `apps/mobile/pyproject.toml`: `permissions = ["camera"]` (the camera permission in the manifest) and `[tool.flet.android.manifest_application] usesCleartextTraffic = "true"` (HTTP over the local network). Reading QR codes needs the `pyzbar` and `Pillow` wheels (available on pypi.flet.dev); the QR reading tests in CI install the zbar library.

The Flet version is written in four places and changes together: `FLET_VERSION` in the three `build-*.yml`, `dependencies` in `apps/*/pyproject.toml` and `requirements-dev.txt`. The app version (`VERSION` in the `about.py` of both apps, `version` in their `pyproject.toml`) changes together with the tag.

## Local development (Windows)

Once: Python 3.12 (`winget install Python.Python.3.12`), Visual Studio 2022 with “Desktop development with C++”, Windows developer mode. The build environment: `py -3.12 -m venv $env:USERPROFILE\.venv312`, then `$env:USERPROFILE\.venv312\Scripts\python.exe -m pip install flet==1.0.0 -r requirements-dev.txt` (Flet downloads Flutter itself).

| What | Command | Time |
|---|---|---|
| Tests and linter | `.venv\Scripts\python.exe -m pytest -q`, `... -m ruff check .` | seconds |
| The screen without packaging (hot reload) | `$env:USERPROFILE\.venv312\Scripts\flet.exe run apps/desktop/src/main.py -d` | seconds |
| Windows build + launch check | `.\scripts\build_windows.ps1` | a few minutes |
| Final Windows, macOS, Android builds | a `v*` tag → GitHub Actions | ~10 minutes |

Logs of the built app: `%LOCALAPPDATA%\@ANDY_BUM\GMAGC\console.log`. macOS cannot be built locally on Windows, only through GitHub.

The app icon is in `apps/*/src/assets/icon.png` (Flet makes the Windows, macOS and Android icons from it itself); the source drawing: `docs/branding/icon.png`, the backing background is set by `icon_background` in `pyproject.toml`.

## Development

```powershell
.venv\Scripts\python.exe -m pytest -q          # about a thousand tests, synthetic data only
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe scripts\benchmark.py --library D:\path\to\gobos --samples 150
.venv\Scripts\python.exe scripts\report_photos.py --library D:\path\to\gobos --top 10   # an HTML report for labeling photos
```

The `gobos/` (library), `photo/` (real photos) and `models/` (downloaded models, `scripts/fetch_model.py`) folders are **not part** of the repository.

### Languages (i18n)

The interface texts are written in Russian in the code and wrapped in `t("…")` (`gmagc_common/i18n.py`); the Russian text is the key. English translations are dictionaries “Russian → English” in `lang_en.py` (`packages/common/gmagc_common`, `apps/desktop/src/gmagc_desktop`, `apps/mobile/src/gmagc_mobile`). An untranslated text stays in Russian. The test `tests/test_i18n_catalogs.py` requires an English translation for every `t("…")` call, forbids leftover entries and checks that the `{placeholders}` match. Word forms use `plural(n, ru=(…), en=(…))`. A language change rebuilds the interface on the same services (`DesktopApp.rebuild()`, `MobileApp.rebuild()`), so texts must not be computed once at import time: module-level constants with texts are functions.

```
apps/desktop/src/gmagc_desktop/   the core: matcher/ (image, embeddings, search), library/ (walk, index, cache, duplicates), cli.py
                                  service/ (settings, search service, access code), server/ (HTTP server, QR, addresses), ui/ (the Flet screen)
apps/desktop/src/gmagc_common/    a copy of the shared package (the original is in packages/common/gmagc_common; after edits: python scripts/sync_common.py)
packages/common/gmagc_common/     the phone ↔ PC protocol, fixture profiles and console exports, i18n (standard library only)
apps/desktop/src/main.py          the Flet desktop app
apps/mobile/src/gmagc_mobile/     the Flet Android app: client (network), camera (zoom, focus), qr, store, imaging, texts, profiles_ui, app (the screen)
apps/mobile/src/gmagc_common/     a copy of the shared package (the original is in packages/common; after edits: python scripts/sync_common.py)
.github/workflows/                tests and Windows / macOS / Android builds
scripts/                          benchmark, photo report, duplicate-group viewer, model download, window capture (capture_window.ps1), phone simulator (phone_sim.py), export to consoles (export_ma3.py, export_ma2.py), protocol sync (sync_common.py)
tests/                            tests (a synthetic library in tests/fixtures.py)
docs/                             specifications, implementation plans, measurements
```

## What is next

Wheel slots with gobos from the GMAGC library in the console exports, more MA2 attributes (iris, frost, CTO), the app icon, build signing, checks on different phones. The known postponed improvements are listed at the end of the plan `docs/superpowers/plans/2026-09-19-gmagc-core-matcher.md`.

## License

License: [MIT](LICENSE). The gobo library belongs to its manufacturers and is not part of the repository.
