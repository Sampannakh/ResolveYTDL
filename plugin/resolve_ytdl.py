#!/usr/bin/env python3
"""DaVinci Resolve utility script for downloading videos with yt-dlp."""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import tempfile
import urllib.request
import sys
import threading
import venv
from pathlib import Path
from typing import Any, Optional, Sequence

APP_NAME = "ResolveYTDL"
SCRIPT_TITLE = "ResolveYTDL"
DEFAULT_FORMAT = "bestvideo+bestaudio/best"
DEFAULT_UPDATE_URL = "https://raw.githubusercontent.com/Sampannakh/ResolveYTDL/main/plugin/resolve_ytdl.py"
UPDATE_TIMEOUT_SECONDS = 5


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


def update_url() -> str:
    return os.environ.get("RESOLVEYTDL_UPDATE_URL", DEFAULT_UPDATE_URL)


def internet_available(timeout: int = UPDATE_TIMEOUT_SECONDS) -> bool:
    try:
        request = urllib.request.Request("https://www.google.com/generate_204", method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 400
    except Exception:
        return False


def auto_update_script(logger=print) -> bool:
    """Replace this script with the latest published copy when internet is available."""
    source = update_url()
    current = Path(__file__).resolve()
    if not source:
        logger("Auto-update skipped: no update URL configured.")
        return False
    if not internet_available():
        logger("Auto-update skipped: no internet connection detected.")
        return False
    try:
        logger(f"Checking for ResolveYTDL script update: {source}")
        request = urllib.request.Request(source, headers={"User-Agent": f"{APP_NAME}/self-update"})
        with urllib.request.urlopen(request, timeout=UPDATE_TIMEOUT_SECONDS) as response:
            latest = response.read()
        current_bytes = current.read_bytes()
        if latest == current_bytes:
            logger("ResolveYTDL script is up to date.")
            return False
        text = latest.decode("utf-8")
        if "APP_NAME = \"ResolveYTDL\"" not in text or "def run_resolve_ui" not in text:
            logger("Auto-update skipped: downloaded file did not look like ResolveYTDL.")
            return False
        current_mode = current.stat().st_mode
        fd, temp_name = tempfile.mkstemp(prefix=current.name, suffix=".tmp", dir=str(current.parent))
        with os.fdopen(fd, "wb") as handle:
            handle.write(latest)
        os.chmod(temp_name, current_mode)
        os.replace(temp_name, current)
        logger("ResolveYTDL script updated. Restart the script to use the new version.")
        return True
    except Exception as exc:
        logger(f"Auto-update skipped: {exc}")
        return False


def resolve_ytdlp() -> Optional[Path]:
    """Prefer the user's system yt-dlp before the managed fallback environment."""
    system = shutil.which("yt-dlp")
    if system:
        return Path(system)
    local = venv_executable("yt-dlp")
    if local.exists():
        return local
    return None


def ensure_environment() -> Path:
    """Create the managed virtual environment and install or update yt-dlp if needed."""
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


def run_ytdlp_json(url: str, ytdlp: Path) -> dict[str, Any]:
    command = [str(ytdlp), "--dump-single-json", "--no-playlist", url]
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or f"yt-dlp exited with status {completed.returncode}"
        raise RuntimeError(message)
    return json.loads(completed.stdout)


def format_summary(fmt: dict[str, Any]) -> str:
    format_id = str(fmt.get("format_id", "?"))
    ext = fmt.get("ext") or "?"
    resolution = fmt.get("resolution") or "x".join(str(v) for v in (fmt.get("width"), fmt.get("height")) if v) or "audio-only"
    fps = f" {fmt.get('fps')}fps" if fmt.get("fps") else ""
    vcodec = fmt.get("vcodec") or "?"
    acodec = fmt.get("acodec") or "?"
    filesize = fmt.get("filesize") or fmt.get("filesize_approx")
    size_text = f" {filesize / 1024 / 1024:.1f}MiB" if isinstance(filesize, (int, float)) else ""
    note = fmt.get("format_note") or ""
    return f"{format_id:>8} | {ext:<5} | {resolution:<12}{fps:<7} | v:{vcodec:<12} a:{acodec:<12}{size_text} {note}".rstrip()


def list_formats(url: str, ytdlp: Path) -> tuple[dict[str, Any], list[str]]:
    info = run_ytdlp_json(url, ytdlp)
    command = [str(ytdlp), "--list-formats", "--no-playlist", url]
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode == 0 and completed.stdout.strip():
        lines = completed.stdout.rstrip().splitlines()
    else:
        formats = info.get("formats") or []
        lines = [format_summary(fmt) for fmt in formats]
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or f"yt-dlp exited with status {completed.returncode}"
            lines.insert(0, f"yt-dlp --list-formats failed; showing JSON formats instead: {detail}")
    if not lines:
        lines = ["No individual formats were reported; use the default selector or a yt-dlp format expression."]
    return info, lines


def download(url: str, destination: Path, ytdlp: Path, format_selector: str = DEFAULT_FORMAT, logger=print) -> Optional[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    before = set(destination.glob("*"))
    template = str(destination / "%(title).200B [%(id)s].%(ext)s")
    command = [str(ytdlp), "--newline", "--no-playlist", "--restrict-filenames", "-f", format_selector, "-o", template, url]
    logger("Using yt-dlp system/user configuration files.")
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
    imported = media_pool.ImportMedia([str(path)])
    if imported:
        logger(f"Imported into media pool: {path.name}")
    else:
        logger(f"Resolve did not report a successful import for: {path}")


def run_cli(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="Download a yt-dlp-supported URL and optionally import it in Resolve")
    parser.add_argument("url", nargs="?", help="YouTube or other yt-dlp-supported URL")
    parser.add_argument("destination", nargs="?", type=Path, default=data_dir() / "downloads", help="Download destination")
    parser.add_argument("-f", "--format", default=DEFAULT_FORMAT, help="yt-dlp format id or expression")
    parser.add_argument("--list-formats", action="store_true", help="Print all available formats and exit")
    args = parser.parse_args(argv[1:])
    if not args.url:
        parser.print_usage()
        return 2
    auto_update_script()
    ytdlp = resolve_ytdlp() or ensure_environment()
    print(f"Using yt-dlp: {ytdlp}")
    if args.list_formats:
        info, lines = list_formats(args.url, ytdlp)
        print(f"Title: {info.get('title', 'unknown')}")
        print(f"Uploader: {info.get('uploader') or info.get('channel') or 'unknown'}")
        print("Available formats:")
        print("\n".join(lines))
        return 0
    downloaded = download(args.url, args.destination.expanduser(), ytdlp, args.format)
    if downloaded:
        print(f"Downloaded: {downloaded}")
    return 0


def run_resolve_ui() -> None:
    ui = fusion.UIManager  # type: ignore[name-defined]
    dispatcher = bmd.UIDispatcher(ui)  # type: ignore[name-defined]
    default_dest = str(data_dir() / "downloads")
    window = dispatcher.AddWindow(
        {"WindowTitle": SCRIPT_TITLE, "ID": "ResolveYTDL", "Geometry": [100, 100, 820, 560]},
        [
            ui.VGroup(
                {"Spacing": 8},
                [
                    ui.Label({"Text": "URL"}),
                    ui.LineEdit({"ID": "url", "PlaceholderText": "https://www.youtube.com/watch?v=..."}),
                    ui.Label({"Text": "Format selector (load formats, then paste any format id or yt-dlp expression)"}),
                    ui.LineEdit({"ID": "format", "Text": DEFAULT_FORMAT}),
                    ui.Label({"ID": "title", "Text": "Title: not loaded"}),
                    ui.Label({"ID": "message", "Text": "Status: idle"}),
                    ui.Label({"Text": "Destination folder"}),
                    ui.LineEdit({"ID": "destination", "Text": default_dest}),
                    ui.HGroup({"Spacing": 8}, [ui.Button({"ID": "formats", "Text": "Load All Formats"}), ui.Button({"ID": "download", "Text": "Download and Import"}), ui.Button({"ID": "close", "Text": "Close"})]),
                    ui.TextEdit({"ID": "log", "ReadOnly": True}),
                ],
            )
        ],
    )
    items = window.GetItems()

    def log(message: str) -> None:
        items["log"].PlainText = (items["log"].PlainText + message + "\n")[-20000:]
        items["message"].Text = f"Status: {message[:140]}"

    def current_url() -> str:
        return items["url"].Text.strip()

    def load_formats_worker() -> None:
        try:
            url = current_url()
            if not url:
                log("Enter a URL before loading formats.")
                return
            ytdlp = resolve_ytdlp() or ensure_environment()
            log(f"Using yt-dlp: {ytdlp}")
            info, lines = list_formats(url, ytdlp)
            items["title"].Text = f"Title: {info.get('title', 'unknown')}"
            uploader = info.get("uploader") or info.get("channel") or "unknown"
            log(f"Uploader/channel: {uploader}")
            log("Available formats (copy a format id into the selector, or use any yt-dlp format expression):")
            for line in lines:
                log(line)
            log("Format list loaded.")
        except Exception as exc:  # Resolve UI callbacks need visible error reporting.
            log(f"Error loading formats: {exc}")

    def download_worker() -> None:
        try:
            url = current_url()
            if not url:
                log("Enter a URL before downloading.")
                return
            selector = items["format"].Text.strip() or DEFAULT_FORMAT
            ytdlp = resolve_ytdlp() or ensure_environment()
            log(f"Using yt-dlp: {ytdlp}")
            log(f"Selected format: {selector}")
            downloaded = download(url, Path(items["destination"].Text).expanduser(), ytdlp, selector, log)
            if downloaded:
                import_into_resolve(downloaded, log)
                log(f"Done: {downloaded}")
            else:
                log("Download finished, but no new file was detected in the destination folder.")
        except Exception as exc:  # Resolve UI callbacks need visible error reporting.
            log(f"Error downloading: {exc}")

    threading.Thread(target=auto_update_script, args=(lambda message: log(message),), daemon=True).start()

    window.On.ResolveYTDL.Close = lambda ev: dispatcher.ExitLoop()
    window.On.close.Clicked = lambda ev: dispatcher.ExitLoop()
    window.On.formats.Clicked = lambda ev: threading.Thread(target=load_formats_worker, daemon=True).start()
    window.On.download.Clicked = lambda ev: threading.Thread(target=download_worker, daemon=True).start()
    window.Show()
    dispatcher.RunLoop()
    window.Hide()


if __name__ == "__main__":
    if "fusion" in globals() and "bmd" in globals() and len(sys.argv) == 1:
        run_resolve_ui()
    else:
        raise SystemExit(run_cli(sys.argv))
