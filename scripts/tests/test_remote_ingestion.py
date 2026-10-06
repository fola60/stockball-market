from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("remote_ingestion", ROOT / "scripts/remote_ingestion.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def snapshot():
    return {
        "version": 1,
        "release": "a" * 40,
        "image": "ghcr.io/example/stockball-worker:" + "a" * 40,
        "ports": {"database": 25432, "redis": 26379, "engine": 23000, "api": 28000},
        "environment": {
            "STOCKBALL_WORKER_DATABASE_URL": "postgresql://user:p%40ss%3Aword@postgres:5432/stockball?sslmode=prefer",
            "STOCKBALL_WORKER_REDIS_URL": "redis://:secret@redis:6379/2",
            "STOCKBALL_WORKER_TRADING_ENGINE_URL": "http://trading-engine:3000",
            "STOCKBALL_WORKER_QUEUE_NAME": "custom:trading",
            "STOCKBALL_WORKER_RETRY_QUEUE_NAME": "custom:trading:retry",
            "STOCKBALL_WORKER_INGESTION_QUEUE_NAME": "custom:ingestion",
            "STOCKBALL_WORKER_INGESTION_RETRY_QUEUE_NAME": "custom:ingestion:retry",
            "STOCKBALL_BET365_BROWSER_ENABLED": "false",
        },
    }


def args(**overrides):
    return argparse.Namespace(**{
        "ssh_host": "stockball-ovh", "remote_dir": "/opt/stockball", "check": False,
        "poll_seconds": 1, "drain_timeout": 1, "local_ports": launcher.LOCAL_PORTS,
        **overrides,
    })


class ConnectionTests(unittest.TestCase):
    def test_ingestion_cannot_share_the_trading_queue(self):
        config = snapshot()
        config["environment"]["STOCKBALL_WORKER_INGESTION_QUEUE_NAME"] = "custom:trading"
        with self.assertRaises(launcher.LaunchError):
            launcher.validate_snapshot(config)

    def test_credentials_database_query_and_redis_index_survive_rewriting(self):
        environment = launcher.worker_environment(snapshot(), launcher.LOCAL_PORTS, {})
        self.assertEqual(environment["STOCKBALL_WORKER_DATABASE_URL"],
                         "postgresql://user:p%40ss%3Aword@127.0.0.1:15432/stockball?sslmode=prefer")
        self.assertEqual(environment["STOCKBALL_WORKER_REDIS_URL"],
                         "redis://:secret@127.0.0.1:16379/2")

    def test_development_connections_and_trading_queue_cannot_override_production(self):
        environment = launcher.worker_environment(snapshot(), launcher.LOCAL_PORTS, {
            "STOCKBALL_WORKER_DATABASE_URL": "postgresql://localhost/development",
            "STOCKBALL_WORKER_QUEUE_NAME": "custom:trading",
            "STOCKBALL_WORKER_RETRY_QUEUE_NAME": "custom:trading:retry",
            "STOCKBALL_BET365_BROWSER_ENABLED": "true",
        })
        self.assertIn("/stockball", environment["STOCKBALL_WORKER_DATABASE_URL"])
        self.assertEqual(environment["STOCKBALL_WORKER_QUEUE_NAME"], "custom:ingestion")
        self.assertEqual(environment["STOCKBALL_WORKER_RETRY_QUEUE_NAME"], "custom:ingestion:retry")
        self.assertEqual(environment["STOCKBALL_BET365_BROWSER_ENABLED"], "true")

    def test_query_cannot_bypass_ssh(self):
        for query in ("host=other", "hostaddr=1.2.3.4", "port=9999", "service=other"):
            with self.subTest(query=query), self.assertRaises(launcher.LaunchError):
                launcher.rewrite_url("postgresql://user:secret@postgres/db?" + query,
                                     15432, ("postgresql",))

    def test_invalid_snapshot_fails_without_disclosing_credentials(self):
        changes = [
            {"version": 2}, {"image": "worker:latest"}, {"release": "not-a-sha"},
            {"ports": {}}, {"environment": {}},
            {"environment": {"LD_PRELOAD": "secret"}},
        ]
        for change in changes:
            with self.subTest(change=change):
                with self.assertRaises(launcher.LaunchError) as caught:
                    launcher.validate_snapshot({**snapshot(), **change})
                self.assertNotIn("secret", str(caught.exception))

    def test_subprocess_failures_are_redacted(self):
        with patch.object(launcher.subprocess, "run", side_effect=subprocess.CalledProcessError(
            1, ["ssh"], output="production-secret", stderr="production-secret"
        )), self.assertRaises(launcher.LaunchError) as caught:
            launcher.run(["ssh", "host"])
        self.assertNotIn("production-secret", str(caught.exception))


class LifecycleTests(unittest.TestCase):
    def test_macos_container_uses_desktop_gateway_for_all_tunnels(self):
        instance = launcher.Launcher(args())
        with patch.object(launcher.sys, "platform", "darwin"), \
                patch.object(launcher, "run", return_value="") as run, \
                patch.object(instance, "stop_worker"), patch.object(instance, "close_tunnel"), \
                patch.object(instance, "open_tunnel"), \
                patch.object(instance, "snapshot", return_value=snapshot()):
            instance.prepare(snapshot())
        environment = run.call_args_list[-1].kwargs["env"]
        self.assertEqual(environment["LOCAL_INGESTION_NETWORK_MODE"], "bridge")
        for key in ("DATABASE_URL", "REDIS_URL", "TRADING_ENGINE_URL", "API_URL"):
            self.assertEqual(launcher.urlsplit(environment["STOCKBALL_WORKER_" + key]).hostname,
                             "host.docker.internal")

    def test_prepare_passes_secrets_by_environment_and_drains_before_replacing_tunnel(self):
        instance = launcher.Launcher(args())
        order = []
        with patch.object(launcher, "run", return_value="") as run, \
                patch.object(instance, "stop_worker", side_effect=lambda: order.append("drain")), \
                patch.object(instance, "close_tunnel", side_effect=lambda: order.append("close")), \
                patch.object(instance, "open_tunnel", side_effect=lambda _: order.append("open")), \
                patch.object(instance, "snapshot", return_value=snapshot()), \
                patch.dict(os.environ, {}, clear=True):
            instance.prepare(snapshot())
        self.assertEqual(order, ["drain", "close", "open"])
        command = run.call_args_list[-1].args[0]
        self.assertIn("--detach", command)
        self.assertIn("STOCKBALL_WORKER_DATABASE_URL", command)
        self.assertNotIn("secret", " ".join(command))
        self.assertNotIn("p%40ss", " ".join(command))
        self.assertIn("p%40ss", run.call_args_list[-1].kwargs["env"]["STOCKBALL_WORKER_DATABASE_URL"])

    def test_check_never_starts_a_consumer(self):
        instance = launcher.Launcher(args(check=True))
        with patch.object(launcher, "run", return_value="") as run, \
                patch.object(instance, "stop_worker"), patch.object(instance, "close_tunnel"), \
                patch.object(instance, "open_tunnel"), \
                patch.object(instance, "snapshot", return_value=snapshot()):
            instance.prepare(snapshot())
        self.assertFalse(instance.owns_worker)
        self.assertFalse(any("--detach" in call.args[0] for call in run.call_args_list))

    def test_release_changed_during_pull_cannot_start(self):
        instance = launcher.Launcher(args())
        changed = copy.deepcopy(snapshot())
        changed["release"] = "b" * 40
        with patch.object(launcher, "run", return_value="") as run, \
                patch.object(instance, "stop_worker"), patch.object(instance, "close_tunnel"), \
                patch.object(instance, "open_tunnel"), \
                patch.object(instance, "snapshot", return_value=changed), \
                self.assertRaises(launcher.LaunchError):
            instance.prepare(snapshot())
        self.assertFalse(any("--detach" in call.args[0] for call in run.call_args_list))

    def test_ssh_failure_stops_worker_and_closes_tunnel(self):
        instance = launcher.Launcher(args())
        instance.tunnel = MagicMock()
        instance.tunnel.poll.return_value = None
        with patch.object(launcher, "run", return_value=""), \
                patch.object(instance, "state", return_value=None), \
                patch.object(instance, "snapshot", side_effect=launcher.LaunchError("SSH failed")), \
                patch.object(instance, "stop_worker") as stop, \
                patch.object(instance, "close_tunnel") as close, \
                patch.object(launcher.time, "sleep", side_effect=KeyboardInterrupt), \
                self.assertRaises(KeyboardInterrupt):
            instance.watch()
        stop.assert_any_call(drain=True)
        close.assert_called()


class RemoteHelperTests(unittest.TestCase):
    """Exercise the real remote shell helper with a simulated Docker CLI."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name) / "project with spaces"
        (root / "scripts").mkdir(parents=True)
        self.helper = root / "scripts/ingestion-connection.sh"
        shutil.copy(ROOT / "scripts/ingestion-connection.sh", self.helper)
        (root / ".current-release").write_text("a" * 40 + "\n")
        binaries = root / "bin"
        binaries.mkdir()
        fake_docker = binaries / "docker"
        fake_docker.write_text(f"#!{sys.executable}\n" + '''
import json
import os
import subprocess
import sys
args = sys.argv[1:]
if args[0] == "compose":
    if "ps" in args:
        print("worker-container")
    elif "port" in args:
        service = args[args.index("port") + 1]
        ports = {"postgres": 25432, "redis": 26379, "trading-engine": 23000, "api": 28000}
        print(os.environ.get("TEST_BIND", "127.0.0.1") + ":" + str(ports[service]))
    else:
        sys.exit(2)
elif args[0] == "inspect":
    print(os.environ["TEST_IMAGE"])
elif args[0] == "exec":
    environment = {**os.environ, **json.loads(os.environ["TEST_ENV"]), "UNRELATED_SECRET": "hidden"}
    sys.exit(subprocess.call([sys.executable, *args[args.index("python") + 1:]], env=environment))
else:
    sys.exit(2)
''')
        fake_docker.chmod(0o755)
        fake_flock = binaries / "flock"
        fake_flock.write_text('#!/bin/sh\nexit "${TEST_FLOCK_EXIT:-0}"\n')
        fake_flock.chmod(0o755)
        self.environment = {
            "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
            "TEST_IMAGE": snapshot()["image"],
            "TEST_ENV": json.dumps(snapshot()["environment"]),
        }

    def execute(self, **overrides):
        return subprocess.run(["bash", str(self.helper)], env={**self.environment, **overrides},
                              capture_output=True, text=True, timeout=15)

    def test_reads_live_environment_and_actual_loopback_ports(self):
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        config = launcher.validate_snapshot(json.loads(result.stdout))
        self.assertEqual(config, snapshot())
        self.assertNotIn("UNRELATED_SECRET", result.stdout)

    def test_busy_deployment_returns_no_settings(self):
        result = self.execute(TEST_FLOCK_EXIT="1")
        self.assertEqual(result.returncode, 75)
        self.assertEqual(result.stdout, "")

    def test_unpromoted_image_returns_no_settings(self):
        result = self.execute(TEST_IMAGE="worker:" + "b" * 40)
        self.assertEqual(result.returncode, 75)
        self.assertEqual(result.stdout, "")

    def test_non_loopback_binding_is_rejected(self):
        result = self.execute(TEST_BIND="0.0.0.0")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


@unittest.skipUnless(shutil.which("docker"), "Docker Compose is needed to validate deployment roles")
class ComposeTests(unittest.TestCase):
    def config(self, files, profile=None):
        environment = {**os.environ, "POSTGRES_PASSWORD": "validation-only",
                       "IMAGE_TAG": "validation-only", "DOMAIN": "example.com",
                       "LOCAL_INGESTION_IMAGE": "worker:validation-only", "COMPOSE_PROFILES": ""}
        command = ["docker", "compose", "--env-file", os.devnull]
        if profile:
            command += ["--profile", profile]
        for name in files:
            command += ["-f", str(ROOT / name)]
        return json.loads(subprocess.check_output([*command, "config", "--format", "json"],
                                                 env=environment))

    def test_production_runs_scheduler_and_trading_but_not_ingestion(self):
        config = self.config(["docker-compose.yml", "compose.prod.yml"], "server")
        services = config["services"]
        self.assertIn("scheduler", services)
        self.assertIn("worker", services)
        self.assertNotIn("ingestion-worker", services)
        for name in ("postgres", "redis", "trading-engine"):
            self.assertEqual(services[name]["ports"][0]["host_ip"], "127.0.0.1")

    def test_development_worker_profile_still_runs_both_workers(self):
        config = self.config(["docker-compose.yml", "compose.dev.yml"], "worker")
        self.assertIn("worker", config["services"])
        self.assertIn("ingestion-worker", config["services"])

    def test_local_configuration_has_no_server_dependencies(self):
        config = self.config(["compose.local-ingestion.yml"])
        self.assertEqual(set(config["services"]), {"ingestion-worker"})
        worker = config["services"]["ingestion-worker"]
        self.assertEqual(worker["network_mode"], "host")
        self.assertEqual(worker["restart"], "no")
        self.assertNotIn("depends_on", worker)


if __name__ == "__main__":
    unittest.main()
