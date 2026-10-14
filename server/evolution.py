"""Server-owned evolutionary search, isolated trial episodes, atomic JSON archives."""

from __future__ import annotations
import copy
import json
import logging
import os
from pathlib import Path
import random
import shutil
import weakref
import statistics
import tempfile
import threading
import time
import uuid
from . import genome, schema
from .development import seed
from .trials import Trials, run_attempt, summarize


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False))
    os.replace(temporary, path)


def fitness(rows, net, options):
    durations = [r["duration"] for r in rows]
    lifetime = statistics.mean(durations)
    penalty = options["fitness"]["neuron_penalty"] * len(net["neurons"])
    return dict(
        value=lifetime - penalty,
        lifetime=lifetime,
        neuron_penalty=penalty,
        lifetime_std=statistics.pstdev(durations),
    )


class Deadline:
    def __init__(self, event, seconds):
        self.event = event
        self.until = time.monotonic() + seconds

    def is_set(self):
        return self.event.is_set() or time.monotonic() >= self.until


def assess(project, options, stop, progress, validation=False):
    rows = []
    count = options["validation_attempts"] if validation else options["attempts"]
    start_seed = options["validation_seed"] if validation else options["search_seed"]
    trial_options = dict(
        duration=options["duration"], seed=start_seed, randomize=options["randomize"]
    )
    for i in range(count):
        if stop.is_set():
            return None
        row = run_attempt(
            project, trial_options, i, stop, lambda tick, limit: progress(i, count, tick / limit)
        )
        if row is None:
            return None
        rows.append(row)
        progress(i + 1, count, 0)
    return dict(
        rows=rows, summary=summarize(rows), fitness=fitness(rows, project["topology"], options)
    )


def evaluate(project, initial, options, event, publish, directory, job_id):
    """A fixed seed panel for all generations; validation is never used for selection."""
    directory = Path(directory)
    start = time.monotonic()
    stop = Deadline(event, options["wall_seconds"])
    rng = random.Random(seed("selection", options["seed"]))
    state = dict(
        id=job_id,
        settings=options,
        status="running",
        generation=0,
        candidate=0,
        phase="baseline",
        completed=0,
        rejected=0,
        history=[],
        best=None,
        baseline=None,
        error=None,
        episode=0,
        episodes=options["attempts"],
        episode_progress=0,
    )
    last_report = 0.0

    def report(force=False, **changes):
        nonlocal last_report
        state.update(changes)
        now = time.monotonic()
        if not force and now - last_report < 0.25:
            return
        last_report = now
        elapsed = now - start
        state.update(
            elapsed_seconds=elapsed, evaluations_per_second=state["completed"] / max(elapsed, 1e-9)
        )
        publish(copy.deepcopy(state))
        atomic_json(directory / "status.json", state)

    def progress(i, count, fraction):
        report(episode=i, episodes=count, episode_progress=fraction)

    def document(record, label):
        p = copy.deepcopy(project)
        p.update(
            topology=record["net"], compute={"device": "cpu"}, name=f"Evolution · {label}"[:160]
        )
        p.setdefault("extensions", {})["evolution"] = dict(
            version=1,
            decoder=(record.get("genome") or {}).get("decoder", genome.DECODER),
            run_id=job_id,
            mode=options["mode"],
            settings=options,
            genome=record.get("genome"),
            generation=record["generation"],
            individual_id=record["id"],
            parent=record.get("parent"),
            search=record.get("search"),
            validation=record.get("validation"),
            size=genome.size(record["net"]),
            source_revision=project.get("revision"),
            origin=project.get("extensions", {}).get("evolution", {}).get("individual_id"),
        )
        return p

    def save(record, name):
        atomic_json(directory / (name + ".json"), document(record, name))
        atomic_json(
            directory / (name + ".meta.json"),
            dict(
                id=f"{job_id}/{name}",
                label=name,
                run_id=job_id,
                generation=record["generation"],
                size=genome.size(record["net"]),
                fitness=(record.get("search") or {}).get("fitness"),
                saved=time.time(),
            ),
        )

    def public(record):
        return {
            k: copy.deepcopy(record[k])
            for k in ("id", "generation", "parent", "search", "validation")
            if k in record
        } | {"size": genome.size(record["net"])}

    best = None
    archive = []
    try:
        project = copy.deepcopy(project)
        project["compute"] = {"device": "cpu"}
        baseline_net = project["topology"]
        max_delay = max((s["delay"] for s in baseline_net["synapses"]), default=1)
        estimate = (
            len(baseline_net["neurons"]) * (4096 + (max_delay + 1) * 16)
            + genome.size(baseline_net)["synapses"] * 2048
        )
        if estimate > options["memory_mb"] * 1048576:
            raise ValueError("Исходная сеть превышает бюджет памяти")
        baseline = dict(id="baseline", net=baseline_net, generation=-1)
        save(baseline, "baseline")
        report(True)
        baseline["search"] = assess(project, options, stop, progress)
        if baseline["search"] is None:
            report(
                True,
                status="cancelled",
                stop_reason="requested" if event.is_set() else "time_budget",
            )
            return
        report(True, phase="baseline_validation")
        baseline["validation"] = assess(project, options, stop, progress, True)
        save(baseline, "baseline")
        state["baseline"] = public(baseline)
        parents = []
        initial_net = genome.decode(initial, project, options, stop)
        next_genomes = [(initial, None)]
        for generation in range(options["generations"]):
            if stop.is_set():
                break
            report(True, generation=generation, candidate=0, phase="search")
            population = []
            # Elites are already fully evaluated on exactly the same panel.
            if parents:
                population.extend(copy.deepcopy(parents[: options["elite"]]))
            while len(population) < options["population"] and not stop.is_set():
                slot = len(population)
                parent_id = None
                last_error = ""
                for retry in range(32):
                    try:
                        if next_genomes:
                            genes, parent_id = next_genomes.pop(0)
                            net = initial_net
                            break
                        else:
                            parent = (
                                max(
                                    rng.choices(parents, k=options["tournament"]),
                                    key=lambda p: p["search"]["fitness"]["value"],
                                )
                                if parents
                                else None
                            )
                            parent_id = parent["id"] if parent else "initial"
                            genes = genome.mutate(
                                parent["genome"] if parent else initial,
                                project,
                                options,
                                seed(options["seed"], generation, slot, retry),
                            )
                        net = genome.decode(genes, project, options, stop)
                        break
                    except ValueError as exc:
                        last_error = str(exc)
                        state["rejected"] += 1
                else:
                    # Bounded retries: clone a valid parent instead of wedging a generation.
                    if not parents:
                        raise ValueError("Не удалось создать допустимого потомка: " + last_error)
                    parent = parents[0]
                    genes, net, parent_id = (
                        copy.deepcopy(parent["genome"]),
                        copy.deepcopy(parent["net"]),
                        parent["id"],
                    )
                record = dict(
                    id=f"g{generation:05d}_i{slot:03d}",
                    parent=parent_id,
                    genome=genes,
                    net=net,
                    generation=generation,
                )
                report(True, candidate=slot + 1, phase="search", episode=0, episode_progress=0)
                candidate_project = {**project, "topology": net}
                result = assess(candidate_project, options, stop, progress)
                if result is None:
                    break
                record["search"] = result
                state["completed"] += 1
                population.append(record)
                # Completed candidates survive cancellation; partial candidates are never stored.
                save(record, "candidate_" + record["id"])
                archive.append("candidate_" + record["id"])
                while len(archive) > options["archive_size"]:
                    expired = archive.pop(0)
                    (directory / (expired + ".json")).unlink(missing_ok=True)
                    (directory / (expired + ".meta.json")).unlink(missing_ok=True)
                if best is None or result["fitness"]["value"] > best["search"]["fitness"]["value"]:
                    best = copy.deepcopy(record)
                    save(best, "best")
                    report(True, phase="validation", best=public(best))
                    best["validation"] = assess(candidate_project, options, stop, progress, True)
                    save(best, "best")
                    save(best, "candidate_" + record["id"])
                    state["best"] = public(best)
                report(True, phase="search", best=public(best))
            if len(population) != options["population"]:
                break
            parents = sorted(population, key=lambda p: (-p["search"]["fitness"]["value"], p["id"]))
            scores = [p["search"]["fitness"]["value"] for p in parents]
            state["history"].append(
                dict(
                    generation=generation,
                    best=max(scores),
                    median=statistics.median(scores),
                    std=statistics.pstdev(scores),
                    size=genome.size(parents[0]["net"]),
                )
            )
            report(True)
        report(
            True,
            status="cancelled" if stop.is_set() else "completed",
            stop_reason=("requested" if event.is_set() else "time_budget")
            if stop.is_set()
            else None,
            phase="done",
            episode_progress=0,
        )
    except InterruptedError:
        report(
            True,
            status="cancelled",
            phase="done",
            stop_reason="requested" if event.is_set() else "time_budget",
        )
    except Exception as exc:
        logging.exception("Evolution failed")
        report(True, status="failed", error=str(exc))


def _worker(project, genes, options, stop, pipe, directory, job_id):
    try:
        try:
            os.nice(5)
        except (AttributeError, OSError):
            pass
        evaluate(project, genes, options, stop, pipe.send, directory, job_id)
    finally:
        pipe.close()


class Evolution(Trials):
    def __init__(self, path=None):
        super().__init__()
        self.root = Path(tempfile.mkdtemp(prefix="bug-evolution-")) if path is None else Path(path)
        self._cleanup = (
            weakref.finalize(self, shutil.rmtree, str(self.root), True) if path is None else None
        )
        self.root.mkdir(parents=True, exist_ok=True)
        statuses = sorted(self.root.glob("*/status.json"), key=lambda p: p.stat().st_mtime)
        if statuses:
            self.job = json.loads(statuses[-1].read_text())
            if self.job["status"] in ("running", "cancelling"):
                self.job.update(
                    status="interrupted",
                    error="Сервер был перезапущен; сохранённые результаты доступны",
                )

    def start(self, runtime, data, revision):
        from .runtime import Conflict

        options = genome.settings(data)
        with self.lock:
            if self.process is not None and self.process.is_alive():
                raise Conflict("Эволюция уже выполняется")
            with runtime.lock:
                if revision != runtime.revision:
                    raise Conflict(
                        "Проект изменён в другом окне. Данные обновлены; повторите действие."
                    )
                project = copy.deepcopy(runtime.project())
            genes = genome.initial(project, options)
            job_id = uuid.uuid4().hex
            directory = self.root / job_id
            directory.mkdir()
            atomic_json(directory / "source.json", project)
            atomic_json(directory / "experiment.json", dict(settings=options, genome=genes))
            read, write = self.context.Pipe(duplex=False)
            self.stop = self.context.Event()
            self.job = dict(
                id=job_id,
                status="running",
                settings=options,
                project_name=project["name"],
                revision=revision,
                generation=0,
                candidate=0,
                completed=0,
                history=[],
                best=None,
                baseline=None,
                elapsed_seconds=0,
                evaluations_per_second=0,
                error=None,
                phase="starting",
                episode=0,
                episodes=options["attempts"],
                episode_progress=0,
            )
            atomic_json(directory / "status.json", self.job)
            self.process = self.context.Process(
                target=_worker,
                args=(project, genes, options, self.stop, write, str(directory), job_id),
                daemon=True,
            )
            try:
                self.process.start()
            except Exception:
                read.close()
                write.close()
                self.job.update(status="failed", error="Не удалось запустить процесс")
                atomic_json(directory / "status.json", self.job)
                self.process = None
                raise
            write.close()
            threading.Thread(
                target=self._collect, args=(self.process, read, job_id), daemon=True
            ).start()
            return self.snapshot()

    def artifacts(self):
        result = []
        for p in self.root.glob("*/*.meta.json"):
            try:
                result.append(json.loads(p.read_text()))
            except (OSError, ValueError):
                continue
        return sorted(result, key=lambda x: -x["saved"])

    def snapshot(self):
        with self.lock:
            return dict(job=copy.deepcopy(self.job), artifacts=self.artifacts())

    def cancel(self, job_id):
        super().cancel(job_id)
        return self.snapshot()

    def artifact_path(self, identity):
        if not isinstance(identity, str) or identity.count("/") != 1:
            raise ValueError("Некорректный ID экземпляра")
        run, name = identity.split("/")
        schema.identifier(run)
        schema.identifier(name)
        if run in (".", "..") or name in (".", ".."):
            raise ValueError("Некорректный ID экземпляра")
        path = self.root / run / (name + ".json")
        if (
            name in ("status", "source", "experiment")
            or name.endswith(".meta")
            or not path.is_file()
        ):
            raise ValueError("Экземпляр не найден")
        return path

    def artifact(self, identity):
        try:
            return json.loads(self.artifact_path(identity).read_text())
        except FileNotFoundError as exc:
            raise ValueError("Экземпляр вытеснен из автоматического архива") from exc

    def pin(self, identity):
        with self.lock:
            data = self.artifact(identity)
            if sum(1 for _ in self.root.glob("*/saved_*.meta.json")) >= 100:
                raise ValueError("Лимит: 100 вручную сохранённых экземпляров")
            run = identity.split("/")[0]
            name = "saved_" + uuid.uuid4().hex[:12]
            atomic_json(self.root / run / (name + ".json"), data)
            meta = data["extensions"]["evolution"]
            atomic_json(
                self.root / run / (name + ".meta.json"),
                dict(
                    id=f"{run}/{name}",
                    label=name,
                    run_id=run,
                    generation=meta["generation"],
                    size=meta["size"],
                    fitness=(meta.get("search") or {}).get("fitness"),
                    saved=time.time(),
                ),
            )
            return self.snapshot()
