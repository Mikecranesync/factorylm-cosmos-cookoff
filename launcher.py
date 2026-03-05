"""
FactoryLM Launcher — starts Matrix API + Demo UI, opens browser.

Works both as a normal script and inside a PyInstaller .exe bundle.
"""

import multiprocessing
import sys
import threading
import time
import webbrowser
from pathlib import Path


def get_base():
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


sys.path.insert(0, str(get_base()))


def start_matrix():
    import uvicorn
    uvicorn.run("services.matrix.app:app", host="0.0.0.0", port=8100, log_level="error")


def start_ui():
    import uvicorn
    uvicorn.run("services.matrix.demo_ui:app", host="0.0.0.0", port=8080, log_level="error")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    print("FactoryLM — Powered by NVIDIA Cosmos Reason 2")
    print("Dashboard opening at http://localhost:8080 ...")
    threading.Thread(target=start_matrix, daemon=True).start()
    threading.Thread(target=start_ui, daemon=True).start()
    threading.Thread(
        target=lambda: (time.sleep(2.5), webbrowser.open("http://localhost:8080")),
        daemon=True,
    ).start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        sys.exit(0)
