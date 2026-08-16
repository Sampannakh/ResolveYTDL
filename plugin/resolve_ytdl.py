#!/usr/bin/env python3
"""DaVinci Resolve utility script for downloading videos with yt-dlp."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import threading
import venv
from pathlib import Path
from typing import Optional, Sequence

APP_NAME = "ResolveYTDL"
SCRIPT_TITLE = "ResolveYTDL"


def data_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif system == "Darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / APP_NAME


def venv_dir() -> Path:
    return data_dir() / ".venv"


def venv_executable(name: str) -> Path:
    if platform.system() == "Windows":
        return venv_dir() / "Scripts" / f"{name}.exe"
    return venv_dir() / "bin" / name


def resolve_ytdlp() -> Optional[Path]:
    system = shutil.which("yt-dlp")
    if system:
        return Path(system)
    local = venv_executable("yt-dlp")
    if local.exists():
        return local
    return None


def ensure_environment() -> Path:
    """Create the managed virtual environment and install yt-dlp if needed."""
    existing = resolve_ytdlp()
    if existing and "ResolveYTDL" not in str(existing):
        return existing

    env = venv_dir()
    env.mkdir(parents=True, exist_ok=True)
    if not venv_executable("python").exists():
        venv.EnvBuilder(with_pip=True, clear=False).create(env)

    python = venv_executable("python")
    subprocess.check_call([str(python), "-m", "pip", "install", "--upgrade", "pip", "yt-dlp"])
    ytdlp = venv_executable("yt-dlp")
    if not ytdlp.exists():
        raise RuntimeError("yt-dlp was installed, but its executable could not be found")
    return ytdlp


def download(url: str, destination: Path, ytdlp: Path, logger=print) -> Optional[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    before = set(destination.glob("*"))
    template = str(destination / "%(title).200B [%(id)s].%(ext)s")
    command = [str(ytdlp), "--no-playlist", "--restrict-filenames", "-o", template, url]
    logger("Running: " + " ".join(command))
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert process.stdout is not None
    for line in process.stdout:
        logger(line.rstrip())
    if process.wait() != 0:
        raise RuntimeError(f"yt-dlp exited with status {process.returncode}")
    created = [p for p in destination.glob("*") if p not in before and p.is_file()]
    return max(created, key=lambda p: p.stat().st_mtime) if created else None


def import_into_resolve(path: Path, logger=print) -> None:
    try:
        resolve = bmd.scriptapp("Resolve")  # type: ignore[name-defined]
    except Exception:
        logger("Resolve scripting API is unavailable; download completed without import.")
        return
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        logger("No active Resolve project; download completed without import.")
        return
    media_pool = project.GetMediaPool()
    media_pool.ImportMedia([str(path)])
    logger(f"Imported: {path}")


def run_cli(argv: Sequence[str]) -> int:
    if len(argv) < 2:
        print("Usage: resolve_ytdl.py URL [DESTINATION]")
        return 2
    url = argv[1]
    destination = Path(argv[2]).expanduser() if len(argv) > 2 else data_dir() / "downloads"
    ytdlp = resolve_ytdlp() or ensure_environment()
    downloaded = download(url, destination, ytdlp)
    if downloaded:
        print(f"Downloaded: {downloaded}")
    return 0


def run_resolve_ui() -> None:
    ui = fusion.UIManager  # type: ignore[name-defined]
    dispatcher = bmd.UIDispatcher(ui)  # type: ignore[name-defined]
    default_dest = str(data_dir() / "downloads")
    window = dispatcher.AddWindow(
        {"WindowTitle": SCRIPT_TITLE, "ID": "ResolveYTDL", "Geometry": [100, 100, 720, 420]},
        [
            ui.VGroup(
                {"Spacing": 8},
                [
                    ui.Label({"Text": "URL"}),
                    ui.LineEdit({"ID": "url", "PlaceholderText": "https://www.youtube.com/watch?v=..."}),
                    ui.Label({"Text": "Destination folder"}),
                    ui.LineEdit({"ID": "destination", "Text": default_dest}),
                    ui.HGroup({"Spacing": 8}, [ui.Button({"ID": "download", "Text": "Download and Import"}), ui.Button({"ID": "close", "Text": "Close"})]),
                    ui.TextEdit({"ID": "log", "ReadOnly": True}),
                ],
            )
        ],
    )
    items = window.GetItems()

    def log(message: str) -> None:
        items["log"].PlainText = (items["log"].PlainText + message + "\n")[-12000:]

    def worker() -> None:
        try:
            url = items["url"].Text.strip()
            if not url:
                log("Enter a URL first.")
                return
            ytdlp = resolve_ytdlp() or ensure_environment()
            log(f"Using yt-dlp: {ytdlp}")
            downloaded = download(url, Path(items["destination"].Text).expanduser(), ytdlp, log)
            if downloaded:
                import_into_resolve(downloaded, log)
                log(f"Done: {downloaded}")
        except Exception as exc:  # Resolve UI callbacks need visible error reporting.
            log(f"Error: {exc}")

    window.On.ResolveYTDL.Close = lambda ev: dispatcher.ExitLoop()
    window.On.close.Clicked = lambda ev: dispatcher.ExitLoop()
    window.On.download.Clicked = lambda ev: threading.Thread(target=worker, daemon=True).start()
    window.Show()
    dispatcher.RunLoop()
    window.Hide()


if __name__ == "__main__":
    if "fusion" in globals() and "bmd" in globals() and len(sys.argv) == 1:
        run_resolve_ui()
    else:
        raise SystemExit(run_cli(sys.argv))
