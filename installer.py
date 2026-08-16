#!/usr/bin/env python3
"""Cross-platform installer for the ResolveYTDL DaVinci Resolve utility script."""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import venv
from pathlib import Path

APP_NAME = "ResolveYTDL"
PLUGIN_SOURCE = Path(__file__).resolve().parent / "plugin" / "resolve_ytdl.py"
SCRIPT_DESTINATION_NAME = "ResolveYTDL.py"
LEGACY_SCRIPT_NAMES = ("ResolveYTDL.py", "resolve_ytdl.py", "Resolve YTDL.py", "YouTubeDL.py", "YTDL.py")


def resolve_script_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        return program_data / "Blackmagic Design" / "DaVinci Resolve" / "Fusion" / "Scripts" / "Utility"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Blackmagic Design" / "DaVinci Resolve" / "Fusion" / "Scripts" / "Utility"
    return Path.home() / ".local" / "share" / "DaVinciResolve" / "Fusion" / "Scripts" / "Utility"


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


def venv_python() -> Path:
    if platform.system() == "Windows":
        return venv_dir() / "Scripts" / "python.exe"
    return venv_dir() / "bin" / "python"


def install_environment(upgrade_ytdlp: bool) -> None:
    if shutil.which("yt-dlp") and not upgrade_ytdlp:
        print("Found system yt-dlp; skipping managed yt-dlp install and using the system backend.")
        return
    env = venv_dir()
    env.mkdir(parents=True, exist_ok=True)
    if not venv_python().exists():
        print(f"Creating virtual environment: {env}")
        venv.EnvBuilder(with_pip=True, clear=False).create(env)
    command = [str(venv_python()), "-m", "pip", "install", "--upgrade", "pip", "yt-dlp"]
    if upgrade_ytdlp:
        command.append("--upgrade")
    print("Installing managed yt-dlp environment")
    subprocess.check_call(command)


def install_plugin(target: Path) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    destination = target / SCRIPT_DESTINATION_NAME
    for legacy_name in LEGACY_SCRIPT_NAMES:
        legacy_path = target / legacy_name
        if legacy_path == destination:
            continue
        if legacy_path.exists():
            legacy_path.unlink()
            print(f"Removed old ResolveYTDL script: {legacy_path}")
    shutil.copy2(PLUGIN_SOURCE, destination)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="Install ResolveYTDL for DaVinci Resolve")
    parser.add_argument("--target", type=Path, default=resolve_script_dir(), help="Resolve Utility scripts directory")
    parser.add_argument("--skip-venv", action="store_true", help="Only copy the Resolve script")
    parser.add_argument("--upgrade-ytdlp", action="store_true", help="Upgrade yt-dlp in the managed virtual environment")
    args = parser.parse_args()

    if not PLUGIN_SOURCE.exists():
        raise FileNotFoundError(f"Missing plugin source: {PLUGIN_SOURCE}")

    installed = install_plugin(args.target.expanduser())
    print(f"Installed Resolve script: {installed}")
    if not args.skip_venv:
        install_environment(args.upgrade_ytdlp)
        print(f"Managed environment: {venv_dir()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
