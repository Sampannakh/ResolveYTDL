# ResolveYTDL

ResolveYTDL is a DaVinci Resolve utility script that downloads YouTube-compatible URLs through a `yt-dlp` backend and imports the result into the current Resolve media pool.

## What it does

- Uses an existing system `yt-dlp` executable when one is available on `PATH`.
- Falls back to a project-managed Python virtual environment if no system install is found.
- Can bootstrap that virtual environment automatically from inside Resolve.
- Supports Windows, macOS, and Linux Resolve script locations.
- Keeps Python packages isolated in a virtual environment instead of installing them globally.

## Install

Run the cross-platform installer from the repository root:

```bash
python installer.py
```

The installer copies `resolve_ytdl.py` into Resolve's Utility scripts folder. If `yt-dlp` is already installed system-wide, the installer uses that backend and skips managed package installation; otherwise it creates a virtual environment under the user's ResolveYTDL data directory and installs `yt-dlp` there.

Useful options:

```bash
python installer.py --skip-venv     # copy the plugin only
python installer.py --upgrade-ytdlp # upgrade yt-dlp in the managed environment
python installer.py --target /path/to/Utility # install to a custom Resolve script folder
```

## Usage in Resolve

1. Open DaVinci Resolve.
2. Go to **Workspace > Scripts > Utility > ResolveYTDL**.
3. Paste a YouTube URL or another URL supported by `yt-dlp`.
4. Click **Load All Formats** to show the title, uploader/channel, and every `yt-dlp` format option reported for the URL.
5. Paste a format id or any `yt-dlp` format expression into the format selector.
6. Choose a destination folder.
7. Click **Download and Import**.

The downloaded file is imported into the current media pool when Resolve's scripting API is available.

## Backend resolution order

At runtime, the plugin resolves `yt-dlp` in this order:

1. A system `yt-dlp` executable found via `PATH`.
2. The executable in the managed virtual environment.
3. A newly bootstrapped managed virtual environment, if Python and pip are available.


## Format selection and configuration

ResolveYTDL does not create or pass a custom `yt-dlp` config file. Downloads and metadata probes use `yt-dlp`'s normal system/user configuration discovery, so existing config files, authentication settings, proxy settings, and defaults continue to apply.

The default format selector is `bestvideo+bestaudio/best`. Use **Load All Formats** in Resolve, or run:

```bash
python plugin/resolve_ytdl.py --list-formats URL
```

Then pass any listed format id or expression with:

```bash
python plugin/resolve_ytdl.py -f FORMAT URL /path/to/downloads
```

The plugin logs backend selection, titles, uploader/channel names, selected format expressions, download progress, Resolve import status, and detailed errors in the Resolve window.
