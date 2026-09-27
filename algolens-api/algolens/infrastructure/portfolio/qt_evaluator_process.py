"""Bounded local evaluator transport; evidence admission belongs to the client."""
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
from math import isfinite
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import tempfile
import time


class QtEvaluatorUnavailable(Exception):
    """A fixed safe reason, never evaluator stderr or request data."""


_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_BYTES = 8 * 1024 * 1024
_IDENTITY = ("schema", "operation", "evaluator_build", "context_fingerprint")


def _object(pairs):
    value = {}
    for name, item in pairs:
        if name in value:
            raise ValueError("duplicate_json_key")
        value[name] = item
    return value


def _reject_number(_value):
    # Engine diagnostics and financial values are strings; float tokens have
    # no meaning at this boundary, including JSON NaN/Infinity extensions.
    raise ValueError("numeric_token_not_supported")


@dataclass(frozen=True)
class QtEvaluatorProcess:
    """Invoke a pinned artifact with bounded pipes in a new network namespace.

    This validates transport and response identity only. Its result must pass
    the QtEvaluatorClient evidence/selection validator before preview admission.
    It never accepts a shell command or inherits application credentials.
    """

    executable: Path
    expected_sha256: str
    expected_build: str
    timeout_seconds: float = 15.0
    max_input_bytes: int = 8 * 1024 * 1024
    max_output_bytes: int = 8 * 1024 * 1024
    bundle_directory: Path | None = None
    expected_bundle_sha256: str | None = None

    def __post_init__(self):
        if (not isinstance(self.executable, Path) or not self.executable.is_absolute()
                or not isinstance(self.expected_sha256, str)
                or not _DIGEST.fullmatch(self.expected_sha256)
                or not isinstance(self.expected_build, str)
                or not self.expected_build or len(self.expected_build) > 256
                or isinstance(self.timeout_seconds, bool)
                or not isinstance(self.timeout_seconds, (int, float))
                or not isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 60
                or type(self.max_input_bytes) is not int
                or not 0 < self.max_input_bytes <= _MAX_BYTES
                or type(self.max_output_bytes) is not int
                or not 0 < self.max_output_bytes <= _MAX_BYTES):
            raise ValueError("invalid_evaluator_process_configuration")
        if self.bundle_directory is not None or self.expected_bundle_sha256 is not None:
            if (not isinstance(self.bundle_directory, Path) or not self.bundle_directory.is_absolute()
                    or not isinstance(self.expected_bundle_sha256, str)
                    or not _DIGEST.fullmatch(self.expected_bundle_sha256)):
                raise ValueError("invalid_evaluator_process_configuration")

    def run(self, request: Mapping[str, object]) -> dict[str, object]:
        try:
            if (not isinstance(request, Mapping) or request.get("schema") not in {"qt-eval/v1", "qt-eval-empty-owner/v2"}
                    or request.get("operation") not in {"selected_book", "draft_diagnostic"}
                    or request.get("evaluator_build") != self.expected_build
                    or not isinstance(request.get("context_fingerprint"), str)
                    or not _DIGEST.fullmatch(request["context_fingerprint"])):
                raise ValueError()
            encoded = json.dumps(dict(request), ensure_ascii=False, allow_nan=False,
                                 separators=(",", ":")).encode("utf-8", "strict")
            # Freeze the request before process creation, including its identity.
            frozen = json.loads(encoded, object_pairs_hook=_object,
                                parse_float=_reject_number, parse_constant=_reject_number)
        except (TypeError, ValueError, UnicodeError, RecursionError):
            raise QtEvaluatorUnavailable("evaluator_request_invalid") from None
        if len(encoded) > self.max_input_bytes:
            raise QtEvaluatorUnavailable("evaluator_input_limit")
        if (os.name != "posix" or not Path("/usr/bin/unshare").is_file()
                or not hasattr(os, "memfd_create")):
            raise QtEvaluatorUnavailable("evaluator_isolation_unavailable")
        try:
            with self._launch() as (argv, pass_fds):
                with tempfile.TemporaryDirectory(prefix="qt-evaluator-") as scratch:
                    process = subprocess.Popen(
                        argv,
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        env={"PATH": "/usr/bin:/bin", "TZ": "UTC", "PYTHON_DOTENV_DISABLED": "1"},
                        cwd=scratch, start_new_session=True, pass_fds=pass_fds,
                    )
                    output = self._exchange(process, encoded)
        except QtEvaluatorUnavailable:
            raise
        except OSError:
            raise QtEvaluatorUnavailable("evaluator_start_failed") from None
        try:
            result = json.loads(output.decode("utf-8", "strict"),
                                object_pairs_hook=_object,
                                parse_float=_reject_number, parse_constant=_reject_number)
            if not isinstance(result, dict):
                raise ValueError()
        except (ValueError, UnicodeError, RecursionError):
            raise QtEvaluatorUnavailable("evaluator_output_invalid") from None
        if any(result.get(name) != frozen[name] for name in _IDENTITY):
            raise QtEvaluatorUnavailable("evaluator_response_mismatch")
        return result

    @contextmanager
    def _launch(self):
        if self.bundle_directory is not None:
            from algolens.infrastructure.portfolio.qt_evaluator_bundle import (
                QtEvaluatorBundle, QtEvaluatorBundleUnavailable,
            )
            try:
                with QtEvaluatorBundle(self.bundle_directory, self.expected_bundle_sha256,
                        self.expected_sha256, self.expected_build).launch() as launch:
                    yield launch.argv, launch.pass_fds
            except QtEvaluatorBundleUnavailable:
                raise QtEvaluatorUnavailable("evaluator_bundle_unavailable") from None
        else:
            # Retained for isolated component fixtures. Workflow admission must
            # require a governed bundle pin before it constructs this process.
            with self._sealed_artifact() as artifact_fd:
                yield ["/usr/bin/unshare", "-Urn", "--", f"/proc/self/fd/{artifact_fd}"], (artifact_fd,)

    @contextmanager
    def _sealed_artifact(self):
        # Execute the exact verified bytes even if the deployment path is
        # replaced or its inode is overwritten between validation and spawn.
        import fcntl

        descriptor = None
        try:
            try:
                artifact = self.executable.resolve(strict=True)
                if not artifact.is_file() or not os.access(artifact, os.X_OK):
                    raise OSError()
                source = artifact.open("rb")
            except OSError:
                raise QtEvaluatorUnavailable("evaluator_artifact_missing") from None
            with source:
                descriptor = os.memfd_create("qt-evaluator", os.MFD_ALLOW_SEALING | os.MFD_CLOEXEC)
                digest = sha256()
                while chunk := source.read(65536):
                    digest.update(chunk)
                    remaining = memoryview(chunk)
                    while remaining:
                        written = os.write(descriptor, remaining)
                        remaining = remaining[written:]
            if digest.hexdigest() != self.expected_sha256:
                raise QtEvaluatorUnavailable("evaluator_artifact_changed")
            os.fchmod(descriptor, 0o500)
            fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS,
                        fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW |
                        fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL)
            yield descriptor
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def _exchange(self, process, encoded: bytes) -> bytes:
        deadline = time.monotonic() + self.timeout_seconds
        outputs = {"stdout": bytearray(), "stderr": bytearray()}
        sent = 0
        try:
            with selectors.DefaultSelector() as selector:
                for stream, events, name in (
                    (process.stdin, selectors.EVENT_WRITE, "stdin"),
                    (process.stdout, selectors.EVENT_READ, "stdout"),
                    (process.stderr, selectors.EVENT_READ, "stderr"),
                ):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, events, name)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise QtEvaluatorUnavailable("evaluator_timeout")
                    for key, _ in selector.select(min(remaining, 0.05)):
                        stream = key.fileobj
                        if key.data == "stdin":
                            try:
                                sent += os.write(stream.fileno(), encoded[sent:sent + 65536])
                            except BrokenPipeError:
                                sent = len(encoded)
                            if sent == len(encoded):
                                selector.unregister(stream)
                                stream.close()
                        else:
                            chunk = os.read(stream.fileno(), 65536)
                            if not chunk:
                                selector.unregister(stream)
                                stream.close()
                                continue
                            limit = (self.max_output_bytes if key.data == "stdout"
                                     else min(self.max_output_bytes, 8192))
                            if len(outputs[key.data]) + len(chunk) > limit:
                                raise QtEvaluatorUnavailable("evaluator_output_limit")
                            outputs[key.data].extend(chunk)
            try:
                code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise QtEvaluatorUnavailable("evaluator_timeout") from None
            if code != 0:
                raise QtEvaluatorUnavailable("evaluator_failed")
            if outputs["stderr"]:
                raise QtEvaluatorUnavailable("evaluator_stderr")
            return bytes(outputs["stdout"])
        finally:
            # Kill the entire owned group even if its leader exited while a
            # descendant retained pipes; no child may survive an aborted call.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            for stream in (process.stdin, process.stdout, process.stderr):
                if not stream.closed:
                    stream.close()
