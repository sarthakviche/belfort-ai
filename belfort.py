"""Belfort AI desktop launcher: starts the backend and shows the UI in its own app window.

One process does both jobs. Closing the window stops the server.
Run with pythonw (no console) via the desktop shortcut, or:  .venv\\Scripts\\python belfort.py
"""
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = 8765
URL = f"http://127.0.0.1:{PORT}"

# pythonw has no console, so stdout/stderr are None and logging would crash the server.
if sys.stdout is None or sys.stderr is None:
    (ROOT / "data").mkdir(exist_ok=True)
    _log = open(ROOT / "data" / "belfort.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log


def port_open() -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def start_server():
    import uvicorn
    sys.path.insert(0, str(ROOT))
    config = uvicorn.Config("app.main:app", host="127.0.0.1", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    return server


def wait_ready(seconds=40) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if port_open():
            return True
        time.sleep(0.25)
    return False


def set_icon():
    """Give the app window the Belfort logo (taskbar, Alt+Tab, title bar)."""
    try:
        import ctypes
        u = ctypes.windll.user32
        ico = str(ROOT / "scripts" / "belfort.ico")
        for _ in range(40):                  # wait for the window to exist
            hwnd = u.FindWindowW(None, "Belfort AI")
            if hwnd:
                break
            time.sleep(0.25)
        else:
            return
        LR_LOADFROMFILE, IMAGE_ICON, WM_SETICON = 0x10, 1, 0x80
        for kind, size in ((1, 48), (0, 16)):  # big icon (taskbar), small icon (title bar)
            h = u.LoadImageW(None, ico, IMAGE_ICON, size, size, LR_LOADFROMFILE)
            if h:
                u.SendMessageW(hwnd, WM_SETICON, kind, h)
    except Exception:
        pass


def main():
    server = None
    if not port_open():                      # already running? just open a window on it
        server = start_server()
        if not wait_ready():
            sys.exit("Belfort AI: the server did not start.")

    try:
        import webview
    except ImportError:                      # no pywebview: fall back to an Edge app window
        subprocess.Popen(["msedge", f"--app={URL}"])
        if server:
            while True:
                time.sleep(3600)
        return

    store = ROOT / "data" / "webview"        # keeps open files, capital, risk between launches
    store.mkdir(parents=True, exist_ok=True)
    try:                                     # own taskbar identity, so Windows stops grouping it under Python
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Belfort.AI")
    except Exception:
        pass
    webview.create_window("Belfort AI", URL, width=1500, height=950, min_size=(1000, 650), background_color="#08080a")
    webview.start(set_icon, private_mode=False, storage_path=str(store))
    if server:
        server.should_exit = True


if __name__ == "__main__":
    main()
