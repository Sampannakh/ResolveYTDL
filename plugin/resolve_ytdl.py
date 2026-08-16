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
MAX_UI_FORMAT_BUTTONS = 80
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
    if os.environ.get("RESOLVEYTDL_NO_UPDATE"):
        logger("Auto-update skipped: disabled for this session (RESOLVEYTDL_NO_UPDATE is set).")
        return False
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


def ensure_managed_ytdlp() -> Path:
    """Create the managed virtual environment and install/upgrade yt-dlp in it."""
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


def get_ytdlp() -> Path:
    """Resolve a yt-dlp executable, preferring a system install."""
    return resolve_ytdlp() or ensure_managed_ytdlp()


def run_with_ytdlp(action, logger=print):
    """Call action(ytdlp_path), retrying once against a freshly upgraded
    managed yt-dlp if the first attempt fails (e.g. a stale system install
    that no longer works against the site)."""
    ytdlp = get_ytdlp()
    try:
        return action(ytdlp), ytdlp
    except RuntimeError as exc:
        if ytdlp == venv_executable("yt-dlp"):
            raise
        logger(f"{ytdlp} failed ({exc}); retrying with a freshly updated managed yt-dlp.")
        ytdlp = ensure_managed_ytdlp()
        return action(ytdlp), ytdlp


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


def selectable_formats(info: dict[str, Any]) -> list[tuple[str, str]]:
    choices = [(DEFAULT_FORMAT, "Best available (video + audio)")]
    seen = {DEFAULT_FORMAT}
    for fmt in info.get("formats") or []:
        selector = str(fmt.get("format_id") or "").strip()
        if not selector or selector in seen:
            continue
        label = format_summary(fmt)
        choices.append((selector, label))
        seen.add(selector)
    return choices


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
    parser.add_argument("--no-update", action="store_true", help="Skip the self-update check for this run")
    args = parser.parse_args(argv[1:])
    if not args.url:
        parser.print_usage()
        return 2
    if args.no_update:
        os.environ["RESOLVEYTDL_NO_UPDATE"] = "1"
    auto_update_script()
    if args.list_formats:
        (info, lines), ytdlp = run_with_ytdlp(lambda ytdlp: list_formats(args.url, ytdlp))
        print(f"Using yt-dlp: {ytdlp}")
        print(f"Title: {info.get('title', 'unknown')}")
        print(f"Uploader: {info.get('uploader') or info.get('channel') or 'unknown'}")
        print("Available formats:")
        print("\n".join(lines))
        return 0
    destination = args.destination.expanduser()
    downloaded, ytdlp = run_with_ytdlp(lambda ytdlp: download(args.url, destination, ytdlp, args.format))
    print(f"Using yt-dlp: {ytdlp}")
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
                    ui.Label({"ID": "title", "Text": "Title: not loaded"}),
                    ui.Label({"ID": "message", "Text": "Status: idle"}),
                    ui.Label({"Text": "Destination folder"}),
                    ui.LineEdit({"ID": "destination", "Text": default_dest}),
                    ui.HGroup({"Spacing": 8}, [ui.Button({"ID": "formats", "Text": "Load All Formats"}), ui.Button({"ID": "close", "Text": "Close"})]),
                    ui.Label({"Text": "Formats (click one to download and import)"}),
                    ui.VGroup(
                        {"ID": "format_buttons", "Spacing": 4},
                        [ui.Button({"ID": f"format_{index}", "Text": "", "Visible": False}) for index in range(MAX_UI_FORMAT_BUTTONS)],
                    ),
                    ui.TextEdit({"ID": "log", "ReadOnly": True}),
                ],
            )
        ],
    )
    items = window.GetItems()
    format_choices: list[tuple[str, str]] = []

    def log(message: str) -> None:
        items["log"].PlainText = (items["log"].PlainText + message + "\n")[-20000:]
        items["message"].Text = f"Status: {message[:140]}"

    def current_url() -> str:
        return items["url"].Text.strip()

    def show_format_buttons(choices: list[tuple[str, str]]) -> None:
        for index in range(MAX_UI_FORMAT_BUTTONS):
            button = items[f"format_{index}"]
            if index < len(choices):
                selector, label = choices[index]
                button.Text = f"Download {selector}: {label}"[:220]
                button.Visible = True
            else:
                button.Text = ""
                button.Visible = False

    def load_formats_worker() -> None:
        try:
            url = current_url()
            if not url:
                log("Enter a URL before loading formats.")
                return
            (info, lines), ytdlp = run_with_ytdlp(lambda ytdlp: list_formats(url, ytdlp), log)
            log(f"Using yt-dlp: {ytdlp}")
            items["title"].Text = f"Title: {info.get('title', 'unknown')}"
            uploader = info.get("uploader") or info.get("channel") or "unknown"
            log(f"Uploader/channel: {uploader}")
            format_choices[:] = selectable_formats(info)[:MAX_UI_FORMAT_BUTTONS]
            show_format_buttons(format_choices)
            log("Available formats loaded as download buttons:")
            for selector, label in format_choices:
                log(f"{selector}: {label}")
            if len(selectable_formats(info)) > MAX_UI_FORMAT_BUTTONS:
                log(f"Showing the first {MAX_UI_FORMAT_BUTTONS} formats only.")
            if not format_choices:
                log("No downloadable formats were found.")
            else:
                log("Click a format button to download and import it.")
            if lines:
                log("Raw yt-dlp format list:")
                for line in lines:
                    log(line)
        except Exception as exc:  # Resolve UI callbacks need visible error reporting.
            log(f"Error loading formats: {exc}")

    def download_worker(selector: str) -> None:
        try:
            url = current_url()
            if not url:
                log("Enter a URL before downloading.")
                return
            log(f"Selected format: {selector}")
            destination = Path(items["destination"].Text).expanduser()
            downloaded, ytdlp = run_with_ytdlp(
                lambda ytdlp: download(url, destination, ytdlp, selector, log), log
            )
            log(f"Using yt-dlp: {ytdlp}")
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
    for index in range(MAX_UI_FORMAT_BUTTONS):
        def make_handler(button_index: int):
            def handler(ev):
                if button_index >= len(format_choices):
                    log("Load formats before choosing a download button.")
                    return
                selector = format_choices[button_index][0]
                threading.Thread(target=download_worker, args=(selector,), daemon=True).start()

            return handler

        getattr(window.On, f"format_{index}").Clicked = make_handler(index)
    window.Show()
    dispatcher.RunLoop()
    window.Hide()


if __name__ == "__main__":
    if "fusion" in globals() and "bmd" in globals() and len(sys.argv) == 1:
        run_resolve_ui()
    else:
        raise SystemExit(run_cli(sys.argv))
