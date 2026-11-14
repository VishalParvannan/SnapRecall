"""Start SnapRecall as a desktop window (or in your browser).

    python snaprecall.py                 # a desktop window if pywebview is installed, else your browser
    python snaprecall.py --browser       # always use your default browser
    python snaprecall.py --no-open       # just run the server, and print its address

The app runs entirely on this computer: the server listens on 127.0.0.1 only. Closing the window
(or pressing Ctrl+C here) stops it. Indexing runs in the background while the app is open.
"""
from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import webbrowser

DEFAULT_PORT = 8610
HOST = "127.0.0.1"


def pick_port(preferred: int) -> int:
    """The preferred port if it is free, otherwise any free one."""
    for port in (preferred, 0):
        with socket.socket() as probe:
            try:
                probe.bind((HOST, port))
            except OSError:
                continue
            return probe.getsockname()[1]
    raise OSError("No free port to run SnapRecall on.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SnapRecall: find screenshots by describing them.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port to listen on (default {DEFAULT_PORT})")
    parser.add_argument("--browser", action="store_true", help="use your default browser instead of a desktop window")
    parser.add_argument("--no-open", action="store_true", help="don't open anything; only run the server")
    args = parser.parse_args(argv)

    import uvicorn

    from web.app import create_app

    port = pick_port(args.port)
    server = uvicorn.Server(uvicorn.Config(create_app(), host=HOST, port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, name="snaprecall-server", daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            print("SnapRecall could not start its server.", file=sys.stderr)
            return 1
        time.sleep(0.05)
    url = f"http://{HOST}:{port}/"

    try:
        if args.no_open:
            print(f"SnapRecall is running at {url} (press Ctrl+C to stop)")
            while thread.is_alive():
                time.sleep(0.5)
        else:
            try:
                import webview  # pywebview: a native window around the same page
            except ImportError:
                webview = None
            if webview is not None and not args.browser:
                webview.create_window("SnapRecall", url, width=1280, height=860, min_size=(900, 600))
                webview.start()  # returns when the window is closed
            else:
                print(f"SnapRecall is running at {url} (press Ctrl+C to stop)")
                if webview is None and not args.browser:
                    print("Tip: pip install pywebview opens SnapRecall in its own window instead of a tab.")
                webbrowser.open(url)
                while thread.is_alive():
                    time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.should_exit = True
        thread.join(10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
