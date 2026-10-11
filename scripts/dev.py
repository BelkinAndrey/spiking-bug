"""Start and stop the three local services as one process group."""

import os
from pathlib import Path
import signal
import shutil
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.chdir(ROOT)
    if not (ROOT / "node_modules/vite").exists():
        raise SystemExit("Сначала запустите ./setup.sh")
    for port in (8000, 5173, 5174):
        with socket.socket() as sock:
            if os.name != "nt":
                # A stopped server's TIME_WAIT sockets must not block a quick restart.
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                raise SystemExit(f"Порт {port} занят; остановите прежний экземпляр приложения.")
    npm = shutil.which("npm")
    if not npm:
        raise SystemExit("Установите Node.js и npm")
    commands = [
        [sys.executable, "-m", "server.app"],
        [npm, "run", "dev:environment"],
        [npm, "run", "dev:editor"],
    ]
    children = []
    try:
        for cmd in commands:
            children.append(subprocess.Popen(cmd, start_new_session=os.name != "nt"))
        print(
            "\nОкружение: http://127.0.0.1:5173\nКоннектом: http://127.0.0.1:5174\nCtrl+C останавливает все три процесса.\n",
            flush=True,
        )
        while all(p.poll() is None for p in children):
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        for p in children:
            if p.poll() is None:
                if os.name != "nt":
                    os.killpg(p.pid, signal.SIGTERM)
                else:
                    p.terminate()
        for p in children:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    main()
