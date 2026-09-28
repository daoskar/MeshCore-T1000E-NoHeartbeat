#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MeshCore T1000-E Source Builder — No Heartbeat + 500 Contacts
Windows GUI

Buduje własny MeshCore Companion BLE dla T1000-E z dokładnego commita:
727fc0512ce08bfd7b499e46daa7fca6eeec730d  (v1.17.0 / 727fc05)

Domyślny tryb:
- heartbeat LED całkowicie OFF gdy brak nieprzeczytanych wiadomości
- 200 ms blink dla nieprzeczytanych wiadomości pozostaje

Alternatywy:
- tylko LED_CYCLE_MILLIS 4000 -> 400000 (ok. 6 min 40 s)
- całkowicie wyłącz LED status w aplikacji

Skrypt:
- pobiera źródła MeshCore z GitHub,
- patchuje ui-orig/UITask.cpp,
- instaluje PlatformIO Core przez pip, jeśli potrzeba,
- buduje env:t1000e_companion_radio_ble,
- kopiuje wynikowy .uf2 do wybranego katalogu,
- opcjonalnie kopiuje UF2 na wykryty dysk T1000-E DFU.

Nie zmienia PIN_STATUS_LED na 46 — pin 46 w T1000-E to GPS_RESETB.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path
from collections import deque
from dataclasses import dataclass

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


GITHUB_REPO = "meshcore-dev/MeshCore"
GITHUB_API_RELEASES = f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=100"
GITHUB_USER_AGENT = "MeshCore-T1000E-Latest-NoHeartbeat-Builder/3.1"

ENV_NAME = "t1000e_companion_radio_ble"

WORK_ROOT = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MeshCoreNoHeartbeatBuilder"
BUILD_LOG = WORK_ROOT / "build-last.log"

UI_CANDIDATES = (
    Path("examples/companion_radio/ui-orig/UITask.cpp"),
    Path("examples/companion_radio/ui-new/UITask.cpp"),
)


MODE_NO_HEARTBEAT = "no_heartbeat"
MODE_LONG_CYCLE = "long_cycle"
MODE_LED_OFF = "led_off"

class BuildError(RuntimeError):
    pass

def console_python() -> str:
    """
    .pyw is normally launched by pythonw.exe. For PlatformIO we deliberately
    use python.exe inside one hidden console. Toolchain child processes then
    inherit that hidden console instead of opening dozens of visible CMD windows.
    """
    exe = Path(sys.executable)
    if os.name == "nt" and exe.name.lower() == "pythonw.exe":
        candidate = exe.with_name("python.exe")
        if candidate.is_file():
            return str(candidate)
    return str(exe)


PYTHON_CONSOLE = console_python()


@dataclass(frozen=True)
class ReleaseInfo:
    tag: str
    name: str
    published_at: str
    zipball_url: str

    @property
    def version_label(self) -> str:
        return self.tag.removeprefix("companion-")

    @property
    def safe_tag(self) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "_", self.tag)


def github_json(url: str):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": GITHUB_USER_AGENT,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        raise BuildError(f"Nie udało się odpytać GitHub API: {exc}")


def parse_companion_semver(tag: str):
    m = re.fullmatch(r"companion-v(\d+)\.(\d+)\.(\d+)", tag.strip())
    return tuple(map(int, m.groups())) if m else None


def discover_latest_companion_release(on_line) -> ReleaseInfo:
    on_line("Sprawdzam najnowszy stabilny Companion release na GitHub...")
    releases = github_json(GITHUB_API_RELEASES)
    if not isinstance(releases, list):
        raise BuildError("GitHub API zwróciło nieoczekiwany format releases.")

    candidates = []
    for rel in releases:
        if rel.get("draft") or rel.get("prerelease"):
            continue
        tag = str(rel.get("tag_name") or "")
        ver = parse_companion_semver(tag)
        if ver is not None:
            candidates.append((ver, str(rel.get("published_at") or ""), rel))

    if not candidates:
        raise BuildError("Nie znaleziono stabilnego tagu companion-vX.Y.Z.")

    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    rel = candidates[0][2]
    info = ReleaseInfo(
        tag=str(rel["tag_name"]),
        name=str(rel.get("name") or rel["tag_name"]),
        published_at=str(rel.get("published_at") or ""),
        zipball_url=str(rel.get("zipball_url") or ""),
    )
    if not info.zipball_url:
        raise BuildError("Release nie ma zipball_url.")

    on_line(f"✓ Najnowszy Companion: {info.tag}")
    if info.published_at:
        on_line(f"Data publikacji: {info.published_at}")
    return info


def release_zip_path(release: ReleaseInfo) -> Path:
    return WORK_ROOT / f"{release.safe_tag}-source.zip"


def release_source_dir(release: ReleaseInfo) -> Path:
    return WORK_ROOT / f"src-{release.safe_tag}"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_process(cmd, cwd: Path, on_line, log_path: Path | None = None):
    flags = 0
    startupinfo = None
    if os.name == "nt":
        # One hidden console for PlatformIO/toolchain. Grandchildren inherit it,
        # preventing one visible CMD window per compiler/tool invocation.
        flags = subprocess.CREATE_NEW_CONSOLE
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE

    cmd_text = " ".join(map(str, cmd))
    on_line("")
    on_line(">>> " + cmd_text)
    on_line("Katalog: " + str(cwd))

    tail = deque(maxlen=60)
    log_file = None
    try:
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_file = log_path.open("a", encoding="utf-8", errors="replace")
            log_file.write("\n\n>>> " + cmd_text + "\n")
            log_file.write("Katalog: " + str(cwd) + "\n")
            log_file.flush()

        p = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=flags,
            startupinfo=startupinfo,
        )
        assert p.stdout is not None
        for line in p.stdout:
            line = line.rstrip("\r\n")
            tail.append(line)
            on_line(line)
            if log_file:
                log_file.write(line + "\n")
                log_file.flush()

        rc = p.wait()
        if log_file:
            log_file.write(f"\n[exit code: {rc}]\n")
            log_file.flush()

        if rc != 0:
            tail_text = "\n".join(tail)
            raise BuildError(
                f"Polecenie zakończyło się kodem {rc}.\n\n"
                f"Polecenie:\n{cmd_text}\n\n"
                f"Ostatnie linie wyjścia:\n{tail_text}\n\n"
                f"Pełny log:\n{log_path if log_path else '(brak pliku logu)'}"
            )
    finally:
        if log_file:
            log_file.close()


def platformio_available() -> bool:
    try:
        kwargs = {}
        if os.name == "nt":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            kwargs["startupinfo"] = si
            kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
        cp = subprocess.run(
            [PYTHON_CONSOLE, "-m", "platformio", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=20,
            **kwargs,
        )
        return cp.returncode == 0
    except Exception:
        return False


def download_source(release: ReleaseInfo, on_line) -> Path:
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    zip_path = release_zip_path(release)
    src_dir = release_source_dir(release)

    if zip_path.exists() and zip_path.stat().st_size > 100_000:
        on_line(f"Używam cache źródeł dla {release.tag}: {zip_path}")
    else:
        on_line(f"Pobieram źródła {release.tag} z GitHub...")
        req = urllib.request.Request(
            release.zipball_url,
            headers={"User-Agent": GITHUB_USER_AGENT, "Accept": "application/vnd.github+json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as r, zip_path.open("wb") as f:
                while True:
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
        except Exception as exc:
            try:
                zip_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise BuildError(f"Nie udało się pobrać źródeł {release.tag}: {exc}")

    if src_dir.exists():
        shutil.rmtree(src_dir, ignore_errors=True)

    on_line("Rozpakowuję świeże źródła release...")
    tmp = Path(tempfile.mkdtemp(prefix="meshcore_extract_", dir=str(WORK_ROOT)))
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(tmp)
        roots = [p for p in tmp.iterdir() if p.is_dir()]
        if len(roots) != 1:
            raise BuildError("ZIP GitHub ma nieoczekiwaną strukturę.")
        roots[0].rename(src_dir)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if not (src_dir / "platformio.ini").is_file():
        raise BuildError("Po rozpakowaniu brakuje platformio.ini.")

    on_line(f"Źródła gotowe: {src_dir}")
    return src_dir


def _single_led_insert_pos(text: str):
    marker_re = re.compile(
        r"^[ \t]*#(?:if|elif)[ \t]+defined\(PIN_STATUS_LED\)[ \t]*$",
        re.MULTILINE,
    )
    for m in marker_re.finditer(text):
        tail = text[m.end():]
        boundary = re.search(r"^[ \t]*#(?:elif|else|endif)\b", tail, re.MULTILINE)
        branch_end = m.end() + (boundary.start() if boundary else len(tail))
        branch = text[m.end():branch_end]
        cur = re.search(
            r"^[ \t]*int[ \t]+cur_time[ \t]*=[ \t]*millis\(\)[ \t]*;[ \t]*$",
            branch,
            re.MULTILINE,
        )
        if cur and "digitalWrite(PIN_STATUS_LED" in branch:
            return m.end() + cur.end()
    return None


def patch_one_ui_file(path: Path, mode: str, on_line) -> bool:
    if not path.is_file():
        return False

    text = path.read_text(encoding="utf-8")
    original = text

    if mode == MODE_LONG_CYCLE:
        pat = re.compile(r"(#define\s+LED_CYCLE_MILLIS\s+)4000\b")
        text, count = pat.subn(r"\g<1>400000", text, count=1)
        if count != 1:
            return False

    elif mode in (MODE_NO_HEARTBEAT, MODE_LED_OFF):
        pos = _single_led_insert_pos(text)
        if pos is None:
            return False

        if mode == MODE_NO_HEARTBEAT:
            insert = """

  // Custom T1000-E builder v3: heartbeat OFF, unread blink preserved.
  if (_msgcount <= 0) {
    digitalWrite(PIN_STATUS_LED, !LED_STATE_ON);
    return;
  }
"""
        else:
            insert = """

  // Custom T1000-E builder v3: status LED completely OFF.
  digitalWrite(PIN_STATUS_LED, !LED_STATE_ON);
  return;
"""
        text = text[:pos] + insert + text[pos:]
    else:
        raise BuildError("Nieznany tryb patcha.")

    if text == original:
        return False

    path.write_text(text, encoding="utf-8", newline="\n")
    on_line(f"✓ Spatchowano {path.name} w {path.parent.name}")
    return True


def patch_max_contacts(src_dir: Path, max_contacts: int, on_line) -> Path:
    """
    Patch only the T1000-E Companion BLE environment.
    This intentionally leaves repeater/room/USB targets unchanged.
    """
    ini_path = src_dir / "variants" / "t1000-e" / "platformio.ini"
    if not ini_path.is_file():
        raise BuildError(f"Brak konfiguracji T1000-E: {ini_path}")

    text = ini_path.read_text(encoding="utf-8")
    env_re = re.compile(
        rf"(^\\[env:{re.escape(ENV_NAME)}\\]\\s*$)(.*?)(?=^\\[env:|\\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = env_re.search(text)
    if not m:
        raise BuildError(
            f"Nie znaleziono sekcji [env:{ENV_NAME}] w {ini_path}."
        )

    block = m.group(0)
    patched_block, count = re.subn(
        r"(-D\\s+MAX_CONTACTS=)\\d+",
        rf"\\g<1>{max_contacts}",
        block,
        count=1,
    )
    if count != 1:
        raise BuildError(
            f"Nie znaleziono MAX_CONTACTS w sekcji [env:{ENV_NAME}]."
        )

    new_text = text[:m.start()] + patched_block + text[m.end():]
    ini_path.write_text(new_text, encoding="utf-8", newline="\\n")
    on_line(f"✓ MAX_CONTACTS ustawiono na {max_contacts} dla {ENV_NAME}")
    return ini_path


def patch_source(src_dir: Path, release: ReleaseInfo, mode: str, on_line):
    patched = []
    seen = set()

    paths = [src_dir / p for p in UI_CANDIDATES]
    ui_root = src_dir / "examples" / "companion_radio"
    if ui_root.is_dir():
        paths.extend(ui_root.glob("ui-*/UITask.cpp"))

    for p in paths:
        key = str(p.resolve()) if p.exists() else str(p)
        if key in seen:
            continue
        seen.add(key)
        if patch_one_ui_file(p, mode, on_line):
            patched.append(p.relative_to(src_dir))

    if not patched:
        raise BuildError(
            "Najnowszy release zmienił strukturę obsługi LED. "
            "Nie rozpoznałem bezpiecznie PIN_STATUS_LED, więc niczego nie patchuję."
        )

    env_marker = f"[env:{ENV_NAME}]"
    found_env = False
    for ini in src_dir.rglob("*.ini"):
        try:
            if env_marker in ini.read_text(encoding="utf-8", errors="replace"):
                found_env = True
                break
        except OSError:
            pass
    if not found_env:
        raise BuildError(
            f"Najnowszy release nie ma środowiska {ENV_NAME}; nazwa targetu mogła się zmienić."
        )

    on_line(f"✓ Environment: {ENV_NAME}")
    (src_dir / "CUSTOM_T1000E_NO_HEARTBEAT.txt").write_text(
        f"MeshCore release: {release.tag}\n"
        f"Release date: {release.published_at}\n"
        f"Environment: {ENV_NAME}\n"
        f"Mode: {mode}\n"
        "Builder: v3.0 latest-release\n"
        f"Patched files: {', '.join(map(str, patched))}\n",
        encoding="utf-8",
    )


def install_platformio(on_line):
    if platformio_available():
        on_line("PlatformIO Core: wykryty.")
        return

    on_line("PlatformIO Core nie jest zainstalowany.")
    on_line("Instaluję PlatformIO przez pip dla bieżącego Pythona...")
    run_process(
        [PYTHON_CONSOLE, "-m", "pip", "install", "--user", "--upgrade", "platformio"],
        Path.home(),
        on_line,
        BUILD_LOG,
    )
    if not platformio_available():
        raise BuildError("PlatformIO nadal nie jest dostępny po instalacji.")
    on_line("PlatformIO Core: instalacja zakończona.")


def build_firmware(src_dir: Path, on_line) -> Path:
    """
    Build only the official MeshCore create_uf2 custom target.

    The normal default nRF52 build also tries to produce firmware.zip.
    On this Windows/Python setup that ZIP packaging step fails even though
    firmware.elf and firmware.hex are already valid. We do not need the ZIP
    for UF2 flashing, so bypass it completely.
    """
    on_line("")
    on_line(f"Buduję środowisko: {ENV_NAME}")
    on_line("Tryb v2.3: tylko oficjalny target create_uf2 — bez firmware.zip.")
    on_line("Pierwszy build może pobrać toolchain i biblioteki PlatformIO.")

    try:
        BUILD_LOG.unlink(missing_ok=True)
    except OSError:
        pass

    on_line(f"GUI Python: {sys.executable}")
    on_line(f"PlatformIO Python (ukryta konsola): {PYTHON_CONSOLE}")

    try:
        kwargs = {}
        if os.name == "nt":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            kwargs["startupinfo"] = si
            kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
        cp = subprocess.run(
            [PYTHON_CONSOLE, "-m", "platformio", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            **kwargs,
        )
        on_line("PlatformIO: " + cp.stdout.strip())
    except Exception as exc:
        on_line("Nie udało się odczytać wersji PlatformIO: " + str(exc))

    build_dir = src_dir / ".pio" / "build" / ENV_NAME
    firmware_hex = build_dir / "firmware.hex"
    firmware_uf2 = build_dir / "firmware.uf2"

    # Preferred path: MeshCore's own create_uf2 custom target.
    try:
        run_process(
            [
                PYTHON_CONSOLE, "-m", "platformio",
                "run", "-e", ENV_NAME, "-t", "create_uf2"
            ],
            src_dir,
            on_line,
            BUILD_LOG,
        )
    except BuildError as exc:
        # If compilation reached firmware.hex, the only thing we need is the
        # project's official uf2conv conversion. This also recovers cleanly
        # from machines where unrelated nRF ZIP packaging misbehaves.
        if not firmware_hex.is_file():
            raise

        on_line("")
        on_line("PlatformIO zwróciło błąd, ale firmware.hex istnieje.")
        on_line("Uruchamiam bezpośrednio oficjalny MeshCore bin/uf2conv/uf2conv.py...")

        uf2conv = src_dir / "bin" / "uf2conv" / "uf2conv.py"
        if not uf2conv.is_file():
            raise BuildError(
                f"Brak konwertera MeshCore: {uf2conv}\n\nPierwotny błąd:\n{exc}"
            )

        try:
            firmware_uf2.unlink(missing_ok=True)
        except OSError:
            pass

        run_process(
            [
                PYTHON_CONSOLE,
                str(uf2conv),
                "-f", "0xADA52840",
                "-c", str(firmware_hex),
                "-o", str(firmware_uf2),
            ],
            src_dir,
            on_line,
            BUILD_LOG,
        )

    if not firmware_uf2.is_file():
        # Some PlatformIO/custom-target versions may place UF2 under a
        # non-default filename; accept the newest UF2 in this environment.
        uf2s = sorted(
            build_dir.rglob("*.uf2"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        ) if build_dir.is_dir() else []
        if not uf2s:
            if firmware_hex.is_file():
                raise BuildError(
                    "firmware.hex powstał, ale nie znaleziono firmware.uf2 "
                    "po wykonaniu create_uf2."
                )
            raise BuildError(f"Brak katalogu/wyniku buildu: {build_dir}")
        firmware_uf2 = uf2s[0]

    if firmware_uf2.stat().st_size < 100_000:
        raise BuildError(
            f"Powstały UF2 wygląda podejrzanie mały: {firmware_uf2.stat().st_size} B"
        )

    on_line(f"UF2 zbudowany: {firmware_uf2}")
    on_line(f"Rozmiar UF2: {firmware_uf2.stat().st_size:,} B")
    return firmware_uf2


def list_windows_drives():
    if os.name != "nt":
        return []
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    return [f"{chr(65+i)}:\\" for i in range(26) if mask & (1 << i)]


def find_t1000e_dfu():
    found = []
    for root in list_windows_drives():
        p = Path(root) / "INFO_UF2.TXT"
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        normalized = "".join(c for c in txt.lower() if c.isalnum())
        if "t1000e" in normalized:
            found.append(root)
    return found


def flash_to_dfu(uf2: Path, on_line):
    on_line("Czekam na dysk T1000-E DFU (maks. 120 s)...")
    deadline = time.time() + 120
    while time.time() < deadline:
        found = find_t1000e_dfu()
        if len(found) == 1:
            root = found[0]
            target = Path(root) / "NEW.UF2"
            on_line(f"Wykryto T1000-E: {root}")
            with uf2.open("rb") as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
                dst.flush()
                try:
                    os.fsync(dst.fileno())
                except OSError:
                    pass
            on_line(f"Skopiowano UF2 na {target}")
            return
        if len(found) > 1:
            raise BuildError("Wykryto więcej niż jedno T1000-E w DFU.")
        time.sleep(0.5)

    raise BuildError("Nie wykryto T1000-E DFU w ciągu 120 s.")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MeshCore T1000-E — No-Heartbeat + 500 Contacts Builder v3.1")
        self.geometry("900x680")
        self.minsize(780, 580)

        default_out = Path.home() / "Desktop"
        if not default_out.exists():
            default_out = Path.home()

        self.output_dir = tk.StringVar(value=str(default_out))
        self.mode = tk.StringVar(value=MODE_NO_HEARTBEAT)
        self.autoflash = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Gotowy. Przy buildzie sprawdzę najnowszy Companion release.")
        self.release_status = tk.StringVar(value="Najnowszy release: jeszcze nie sprawdzono")
        self._busy = False

        self.build_ui()

    def build_ui(self):
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)

        ttk.Label(
            f,
            text="MeshCore T1000-E Companion BLE — No Heartbeat + 500 kontaktów",
            font=("Segoe UI", 15, "bold"),
        ).pack(anchor="w")

        ttk.Label(
            f,
            text=(
                "Źródło: najnowszy stabilny Companion release wykrywany na GitHub przy każdym buildzie. "
                "Builder omija firmware.zip i generuje UF2 bezpośrednio."
            ),
        ).pack(anchor="w", pady=(3, 12))

        release_row = ttk.Frame(f)
        release_row.pack(fill="x", pady=(0, 10))
        ttk.Label(
            release_row,
            textvariable=self.release_status,
            font=("Segoe UI", 10, "bold"),
        ).pack(side="left")
        ttk.Button(
            release_row,
            text="Sprawdź najnowszy release",
            command=self.check_latest_release,
        ).pack(side="right")

        box = ttk.LabelFrame(f, text="Tryb LED", padding=10)
        box.pack(fill="x")

        ttk.Radiobutton(
            box,
            text="Heartbeat OFF, zachowaj 200 ms blink dla nieprzeczytanych wiadomości — zalecane",
            variable=self.mode,
            value=MODE_NO_HEARTBEAT,
        ).pack(anchor="w", pady=2)

        ttk.Radiobutton(
            box,
            text="Tylko 4000 → 400000 ms (heartbeat mniej więcej raz na 6 min 40 s)",
            variable=self.mode,
            value=MODE_LONG_CYCLE,
        ).pack(anchor="w", pady=2)

        ttk.Radiobutton(
            box,
            text="Wyłącz całą diodę status w aplikacji (także blink wiadomości)",
            variable=self.mode,
            value=MODE_LED_OFF,
        ).pack(anchor="w", pady=2)

        row = ttk.Frame(f)
        row.pack(fill="x", pady=(12, 0))
        ttk.Label(row, text="Katalog wynikowy:").pack(side="left")
        ttk.Entry(row, textvariable=self.output_dir).pack(
            side="left", fill="x", expand=True, padx=8
        )
        ttk.Button(row, text="Wybierz…", command=self.pick_output).pack(side="left")

        ttk.Checkbutton(
            f,
            text="Po buildzie automatycznie skopiuj UF2 na wykryty dysk T1000-E DFU",
            variable=self.autoflash,
        ).pack(anchor="w", pady=(10, 8))

        buttons = ttk.Frame(f)
        buttons.pack(fill="x")
        self.build_btn = ttk.Button(
            buttons,
            text="POBIERZ + PATCHUJ + ZBUDUJ UF2",
            command=self.start_build,
        )
        self.build_btn.pack(side="left")

        ttk.Button(
            buttons,
            text="Otwórz katalog roboczy",
            command=self.open_work,
        ).pack(side="left", padx=(8, 0))

        ttk.Button(
            buttons,
            text="Otwórz build-last.log",
            command=self.open_build_log,
        ).pack(side="left", padx=(8, 0))

        ttk.Button(
            buttons,
            text="Wyczyść źródła/cache ZIP",
            command=self.clear_cache,
        ).pack(side="left", padx=(8, 0))

        ttk.Label(
            f, textvariable=self.status, font=("Segoe UI", 10, "bold")
        ).pack(anchor="w", pady=(12, 5))

        self.log = tk.Text(f, wrap="word", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True)

    def check_latest_release(self):
        if self._busy:
            return
        self.release_status.set("Najnowszy release: sprawdzam GitHub...")

        def worker():
            try:
                rel = discover_latest_companion_release(self.log_line)
                text = f"Najnowszy release: {rel.tag}"
                if rel.published_at:
                    text += "  |  " + rel.published_at.replace("T", " ").replace("Z", " UTC")
                self.after(0, self.release_status.set, text)
            except Exception as exc:
                self.after(0, self.release_status.set, "Najnowszy release: błąd sprawdzania")
                self.after(0, lambda m=str(exc): messagebox.showerror("GitHub", m))

        threading.Thread(target=worker, daemon=True).start()

    def pick_output(self):
        p = filedialog.askdirectory(initialdir=self.output_dir.get())
        if p:
            self.output_dir.set(p)

    def log_line(self, s):
        self.after(0, self._log_line_ui, str(s))

    def _log_line_ui(self, s):
        self.log.insert("end", s + "\n")
        self.log.see("end")
        self.update_idletasks()

    def set_status(self, s):
        self.after(0, self.status.set, s)

    def start_build(self):
        if self._busy:
            return
        self._busy = True
        self.build_btn.configure(state="disabled")
        self.log.delete("1.0", "end")

        mode = self.mode.get()
        out_dir = Path(self.output_dir.get().strip())

        def worker():
            try:
                out_dir.mkdir(parents=True, exist_ok=True)

                self.set_status("Sprawdzam najnowszy Companion release...")
                release = discover_latest_companion_release(self.log_line)
                release_text = f"Najnowszy release: {release.tag}"
                if release.published_at:
                    release_text += "  |  " + release.published_at.replace("T", " ").replace("Z", " UTC")
                self.after(0, self.release_status.set, release_text)

                self.set_status(f"Pobieram/przygotowuję {release.tag}...")
                src_dir = download_source(release, self.log_line)

                self.set_status("Patchuję źródło...")
                patch_source(src_dir, release, mode, self.log_line)

                self.set_status("Sprawdzam PlatformIO...")
                install_platformio(self.log_line)

                self.set_status(f"Buduję {release.tag}...")
                built = build_firmware(src_dir, self.log_line)

                suffix = {
                    MODE_NO_HEARTBEAT: "no-heartbeat",
                    MODE_LONG_CYCLE: "heartbeat-400000ms",
                    MODE_LED_OFF: "status-led-off",
                }[mode]

                final = out_dir / (
                    f"t1000e_companion_radio_ble-{release.version_label}_{suffix}_contacts-{MAX_CONTACTS}.uf2"
                )
                shutil.copyfile(built, final)

                digest = sha256_file(final)
                self.log_line("")
                self.log_line("===== GOTOWE =====")
                self.log_line(f"UF2: {final}")
                self.log_line(f"SHA-256: {digest}")

                if self.autoflash.get():
                    self.set_status("Czekam na T1000-E DFU...")
                    flash_to_dfu(final, self.log_line)

                self.set_status("Gotowe.")
                self.after(
                    0,
                    lambda: messagebox.showinfo(
                        "Gotowe",
                        "Zbudowano własny firmware T1000-E.\n\n"
                        f"{final}\n\nSHA-256:\n{digest}",
                    ),
                )
            except Exception as e:
                self.log_line("")
                self.log_line("✗ BŁĄD: " + str(e))
                if BUILD_LOG.is_file():
                    self.log_line("")
                    self.log_line("Pełny log zapisano tutaj:")
                    self.log_line(str(BUILD_LOG))
                self.set_status("Build przerwany.")
                msg = str(e)
                if len(msg) > 7000:
                    msg = msg[-7000:]
                if BUILD_LOG.is_file():
                    msg += "\n\nPełny log:\n" + str(BUILD_LOG)
                self.after(0, lambda m=msg: messagebox.showerror("Błąd buildu", m))
            finally:
                self._busy = False
                self.after(0, lambda: self.build_btn.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def open_work(self):
        WORK_ROOT.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(WORK_ROOT))
        else:
            messagebox.showinfo("Katalog roboczy", str(WORK_ROOT))

    def open_build_log(self):
        if not BUILD_LOG.is_file():
            messagebox.showinfo("Log buildu", f"Plik jeszcze nie istnieje:\n{BUILD_LOG}")
            return
        if os.name == "nt":
            os.startfile(str(BUILD_LOG))
        else:
            messagebox.showinfo("Log buildu", str(BUILD_LOG))

    def clear_cache(self):
        if self._busy:
            messagebox.showwarning("Build trwa", "Najpierw zakończ bieżący build.")
            return
        try:
            WORK_ROOT.mkdir(parents=True, exist_ok=True)
            for p in list(WORK_ROOT.iterdir()):
                if p.is_dir() and p.name.startswith("src-companion-v"):
                    shutil.rmtree(p, ignore_errors=True)
                elif p.is_file() and p.name.startswith("companion-v") and p.name.endswith("-source.zip"):
                    p.unlink(missing_ok=True)
            messagebox.showinfo("Cache", "Usunięto cache źródeł MeshCore. Cache PlatformIO pozostaje.")
        except Exception as e:
            messagebox.showerror("Cache", str(e))


if __name__ == "__main__":
    App().mainloop()
