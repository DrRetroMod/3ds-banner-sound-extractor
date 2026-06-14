#!/usr/bin/env python3
"""
3DS Banner Sound Extractor v1.4.1

Extracts Nintendo 3DS banner audio from .3ds/.cci/.cxi/.cia/.app files and converts it to MP3.

Dependency policy:
- ctrtool: downloaded from 3DSGuy/Project_CTR GitHub releases, selecting CTRTool assets only.
- vgmstream-cli: downloaded from vgmstream's official nightly CLI release URLs.
- ffmpeg: uses local/PATH ffmpeg, or installs imageio-ffmpeg and uses its bundled ffmpeg binary.

Supported desktop targets:
- macOS Apple Silicon / ARM64
- macOS Intel / x86_64
- Windows 64-bit
- Linux x86_64 / ARM64 when matching upstream binaries are available

Outputs:
  Extracted Banner Sounds/<ROM name>_banner_sound.mp3
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Iterable

APP_NAME = "3DS Banner Sound Extractor"
VERSION = "1.4.1"
TOOLS_DIR_NAME = "_3ds_banner_tools"
WORK_DIR_NAME = "_3ds_banner_work"
OUTPUT_DIR_NAME = "Extracted Banner Sounds"
SUPPORTED_EXTS = {".3ds", ".cci", ".cxi", ".cia", ".app"}

PROJECT_CTR_API_RELEASES = "https://api.github.com/repos/3DSGuy/Project_CTR/releases"
VGMSTREAM_URLS = {
    "mac": "https://github.com/vgmstream/vgmstream-releases/releases/download/nightly/vgmstream-mac-cli.tar.gz",
    "linux": "https://github.com/vgmstream/vgmstream-releases/releases/download/nightly/vgmstream-linux-cli.tar.gz",
    "windows": "https://github.com/vgmstream/vgmstream-releases/releases/download/nightly/vgmstream-win64.zip",
}


class SetupError(RuntimeError):
    pass


class ExtractError(RuntimeError):
    pass


def log(msg: str, quiet: bool = False) -> None:
    if not quiet:
        print(msg)


def detect_os() -> str:
    system = platform.system().lower()
    if system == "darwin":
        return "mac"
    if system == "windows":
        return "windows"
    if system == "linux":
        return "linux"
    raise SetupError(f"Unsupported OS: {platform.system()}")


def normalized_arch() -> str:
    machine = platform.machine().lower()
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    if machine in {"x86_64", "amd64"}:
        return "x64"
    if machine in {"i386", "i686", "x86"}:
        return "x86"
    return machine


def arch_tokens() -> list[str]:
    arch = normalized_arch()
    if arch == "arm64":
        return ["arm64", "aarch64", "apple", "silicon"]
    if arch == "x64":
        return ["x64", "x86_64", "amd64", "64", "intel"]
    if arch == "x86":
        return ["x86", "i386", "i686", "32"]
    return [arch]


def platform_label() -> str:
    return f"{detect_os()}-{normalized_arch()}"


def exe_name(name: str) -> str:
    return f"{name}.exe" if detect_os() == "windows" else name


def tools_dir_for(input_path: Path) -> Path:
    base = input_path if input_path.is_dir() else input_path.parent
    return base / TOOLS_DIR_NAME


def work_dir_for(input_path: Path) -> Path:
    base = input_path if input_path.is_dir() else input_path.parent
    return base / WORK_DIR_NAME


def output_dir_for(rom_path: Path) -> Path:
    return rom_path.parent / OUTPUT_DIR_NAME


def safe_mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def make_executable(path: Path) -> None:
    if detect_os() == "windows":
        return
    try:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except PermissionError:
        # If it is already executable, this is fine. macOS sometimes refuses chmod on copied tools.
        if not os.access(path, os.X_OK):
            raise


def clear_macos_quarantine(path: Path) -> None:
    if detect_os() != "mac":
        return
    shutil.which("xattr") and subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_command(cmd: list[str | Path], check: bool = True, quiet: bool = False, capture: bool = False) -> subprocess.CompletedProcess:
    cmd_s = [str(x) for x in cmd]
    if not quiet and not capture:
        print("Running:", " ".join(cmd_s))
    return subprocess.run(
        cmd_s,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )


def tool_works(path: Path, kind: str) -> bool:
    if not path.exists():
        return False
    make_executable(path)
    clear_macos_quarantine(path)
    tests = {
        "ctrtool": [str(path), "--help"],
        "vgmstream-cli": [str(path), "-h"],
        "ffmpeg": [str(path), "-version"],
    }
    try:
        cp = subprocess.run(tests[kind], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20)
    except Exception:
        return False
    out = cp.stdout or ""
    if kind == "ctrtool":
        return "CTRTool" in out or "ctrtool" in out.lower()
    if kind == "vgmstream-cli":
        return "vgmstream" in out.lower()
    if kind == "ffmpeg":
        return "ffmpeg" in out.lower()
    return False


def curl_available() -> bool:
    return shutil.which("curl") is not None


def urlopen_bytes(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def curl_get_bytes(url: str, timeout: int = 120) -> bytes:
    curl = shutil.which("curl")
    if not curl:
        raise SetupError("curl is not available for HTTPS fallback downloads")
    cp = subprocess.run(
        [curl, "-L", "--fail", "--silent", "--show-error", "--max-time", str(timeout), url],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if cp.returncode != 0:
        err = cp.stderr.decode("utf-8", errors="replace").strip()
        raise SetupError(f"curl download failed for {url}: {err}")
    return cp.stdout


def http_get_bytes(url: str, timeout: int = 120) -> bytes:
    try:
        return urlopen_bytes(url, timeout)
    except urllib.error.URLError as exc:
        # Python.org macOS Python installs can lack a usable CA bundle, causing
        # CERTIFICATE_VERIFY_FAILED even when system curl works. Fall back to curl
        # rather than disabling TLS verification.
        if curl_available():
            return curl_get_bytes(url, timeout)
        raise exc


def download(url: str, dest: Path, quiet: bool = False) -> None:
    safe_mkdir(dest.parent)
    log(f"Downloading: {url}", quiet)
    dest.write_bytes(http_get_bytes(url, timeout=120))


def extract_archive(archive: Path, dest: Path) -> None:
    safe_mkdir(dest)
    name = archive.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
        return
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        with tarfile.open(archive, "r:gz") as t:
            t.extractall(dest)
        return
    raise SetupError(f"Unsupported archive type: {archive.name}")


def find_executable(root: Path, possible_names: Iterable[str]) -> Path | None:
    names = set(possible_names)
    for p in root.rglob("*"):
        if p.is_file() and p.name in names:
            return p
    return None


def copy_runtime_bundle(found: Path, tools_dir: Path, final_name: str, kind: str) -> Path:
    """Copy a tool plus any runtime files it needs.

    This matters on Windows especially: vgmstream-cli.exe is shipped with DLLs
    beside it. Copying only the EXE makes validation fail even though the
    download was correct.
    """
    safe_mkdir(tools_dir)
    dest = tools_dir / final_name

    if kind == "vgmstream-cli":
        # Copy the complete directory containing the CLI binary. The official
        # Windows package includes DLLs beside vgmstream-cli.exe; macOS/Linux
        # packages may include support files too. Keep the layout flat inside
        # _3ds_banner_tools for portability.
        for item in found.parent.iterdir():
            if item.is_file():
                shutil.copy2(item, tools_dir / item.name)
        if found.name != final_name:
            shutil.copy2(found, dest)
    else:
        shutil.copy2(found, dest)

    make_executable(dest)
    clear_macos_quarantine(dest)
    return dest


def install_from_archive_url(url: str, tools_dir: Path, kind: str, final_name: str, quiet: bool = False) -> Path:
    with tempfile.TemporaryDirectory(prefix="3ds_banner_tool_") as td:
        tmp = Path(td)
        archive = tmp / url.split("/")[-1].split("?")[0]
        download(url, archive, quiet)
        extracted = tmp / "extracted"
        extract_archive(archive, extracted)

        candidates = [final_name]
        if kind == "vgmstream-cli":
            candidates += ["vgmstream-cli", "vgmstream-cli.exe", "test.exe"]
        elif kind == "ctrtool":
            candidates += ["ctrtool", "ctrtool.exe"]
        elif kind == "ffmpeg":
            candidates += ["ffmpeg", "ffmpeg.exe"]

        found = find_executable(extracted, candidates)
        if not found:
            raise SetupError(f"Downloaded archive did not contain {kind}: {url}")

        dest = copy_runtime_bundle(found, tools_dir, final_name, kind)
        if not tool_works(dest, kind):
            # On Windows this usually means a required DLL is missing. Include
            # a more useful message than a generic setup failure.
            raise SetupError(
                f"Downloaded {kind}, but it did not run correctly: {dest}\n"
                f"Archive used: {url}\n"
                f"If this is vgmstream-cli on Windows, check that the DLL files from the zip are also in _3ds_banner_tools."
            )
        log(f"Installed {kind}: {dest}", quiet)
        return dest


def fetch_github_json(url: str):
    # Use urllib first; if Python's certificate store is broken, http_get_bytes
    # falls back to system curl without disabling certificate verification.
    return json.loads(http_get_bytes(url, timeout=60).decode("utf-8"))


def asset_matches_platform(asset_name: str) -> bool:
    n = asset_name.lower()
    os_key = detect_os()
    arch = normalized_arch()

    if os_key == "mac" and not any(x in n for x in ["mac", "macos", "darwin", "osx"]):
        return False
    if os_key == "windows" and not any(x in n for x in ["win", "windows"]):
        return False
    if os_key == "linux" and "linux" not in n:
        return False
    if os_key != "windows" and n.endswith(".exe"):
        return False

    # Reject clearly wrong CPU families when the asset name exposes them.
    has_arm = any(x in n for x in ["arm64", "aarch64"])
    has_x64 = any(x in n for x in ["x64", "x86_64", "amd64", "intel"])
    has_x86 = any(x in n for x in ["x86", "i386", "i686", "32bit", "32-bit"]) and not has_x64

    if arch == "arm64" and (has_x64 or has_x86) and not has_arm:
        return False
    if arch == "x64" and (has_arm or has_x86) and not has_x64:
        return False
    if arch == "x86" and (has_arm or has_x64) and not has_x86:
        return False

    # If no CPU is named, accept the asset only after the OS matched. Some upstream
    # projects publish universal archives this way. Validation still runs the binary.
    return True


def install_ctrtool(tools_dir: Path, no_download: bool, quiet: bool = False) -> Path:
    final = tools_dir / exe_name("ctrtool")
    if tool_works(final, "ctrtool"):
        return final

    path_found = shutil.which(exe_name("ctrtool")) or shutil.which("ctrtool")
    if path_found and tool_works(Path(path_found), "ctrtool"):
        safe_mkdir(tools_dir)
        shutil.copy2(path_found, final)
        make_executable(final)
        clear_macos_quarantine(final)
        return final

    if no_download:
        raise SetupError(f"ctrtool is missing. Place it at: {final}")

    log("Finding ctrtool release asset from 3DSGuy/Project_CTR...", quiet)
    try:
        releases = fetch_github_json(PROJECT_CTR_API_RELEASES)
    except Exception as exc:
        raise SetupError(f"Could not query Project_CTR releases: {exc}") from exc

    tried: list[str] = []
    for rel in releases:
        tag = (rel.get("tag_name") or "").lower()
        name = (rel.get("name") or "").lower()
        if "ctrtool" not in tag and "ctrtool" not in name:
            continue
        assets = rel.get("assets") or []
        # Prefer assets that contain ctrtool and match OS/arch. Reject makerom explicitly.
        candidates = []
        for a in assets:
            aname = (a.get("name") or "").lower()
            url = a.get("browser_download_url")
            if not url:
                continue
            if "makerom" in aname:
                continue
            if "ctrtool" not in aname:
                continue
            if not (aname.endswith(".zip") or aname.endswith(".tar.gz") or aname.endswith(".tgz")):
                continue
            if asset_matches_platform(aname):
                candidates.append((a.get("name") or "", url))
        for aname, url in candidates:
            tried.append(aname)
            try:
                return install_from_archive_url(url, tools_dir, "ctrtool", exe_name("ctrtool"), quiet)
            except Exception as exc:
                log(f"ctrtool asset failed ({aname}): {exc}", quiet)

    msg = "Could not auto-download ctrtool."
    if tried:
        msg += f" Tried assets: {', '.join(tried)}."
    msg += f"\nManual fallback: download CTRTool from Project_CTR releases and place it at:\n  {final}"
    raise SetupError(msg)


def install_vgmstream(tools_dir: Path, no_download: bool, quiet: bool = False) -> Path:
    final = tools_dir / exe_name("vgmstream-cli")
    if tool_works(final, "vgmstream-cli"):
        return final
    if final.exists():
        # Do not let a broken binary block setup.
        bad = final.with_suffix(final.suffix + ".bad") if final.suffix else final.with_name(final.name + ".bad")
        try:
            final.rename(bad)
            log(f"Renamed broken vgmstream-cli to: {bad}", quiet)
        except Exception:
            pass

    path_found = shutil.which(exe_name("vgmstream-cli")) or shutil.which("vgmstream-cli")
    if path_found and tool_works(Path(path_found), "vgmstream-cli"):
        safe_mkdir(tools_dir)
        shutil.copy2(path_found, final)
        make_executable(final)
        clear_macos_quarantine(final)
        return final

    if no_download:
        raise SetupError(f"vgmstream-cli is missing. Place it at: {final}")

    url = VGMSTREAM_URLS[detect_os()]
    log("Downloading vgmstream-cli from official vgmstream nightly CLI build...", quiet)
    return install_from_archive_url(url, tools_dir, "vgmstream-cli", exe_name("vgmstream-cli"), quiet)


def install_ffmpeg(tools_dir: Path, no_download: bool, quiet: bool = False) -> Path:
    final = tools_dir / exe_name("ffmpeg")
    if tool_works(final, "ffmpeg"):
        return final

    path_found = shutil.which(exe_name("ffmpeg")) or shutil.which("ffmpeg")
    if path_found and tool_works(Path(path_found), "ffmpeg"):
        safe_mkdir(tools_dir)
        shutil.copy2(path_found, final)
        make_executable(final)
        clear_macos_quarantine(final)
        log(f"Copied ffmpeg from PATH: {final}", quiet)
        return final

    if no_download:
        raise SetupError(f"ffmpeg is missing. Place it at: {final}")

    log("Installing/locating bundled ffmpeg via imageio-ffmpeg...", quiet)
    try:
        import imageio_ffmpeg  # type: ignore
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "--user", "imageio-ffmpeg"], check=True)
        import imageio_ffmpeg  # type: ignore

    ffmpeg_path = Path(imageio_ffmpeg.get_ffmpeg_exe())
    if not tool_works(ffmpeg_path, "ffmpeg"):
        raise SetupError(f"imageio-ffmpeg installed but ffmpeg did not run: {ffmpeg_path}")
    safe_mkdir(tools_dir)
    shutil.copy2(ffmpeg_path, final)
    make_executable(final)
    clear_macos_quarantine(final)
    if not tool_works(final, "ffmpeg"):
        return ffmpeg_path
    return final


def ensure_tools(input_path: Path, no_download: bool, quiet: bool = False) -> dict[str, Path]:
    td = tools_dir_for(input_path)
    safe_mkdir(td)
    log(f"Detected platform: {platform_label()}", quiet)
    tools = {
        "ctrtool": install_ctrtool(td, no_download, quiet),
        "vgmstream-cli": install_vgmstream(td, no_download, quiet),
        "ffmpeg": install_ffmpeg(td, no_download, quiet),
    }
    return tools


def collect_roms(input_path: Path, recursive: bool) -> list[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() not in SUPPORTED_EXTS:
            raise ExtractError(f"Unsupported file type: {input_path.suffix}")
        return [input_path]
    if not input_path.is_dir():
        raise ExtractError(f"Input does not exist: {input_path}")
    globber = input_path.rglob("*") if recursive else input_path.glob("*")
    return sorted(p for p in globber if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS)


def find_banner_file(exefs_dir: Path) -> Path | None:
    candidates = ["banner", "banner.bin", "banner.bnr"]
    for name in candidates:
        p = exefs_dir / name
        if p.exists():
            return p
    for p in exefs_dir.rglob("*"):
        if p.is_file() and p.name.lower() in candidates:
            return p
    return None


def extract_exefs_direct(ctrtool: Path, rom: Path, work: Path, quiet: bool) -> Path:
    exefs = work / "exefs_direct"
    if exefs.exists():
        shutil.rmtree(exefs)
    safe_mkdir(exefs)
    cp = run_command([ctrtool, f"--exefsdir={exefs}", rom], check=False, quiet=quiet, capture=quiet)
    if cp.returncode != 0 and not any(exefs.iterdir()):
        out = cp.stdout or ""
        raise ExtractError(f"ctrtool could not extract ExeFS. ROM may be encrypted/unsupported.\n{out}")
    return exefs


def extract_bcwav_from_banner(banner: Path, out_bcwav: Path) -> None:
    data = banner.read_bytes()
    positions = []
    for magic in (b"CWAV", b"BCWAV"):
        pos = data.find(magic)
        if pos != -1:
            # BCWAV often starts exactly at CWAV magic in banner data.
            positions.append(pos)
    if not positions:
        raise ExtractError(f"No CWAV/BCWAV magic found in banner: {banner}")
    pos = min(positions)
    out_bcwav.write_bytes(data[pos:])


def convert_to_mp3(vgmstream: Path, ffmpeg: Path, bcwav: Path, wav: Path, mp3: Path, quiet: bool) -> None:
    run_command([vgmstream, "-o", wav, bcwav], check=True, quiet=quiet, capture=quiet)
    run_command([ffmpeg, "-y", "-i", wav, "-codec:a", "libmp3lame", "-q:a", "2", mp3], check=True, quiet=quiet, capture=quiet)


def process_rom(rom: Path, tools: dict[str, Path], args) -> tuple[str, str]:
    out_dir = output_dir_for(rom)
    safe_mkdir(out_dir)
    base = rom.stem
    mp3 = out_dir / f"{base}_banner_sound.mp3"
    if mp3.exists() and not args.force:
        return "SKIPPED", f"exists: {mp3}"

    work_root = work_dir_for(rom) / base
    if work_root.exists():
        shutil.rmtree(work_root)
    safe_mkdir(work_root)

    try:
        exefs = extract_exefs_direct(tools["ctrtool"], rom, work_root, args.quiet)
        banner = find_banner_file(exefs)
        if not banner:
            raise ExtractError("No banner file found in ExeFS")
        banner_copy = out_dir / f"{base}_banner.bin"
        shutil.copy2(banner, banner_copy)
        bcwav = out_dir / f"{base}_banner_sound.bcwav"
        wav = out_dir / f"{base}_banner_sound.wav"
        extract_bcwav_from_banner(banner_copy, bcwav)
        convert_to_mp3(tools["vgmstream-cli"], tools["ffmpeg"], bcwav, wav, mp3, args.quiet)
        if not args.keep_intermediate:
            for p in (wav, bcwav, banner_copy):
                try:
                    p.unlink()
                except FileNotFoundError:
                    pass
        return "OK", str(mp3)
    finally:
        if not args.keep_intermediate:
            shutil.rmtree(work_root, ignore_errors=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=f"{APP_NAME} v{VERSION}")
    p.add_argument("input", nargs="?", help="ROM file or folder")
    p.add_argument("--version", action="store_true", help="Print version and exit")
    p.add_argument("--platform-info", action="store_true", help="Print detected OS/CPU and exit")
    p.add_argument("--recursive", action="store_true", help="Scan folders recursively")
    p.add_argument("--force", action="store_true", help="Overwrite existing MP3 output")
    p.add_argument("--keep-intermediate", action="store_true", help="Keep banner/bin/bcwav/wav and work files")
    p.add_argument("--no-download", action="store_true", help="Do not download/install missing tools")
    p.add_argument("--install-tools-only", action="store_true", help="Install/validate tools and exit")
    p.add_argument("--quiet", action="store_true", help="Reduce output")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.version:
        print(f"{APP_NAME} {VERSION}")
        return 0
    if args.platform_info:
        print(f"{APP_NAME} {VERSION}")
        print(f"Detected platform: {platform_label()}")
        print(f"Executable suffix: {' .exe' if detect_os() == 'windows' else ' none'}")
        return 0
    if not args.input:
        print("Error: input is required unless using --version", file=sys.stderr)
        return 2
    input_path = Path(args.input).expanduser().resolve()

    try:
        tools = ensure_tools(input_path, args.no_download, args.quiet)
        if args.install_tools_only:
            print("Tools ready:")
            for k, v in tools.items():
                print(f"  {k}: {v}")
            return 0

        roms = collect_roms(input_path, args.recursive)
        if not roms:
            print("No supported ROM files found.")
            return 1

        ok = skipped = failed = 0
        for rom in roms:
            print(f"\nProcessing: {rom.name}")
            try:
                status, msg = process_rom(rom, tools, args)
                if status == "OK":
                    ok += 1
                    print(f"[OK] {rom.name} -> {msg}")
                elif status == "SKIPPED":
                    skipped += 1
                    print(f"[SKIPPED] {rom.name} - {msg}")
            except Exception as exc:
                failed += 1
                print(f"[FAILED] {rom.name} - {exc}")

        print("\nSummary")
        print(f"  Successful: {ok}")
        print(f"  Skipped:    {skipped}")
        print(f"  Failed:     {failed}")
        return 0 if failed == 0 else 1

    except Exception as exc:
        print(f"Tool setup failed:\n{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
