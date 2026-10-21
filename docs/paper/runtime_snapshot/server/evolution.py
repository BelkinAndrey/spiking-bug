"""Server-owned evolutionary search, isolated trial episodes, atomic JSON archives."""

from __future__ import annotations
import copy
from itertools import count
import json
import logging
import os
from pathlib import Path
import random
import shutil
import signal
import weakref
import statistics
import tempfile
import threading
import time
import uuid
from . import genome, schema
from .development import seed
from .trials import Trials, run_attempt, summarize
from .evolution_pool import EpisodePool
from .storage import atomic_json, unlink_file


def fitness(rows):
    durations = [r["duration"] for r in rows]
    lifetime = statistics.mean(durations)
    return dict(
        value=lifetime,
        lifetime=lifetime,
        lifetime_std=statistics.pstdev(durations),
    )


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
    return dict(rows=rows, summary=summarize(rows), fitness=fitness(rows))


def evaluate(project, initial, options, event, publish, directory, job_id):
    """A fixed seed panel for all generations; validation is never used for selection."""
    directory = Path(directory)
    start = time.monotonic()
    stop = event
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

    pool = None

    def assessment(candidate_project, validation=False, ticket=None):
        if pool is None:
            return assess(candidate_project, options, stop, progress, validation)
        if ticket is None:
            ticket = pool.submit(candidate_project, options, validation)
        rows = pool.collect(ticket, progress)
        if rows is None:
            return None
        return dict(
            rows=rows,
            summary=summarize(rows),
            fitness=fitness(rows),
        )

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
        if estimate * options["workers"] > options["memory_mb"] * 1048576:
            raise ValueError("Исходная сеть превышает бюджет памяти")
        if options["workers"] > 1:
            pool = EpisodePool(options["workers"], stop)
        baseline = dict(id="baseline", net=baseline_net, generation=-1)
        save(baseline, "baseline")
        report(True)
        baseline["search"] = assessment(project)
        if baseline["search"] is None:
            report(
                True,
                status="cancelled",
                stop_reason="requested",
            )
            return
        report(True, phase="baseline_validation")
        baseline["validation"] = assessment(project, True)
        save(baseline, "baseline")
        state["baseline"] = public(baseline)
        parents = []
        initial_net = genome.decode(initial, project, options, stop)
        next_genomes = [(initial, None)]
        for generation in count():
            if stop.is_set() or (options["generations"] and generation >= options["generations"]):
                break
            report(True, generation=generation, candidate=0, phase="search")
            population = []
            # Elites are already fully evaluated on exactly the same panel.
            if parents:
                population.extend(copy.deepcopy(parents[: options["elite"]]))
            candidates = []
            while len(population) + len(candidates) < options["population"] and not stop.is_set():
                slot = len(population) + len(candidates)
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
                                stop,
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
                candidates.append(record)
            tickets = [
                pool.submit({**project, "topology": record["net"]}, options) if pool else None
                for record in candidates
            ]
            for record, ticket in zip(candidates, tickets):
                report(
                    True,
                    candidate=len(population) + 1,
                    phase="search",
                    episode=0,
                    episode_progress=0,
                )
                candidate_project = {**project, "topology": record["net"]}
                result = assessment(candidate_project, ticket=ticket)
                if result is None:
                    if pool is not None and stop.is_set():
                        continue
                    break
                record["search"] = result
                state["completed"] += 1
                population.append(record)
                # Completed candidates survive cancellation; partial candidates are never stored.
                save(record, "candidate_" + record["id"])
                archive.append("candidate_" + record["id"])
                while len(archive) > options["archive_size"]:
                    expired = archive.pop(0)
                    unlink_file(directory / (expired + ".json"))
                    unlink_file(directory / (expired + ".meta.json"))
                if best is None or result["fitness"]["value"] > best["search"]["fitness"]["value"]:
                    best = copy.deepcopy(record)
                    save(best, "best")
                    report(True, phase="validation", best=public(best))
                    best["validation"] = assessment(candidate_project, True)
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
            stop_reason="requested" if stop.is_set() else None,
            phase="done",
            episode_progress=0,
        )
    except InterruptedError:
        report(
            True,
            status="cancelled",
            phase="done",
            stop_reason="requested",
        )
    except Exception as exc:
        logging.exception("Evolution failed")
        report(True, status="failed", error=str(exc))
    finally:
        if pool is not None:
            pool.close()


def _worker(project, genes, options, stop, pipe, directory, job_id):
    def terminate(*_):
        stop.set()
        raise SystemExit()

    signal.signal(signal.SIGTERM, terminate)
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
        self.collector = None
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
                options.setdefault(
                    "neuron_fatigue_rate", project["world"]["config"]["neuron_fatigue_rate"]
                )
                project["world"]["config"]["neuron_fatigue_rate"] = options["neuron_fatigue_rate"]
            genes = genome.initial(project, options)
            with runtime.lock:
                if revision != runtime.revision:
                    raise Conflict(
                        "Проект изменён в другом окне. Данные обновлены; повторите действие."
                    )
                if runtime.world.config["neuron_fatigue_rate"] != options["neuron_fatigue_rate"]:
                    runtime.command(
                        "world_config",
                        {"neuron_fatigue_rate": options["neuron_fatigue_rate"]},
                        revision,
                    )
                revision = project["revision"] = runtime.revision
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
                daemon=False,
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
            self.collector = threading.Thread(
                target=self._collect, args=(self.process, read, job_id), daemon=True
            )
            self.collector.start()
            return self.snapshot()

    def close(self):
        if self.process is None or self.collector is None:
            return
        self.stop.set()
        # The collector alone reaps the coordinator. Concurrent Process.join()
        # calls can race in waitpid and report a reaped child as still alive.
        self.collector.join(timeout=5)
        if self.collector.is_alive():
            self.process.terminate()
            self.collector.join(timeout=4)
        if self.collector.is_alive():
            self.process.kill()
            self.collector.join(timeout=2)

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

    def clear_archive(self):
        from .runtime import Conflict

        with self.lock:
            if self.process is not None and self.process.is_alive():
                raise Conflict("Перед очисткой архива остановите эволюцию")
            for path in self.root.iterdir():
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            self.job = None
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
