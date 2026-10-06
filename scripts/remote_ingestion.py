"""Run the deployed worker locally, with runtime configuration retrieved over SSH.

Uses only the Python standard library. Secrets go through pipes and process
environment, never command arguments, generated env files, or launcher logs.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shlex
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
CONTAINER = "stockball-local-ingestion"
DRAIN_FILE = "/tmp/stockball-worker-drain"
LOCAL_PORTS = {"database": 15432, "redis": 16379, "engine": 13000, "api": 18000}


class LaunchError(RuntimeError):
    pass


def run(command, *, env=None, timeout=30):
    try:
        return subprocess.run(
            command, env=env, check=True, capture_output=True, text=True, timeout=timeout
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        # Subprocess output or exception text may contain production credentials.
        raise LaunchError(f"{command[0]} command failed; check connectivity and permissions") from None


def rewrite_url(value: str, port: int, schemes: tuple[str, ...], host="127.0.0.1") -> str:
    try:
        url = urlsplit(value)
        if url.scheme not in schemes or not url.hostname or url.fragment:
            raise ValueError
        # Preserve the encoded username/password verbatim, including encoded @/:.
        credentials = url.netloc.rsplit("@", 1)[0] + "@" if "@" in url.netloc else ""
        query = parse_qsl(url.query, keep_blank_values=True)
        # These libpq options override the host/port in the URL. Never allow them
        # to bypass the tunnel. Other connection options are preserved.
        if any(key.lower() in {"host", "hostaddr", "port", "service"} for key, _ in query):
            raise ValueError
        return urlunsplit((url.scheme, f"{credentials}{host}:{port}", url.path,
                           urlencode(query), ""))
    except (TypeError, ValueError):
        raise LaunchError("Unsupported production connection URL; refusing to start") from None


def validate_snapshot(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get("version") != 1:
        raise LaunchError("Unsupported production connection response")
    release = snapshot.get("release", "")
    image = snapshot.get("image", "")
    if not isinstance(release, str) or not re.fullmatch(r"[0-9a-f]{40}", release):
        raise LaunchError("Production has no valid deployed release")
    if not isinstance(image, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9/_.:-]*", image):
        raise LaunchError("Invalid deployed image")
    if not image.endswith(":" + release):
        raise LaunchError("Production worker does not match the successful release")
    ports = snapshot.get("ports", {})
    if not isinstance(ports, dict) or any(
        type(ports.get(key)) is not int or not 1 <= ports[key] <= 65535 for key in LOCAL_PORTS
    ):
        raise LaunchError("Invalid production tunnel ports")
    environment = snapshot.get("environment")
    if not isinstance(environment, dict) or not all(
        isinstance(key, str) and isinstance(value, str) and "\0" not in value
        and (re.fullmatch(r"STOCKBALL_[A-Z0-9_]+", key) or key == "TZ")
        for key, value in environment.items()
    ):
        raise LaunchError("Invalid production worker environment")
    for key in ("DATABASE_URL", "REDIS_URL", "TRADING_ENGINE_URL",
                "INGESTION_QUEUE_NAME", "INGESTION_RETRY_QUEUE_NAME"):
        if not environment.get("STOCKBALL_WORKER_" + key):
            raise LaunchError("Production configuration is incomplete; deploy the new release first")
    if (environment["STOCKBALL_WORKER_INGESTION_QUEUE_NAME"]
            == environment.get("STOCKBALL_WORKER_QUEUE_NAME")
            or environment["STOCKBALL_WORKER_INGESTION_RETRY_QUEUE_NAME"]
            == environment.get("STOCKBALL_WORKER_RETRY_QUEUE_NAME")):
        raise LaunchError("Production ingestion and trading queues must be distinct")
    return snapshot


def worker_environment(snapshot, local_ports, overrides, host="127.0.0.1"):
    environment = dict(snapshot["environment"])
    # Provider options can differ locally. Connections and routing always come
    # from production and are set last so local development settings cannot win.
    environment.update({key: value for key, value in overrides.items()
                        if key.startswith("STOCKBALL_") or key == "TZ"})
    source = snapshot["environment"]
    for suffix, service, schemes in (
        ("DATABASE_URL", "database", ("postgres", "postgresql")),
        ("REDIS_URL", "redis", ("redis", "rediss")),
        ("TRADING_ENGINE_URL", "engine", ("http", "https")),
    ):
        key = "STOCKBALL_WORKER_" + suffix
        environment[key] = rewrite_url(source[key], local_ports[service], schemes, host)
    environment["STOCKBALL_WORKER_API_URL"] = rewrite_url(
        source.get("STOCKBALL_WORKER_API_URL", "http://api:8000"), local_ports["api"],
        ("http", "https"), host,
    )
    environment["STOCKBALL_WORKER_QUEUE_NAME"] = source["STOCKBALL_WORKER_INGESTION_QUEUE_NAME"]
    environment["STOCKBALL_WORKER_RETRY_QUEUE_NAME"] = source[
        "STOCKBALL_WORKER_INGESTION_RETRY_QUEUE_NAME"
    ]
    environment["STOCKBALL_WORKER_DRAIN_FILE"] = DRAIN_FILE
    return environment


class Launcher:
    def __init__(self, args):
        self.args = args
        self.tunnel = None
        self.owns_worker = False
        self.ssh = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                    "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15",
                    "-o", "ServerAliveCountMax=3", "-o", "ControlMaster=no",
                    "-o", "ControlPath=none"]
        self.compose = ["docker", "compose", "--project-name", "stockball-local-ingestion",
                        "--env-file", os.devnull, "-f", str(ROOT / "compose.local-ingestion.yml")]

    def snapshot(self):
        helper = self.args.remote_dir.rstrip("/") + "/scripts/ingestion-connection.sh"
        output = run([*self.ssh, self.args.ssh_host, shlex.quote(helper)])
        try:
            return validate_snapshot(json.loads(output))
        except (ValueError, TypeError):
            raise LaunchError("Invalid production connection response") from None

    def state(self):
        containers = json.loads(run(["docker", "container", "ls", "--all", "--format", "json",
                                    "--filter", f"name=^/{CONTAINER}$"]) or "null")
        if not containers:
            return None
        # Read only state and our ownership label, never the secret environment.
        result = json.loads(run(["docker", "inspect", "--format",
                                 '{{json .State}}', CONTAINER]))
        role = run(["docker", "inspect", "--format",
                    '{{index .Config.Labels "com.stockball.role"}}', CONTAINER])
        if role != "remote-ingestion":
            raise LaunchError(f"Container name {CONTAINER} is already used by another application")
        return result

    def stop_worker(self, *, drain=True):
        if not self.owns_worker:
            return
        state = self.state()
        if state and state["Running"]:
            if drain:
                print("Finishing the current ingestion job before stopping…", flush=True)
                run(["docker", "exec", CONTAINER, "touch", DRAIN_FILE])
                deadline = time.monotonic() + self.args.drain_timeout
                while time.monotonic() < deadline:
                    state = self.state()
                    if not state or not state["Running"]:
                        break
                    time.sleep(1)
                else:
                    print("Drain timed out; stopping worker. Check interrupted jobs in admin.", flush=True)
            run(["docker", "stop", "--time", "10", CONTAINER], timeout=30)
        if state:
            run(["docker", "rm", CONTAINER])
        self.owns_worker = False

    def close_tunnel(self):
        if self.tunnel is not None:
            self.tunnel.terminate()
            try:
                self.tunnel.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.tunnel.kill()
                self.tunnel.wait()
            self.tunnel = None

    def open_tunnel(self, snapshot):
        command = [*self.ssh, "-NT", "-o", "ExitOnForwardFailure=yes"]
        for service, local_port in self.args.local_ports.items():
            command += ["-L", f"127.0.0.1:{local_port}:127.0.0.1:{snapshot['ports'][service]}"]
        self.tunnel = subprocess.Popen([*command, self.args.ssh_host], stdout=subprocess.DEVNULL)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.tunnel.poll() is not None:
                raise LaunchError("SSH tunnel failed; check SSH access and local port conflicts")
            try:
                for port in self.args.local_ports.values():
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        pass
            except OSError:
                time.sleep(0.2)
            else:
                # ExitOnForwardFailure must also have a chance to report a bind conflict.
                time.sleep(0.2)
                if self.tunnel.poll() is None:
                    return
        raise LaunchError("SSH tunnel did not become ready")

    def prepare(self, snapshot):
        network_mode, host = (
            ("bridge", "host.docker.internal") if sys.platform == "darwin"
            else ("host", "127.0.0.1")
        )
        environment = worker_environment(snapshot, self.args.local_ports, os.environ, host)
        process_env = {**os.environ, **environment, "LOCAL_INGESTION_IMAGE": snapshot["image"],
                       "LOCAL_INGESTION_NETWORK_MODE": network_mode,
                       "COMPOSE_PROFILES": ""}
        # -e KEY reads from subprocess environment; no credentials appear in argv.
        forwarded = [item for key in sorted(environment) for item in ("-e", key)]
        run([*self.compose, "pull", "ingestion-worker"], env=process_env, timeout=600)
        self.stop_worker()
        self.close_tunnel()
        self.open_tunnel(snapshot)
        preflight = """
import os
import sys
import httpx
import psycopg2
import redis
import socket
from urllib.parse import urlsplit
try:
    connection = psycopg2.connect(os.environ['STOCKBALL_WORKER_DATABASE_URL'], connect_timeout=5)
    connection.close()
    redis.Redis.from_url(os.environ['STOCKBALL_WORKER_REDIS_URL'],
                        socket_connect_timeout=5, socket_timeout=5).ping()
    engine = urlsplit(os.environ['STOCKBALL_WORKER_TRADING_ENGINE_URL'])
    with socket.create_connection((engine.hostname, engine.port), timeout=5):
        pass
    httpx.get(os.environ['STOCKBALL_WORKER_API_URL'] + '/healthz', timeout=5).raise_for_status()
except Exception:
    print('Production connectivity check failed. Check SSH and Docker networking.', file=sys.stderr)
    sys.exit(1)
"""
        try:
            run([*self.compose, "run", "--rm", "--no-deps", "-T", *forwarded,
                 "--entrypoint", "python", "ingestion-worker", "-c", preflight],
                env=process_env, timeout=90)
        except LaunchError:
            raise LaunchError("Connectivity check failed; verify Docker networking and OVH services") from None
        # Pulling an image can take minutes; don't start with superseded settings.
        if self.snapshot() != snapshot:
            raise LaunchError("Production changed during startup; retrying with the new release")
        if not self.args.check:
            self.owns_worker = True
            run([*self.compose, "run", "--detach", "--no-deps", "--name", CONTAINER,
                 *forwarded, "ingestion-worker"], env=process_env, timeout=90)
        print(f"{'Verified' if self.args.check else 'Started'} ingestion release {snapshot['release'][:12]}",
              flush=True)

    def watch(self):
        run(["docker", "info", "--format", "{{.ServerVersion}}"])
        state = self.state()
        if state:
            if self.args.check:
                raise LaunchError("Stop the existing ingestion container before running --check")
            self.owns_worker = True
            self.stop_worker(drain=False)  # stale container from an interrupted launcher
        current = None
        last_error = None
        try:
            while True:
                try:
                    snapshot = self.snapshot()
                    if self.tunnel is not None and self.tunnel.poll() is not None:
                        raise LaunchError("SSH disconnected; stopping ingestion until it reconnects")
                    state = self.state() if self.owns_worker else None
                    if snapshot != current or not state or not state["Running"]:
                        self.prepare(snapshot)
                        current = snapshot
                    last_error = None
                    if self.args.check:
                        return
                except LaunchError as error:
                    self.stop_worker(drain=self.tunnel is not None and self.tunnel.poll() is None)
                    self.close_tunnel()
                    current = None
                    if self.args.check:
                        raise
                    if str(error) != last_error:
                        print(f"Ingestion paused: {error}. Retrying in {self.args.poll_seconds}s.", flush=True)
                    last_error = str(error)
                time.sleep(self.args.poll_seconds)
        finally:
            try:
                self.stop_worker()
            finally:
                self.close_tunnel()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-host", default=os.getenv("STOCKBALL_OVH_SSH_HOST"),
                        help="SSH config alias or user@host (or STOCKBALL_OVH_SSH_HOST)")
    parser.add_argument("--remote-dir", default="/opt/stockball")
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--drain-timeout", type=int, default=900)
    parser.add_argument("--check", action="store_true", help="verify connections without consuming jobs")
    for service, port in LOCAL_PORTS.items():
        parser.add_argument(f"--{service}-port", type=int, default=port)
    args = parser.parse_args()
    if not args.ssh_host or args.ssh_host.startswith("-") or any(c.isspace() for c in args.ssh_host):
        parser.error("provide --ssh-host with an SSH alias or user@host")
    args.local_ports = {key: getattr(args, key + "_port") for key in LOCAL_PORTS}
    if (args.poll_seconds < 1 or args.drain_timeout < 1
            or any(not 1 <= port <= 65535 for port in args.local_ports.values())
            or len(set(args.local_ports.values())) != len(args.local_ports)):
        parser.error("intervals must be positive and tunnel ports must be valid and distinct")
    state_dir = Path.home() / ".local" / "state" / "stockball-ingestion"
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (state_dir / "launcher.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.exit(1, "Another local ingestion launcher is already running.\n")
        def interrupt(_signum, _frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, interrupt)
        try:
            Launcher(args).watch()
        except KeyboardInterrupt:
            print("Local ingestion stopped.", flush=True)
        except LaunchError as error:
            parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
