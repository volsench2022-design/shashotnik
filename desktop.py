from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def config_file() -> Path:
    app_data = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return app_data / "Checkers Arena" / "settings.json"


def validate_server_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.path not in {"", "/"}
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Enter a server address such as https://your-game.onrender.com.")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def saved_server_url() -> str | None:
    path = config_file()
    if not path.exists():
        return None
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read the saved app settings at {path}.") from error
    value = settings.get("server_url") if isinstance(settings, dict) else None
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"The saved server address in {path} is invalid.")
    return validate_server_url(value)


def save_server_url(server_url: str) -> None:
    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"server_url": server_url}, indent=2),
        encoding="utf-8",
    )


def prompt_server_url(initial: str | None) -> str | None:
    import tkinter as tk
    from tkinter import messagebox, simpledialog

    root = tk.Tk()
    root.withdraw()
    try:
        if initial is None and messagebox.askyesno(
            "Checkers Arena",
            "Host the game server on this PC?\n\n"
            "Choose No to join another player's server.",
            parent=root,
        ):
            return "host"
        while True:
            value = simpledialog.askstring(
                "Connect to Checkers Arena",
                "Enter the host's invite address (for example, https://games.example.com):",
                initialvalue=initial or "",
                parent=root,
            )
            if value is None:
                return None
            try:
                server_url = validate_server_url(value)
            except ValueError as error:
                messagebox.showerror("Invalid server address", str(error), parent=root)
                initial = value
                continue
            save_server_url(server_url)
            return server_url
    finally:
        root.destroy()


def local_addresses() -> list[str]:
    addresses = {
        item[4][0]
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        if not item[4][0].startswith("127.")
    }
    return sorted(addresses)


def run_local_server(port: int, certfile: str | None, keyfile: str | None):
    import uvicorn

    os.environ.setdefault(
        "CHECKERS_DB",
        str(config_file().parent / "checkers.db"),
    )
    from app import app

    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="warning",
        ssl_certfile=certfile,
        ssl_keyfile=keyfile,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="checkers-server", daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if server.started:
            return server, thread
        if not thread.is_alive():
            raise RuntimeError("The local game server stopped during startup.")
        time.sleep(0.1)
    server.should_exit = True
    thread.join(timeout=5)
    raise RuntimeError("The local game server did not start within 15 seconds.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch the Checkers Arena Windows app.")
    parser.add_argument("--server-url", help="Online Checkers Arena server URL")
    parser.add_argument(
        "--host-game",
        action="store_true",
        help="Host the game server on this PC",
    )
    parser.add_argument("--port", type=int, default=8000, help="Local server port")
    parser.add_argument("--ssl-certfile", help="TLS certificate file for a public host")
    parser.add_argument("--ssl-keyfile", help="TLS private key file for a public host")
    args = parser.parse_args()

    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535.")
    if bool(args.ssl_certfile) != bool(args.ssl_keyfile):
        parser.error("--ssl-certfile and --ssl-keyfile must be provided together.")
    if args.host_game and args.server_url:
        parser.error("--host-game and --server-url cannot be used together.")

    server = None
    try:
        if args.host_game:
            host_game = True
            server_url = None
        else:
            server_url = args.server_url or os.environ.get("CHECKERS_SERVER_URL") or saved_server_url()
            if server_url is None:
                selection = prompt_server_url(None)
                if selection == "host":
                    host_game = True
                    server_url = None
                else:
                    host_game = False
                    server_url = selection
            else:
                host_game = False
            if server_url is not None:
                server_url = validate_server_url(server_url)
    except ValueError as error:
        from tkinter import messagebox

        messagebox.showerror("Checkers Arena settings", str(error))
        return 1

    if not host_game and server_url is None:
        return 0
    if server_url is not None and (args.server_url or os.environ.get("CHECKERS_SERVER_URL")):
        save_server_url(server_url)

    try:
        import webview
    except ImportError:
        print("Desktop dependencies are missing. Install requirements-desktop.txt.", file=sys.stderr)
        return 1

    if host_game:
        try:
            server, _ = run_local_server(args.port, args.ssl_certfile, args.ssl_keyfile)
        except Exception as error:
            from tkinter import messagebox

            messagebox.showerror("Could not start hosting", str(error))
            return 1
        scheme = "https" if args.ssl_certfile else "http"
        server_url = f"{scheme}://127.0.0.1:{args.port}"
        addresses = local_addresses()
        address_list = "\n".join(f"  {scheme}://{address}:{args.port}" for address in addresses)
        message = (
            f"The game server is running on this PC at:\n  {server_url}\n\n"
            "Invite players on the same Wi-Fi using one of these addresses:\n"
            f"{address_list or '  No local network address was found.'}\n\n"
            "For players outside your Wi-Fi, configure router port forwarding and HTTPS "
            "before sharing a public address. Never send passwords over public HTTP."
        )
        from tkinter import messagebox

        messagebox.showinfo("Hosting Checkers Arena", message)

    try:
        webview.create_window(
            "Checkers Arena",
            server_url,
            width=1280,
            height=900,
            min_size=(960, 680),
        )
        webview.start()
    finally:
        if server is not None:
            server.should_exit = True
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
