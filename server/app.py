"""Local API. Both frontend origins use same-origin reverse proxies."""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import threading
import time
from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import HTTPException
from .runtime import Runtime, Conflict


def create_app(runtime):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024

    @app.get("/api/health")
    def health():
        return jsonify(ok=True, version=1)

    @app.get("/api/project")
    def project():
        with runtime.lock:
            return jsonify(runtime.project())

    @app.get("/api/state")
    def state():
        return jsonify(runtime.snapshot())

    @app.get("/api/devices")
    def compute_devices():
        return jsonify(runtime.compute_devices())

    @app.get("/api/export")
    def export():
        with runtime.lock:
            return Response(
                json.dumps(runtime.project(), ensure_ascii=False, indent=2),
                mimetype="application/json",
                headers={"Content-Disposition": "attachment; filename=spiking-bug-experiment.json"},
            )

    @app.post("/api/command")
    def command():
        data = request.get_json()
        if not isinstance(data, dict):
            raise ValueError("Ожидается JSON-объект")
        result = runtime.command(data.get("action"), data.get("data", {}), data.get("revision"))
        return jsonify(result)

    @app.get("/api/events")
    def events():
        def stream():
            while not runtime.stop_event.is_set():
                # Serialization inside lock avoids mutable-world iteration races.
                with runtime.lock:
                    payload = json.dumps(runtime.snapshot(), separators=(",", ":"), allow_nan=False)
                yield "data: " + payload + "\n\n"
                time.sleep(1 / 15)

        return Response(
            stream(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.errorhandler(Exception)
    def error(exc):
        if isinstance(exc, Conflict):
            return jsonify(error=str(exc)), 409
        if isinstance(exc, (ValueError, KeyError, TypeError, OverflowError)):
            return jsonify(error=str(exc)), 400
        if isinstance(exc, HTTPException):
            return jsonify(error=exc.description), exc.code
        app.logger.exception("Request failed")
        return jsonify(error="Ошибка сервера; подробности в журнале"), 500

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--project", type=Path, default=Path("data/project.json"))
    parser.add_argument("--ephemeral", action="store_true", help="Use an unsaved, fresh experiment")
    args = parser.parse_args()
    runtime = Runtime(None if args.ephemeral else args.project)
    threading.Thread(target=runtime.loop, daemon=True).start()
    try:
        create_app(runtime).run(host="127.0.0.1", port=args.port, threaded=True, use_reloader=False)
    finally:
        runtime.stop_event.set()


if __name__ == "__main__":
    main()
