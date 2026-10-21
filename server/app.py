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
from .trials import Trials
from .evolution import Evolution


def create_app(runtime):
    app = Flask(__name__)
    trials = Trials()
    app.extensions["trials"] = trials
    evolution = Evolution(runtime.path.parent / "evolution" if runtime.path else None)
    app.extensions["evolution"] = evolution
    # Large generated topologies must also support import and structural edits.
    app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024

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

    @app.get("/api/trials")
    def trial_status():
        return jsonify(trials.snapshot())

    @app.post("/api/trials")
    def start_trials():
        data = request.get_json()
        if not isinstance(data, dict):
            raise ValueError("Ожидается JSON-объект")
        return jsonify(trials.start(runtime, data.get("settings", {}), data.get("revision")))

    @app.post("/api/trials/cancel")
    def cancel_trials():
        data = request.get_json()
        if not isinstance(data, dict):
            raise ValueError("Ожидается JSON-объект")
        return jsonify(trials.cancel(data.get("id")))

    @app.get("/api/evolution")
    def evolution_status():
        return jsonify(evolution.snapshot())

    @app.post("/api/evolution")
    def start_evolution():
        data = request.get_json()
        if not isinstance(data, dict):
            raise ValueError("Ожидается JSON-объект")
        return jsonify(evolution.start(runtime, data.get("settings", {}), data.get("revision")))

    @app.post("/api/evolution/cancel")
    def cancel_evolution():
        return jsonify(evolution.cancel(request.get_json()["id"]))

    @app.get("/api/evolution/artifact/<run>/<name>")
    def evolution_artifact(run, name):
        return jsonify(evolution.artifact(run + "/" + name))

    @app.post("/api/evolution/save")
    def save_evolution():
        return jsonify(evolution.pin(request.get_json()["id"]))

    @app.post("/api/evolution/clear")
    def clear_evolution_archive():
        return jsonify(evolution.clear_archive())

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
    app = create_app(runtime)
    try:
        app.run(host="127.0.0.1", port=args.port, threaded=True, use_reloader=False)
    finally:
        runtime.stop_event.set()
        app.extensions["trials"].close()
        app.extensions["evolution"].close()


if __name__ == "__main__":
    main()
