"""Synthetic executable tests for bounded, isolated evaluator transport."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from algolens.infrastructure.portfolio.qt_evaluator_process import (
    QtEvaluatorProcess, QtEvaluatorUnavailable,
)


REQUEST = {"schema": "qt-eval/v1", "operation": "selected_book",
           "evaluator_build": "synthetic-build", "context_fingerprint": "a" * 64}
PREFIX = "#!/usr/bin/python3\nimport json,sys,os,time\nr=json.load(sys.stdin)\n"


def executable(tmp_path, body, **options):
    path = tmp_path / "synthetic-evaluator"
    path.write_text(PREFIX + body, encoding="utf-8")
    path.chmod(0o700)
    return QtEvaluatorProcess(path, hashlib.sha256(path.read_bytes()).hexdigest(),
                              "synthetic-build", **options)


def test_actual_child_has_only_loopback_no_routes_and_no_ambient_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_SYNTHETIC_SENTINEL", "must-not-be-inherited")
    runner = executable(tmp_path,
        "assert 'QT_SYNTHETIC_SENTINEL' not in os.environ\n"
        "assert not open('/proc/net/route').read().splitlines()[1:]\n"
        "r['child_executed']=True\nprint(json.dumps(r))\n")
    assert runner.run(REQUEST) == {**REQUEST, "child_executed": True}


@pytest.mark.parametrize("body", [
    "print('not json')\n", "print('{\"schema\":\"a\",\"schema\":\"b\"}')\n",
    "print(json.dumps(r)+'{}')\n", "print(json.dumps(r));sys.exit(7)\n",
    "sys.stderr.write('private evaluator failure');print(json.dumps(r))\n",
    "r['diagnostic']=float('nan');print(json.dumps(r))\n",
])
def test_bad_child_output_fails_without_leaking_details(tmp_path, body):
    with pytest.raises(QtEvaluatorUnavailable) as failure:
        executable(tmp_path, body).run(REQUEST)
    assert "private evaluator" not in str(failure.value)
    assert str(failure.value).startswith("evaluator_")


@pytest.mark.parametrize("field,value", [
    ("schema", "future-version"), ("operation", "draft_diagnostic"),
    ("evaluator_build", "another-build"), ("context_fingerprint", "b" * 64),
])
def test_response_identity_must_match_request(tmp_path, field, value):
    body = f"r[{field!r}]={value!r}\nprint(json.dumps(r))\n"
    with pytest.raises(QtEvaluatorUnavailable, match="evaluator_response_mismatch"):
        executable(tmp_path, body).run(REQUEST)


def test_timeout_is_bounded_and_child_is_reaped(tmp_path):
    pid_file = tmp_path / "child-pid"
    runner = executable(tmp_path,
                        f"open({str(pid_file)!r},'w').write(str(os.getpid()))\n"
                        "time.sleep(10)\n", timeout_seconds=0.2)
    with pytest.raises(QtEvaluatorUnavailable, match="evaluator_timeout"):
        runner.run(REQUEST)
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_output_overflow_is_bounded(tmp_path, stream):
    runner = executable(tmp_path, f"sys.{stream}.write('x'*1000000)\n",
                        max_output_bytes=512)
    with pytest.raises(QtEvaluatorUnavailable, match="evaluator_output_limit"):
        runner.run(REQUEST)


def test_changed_artifact_and_oversized_request_never_launch(tmp_path):
    marker = tmp_path / "launched"
    runner = executable(tmp_path, f"open({str(marker)!r},'w').close()\nprint(json.dumps(r))\n",
                        max_input_bytes=256)
    with pytest.raises(QtEvaluatorUnavailable, match="evaluator_input_limit"):
        runner.run({**REQUEST, "large": "x" * 512})
    assert not marker.exists()
    runner.executable.write_text(runner.executable.read_text() + "# changed\n")
    with pytest.raises(QtEvaluatorUnavailable, match="evaluator_artifact_changed"):
        runner.run(REQUEST)
    assert not marker.exists()


def test_missing_artifact_is_unavailable(tmp_path):
    runner = QtEvaluatorProcess(tmp_path / "missing", "0" * 64, "synthetic-build")
    with pytest.raises(QtEvaluatorUnavailable, match="evaluator_artifact_missing"):
        runner.run(REQUEST)


@pytest.mark.parametrize("options", [
    {"timeout_seconds": float("nan")}, {"timeout_seconds": 0},
    {"max_output_bytes": 0}, {"max_input_bytes": 8 * 1024 * 1024 + 1},
])
def test_resource_limits_cannot_be_disabled(tmp_path, options):
    with pytest.raises(ValueError, match="invalid_evaluator_process_configuration"):
        executable(tmp_path, "print(json.dumps(r))\n", **options)


def test_replacing_artifact_after_verification_cannot_change_executed_bytes(tmp_path, monkeypatch):
    import subprocess
    marker = tmp_path / "replaced-code-executed"
    runner = executable(tmp_path, "r['original_code']=True\nprint(json.dumps(r))\n")
    original_popen = subprocess.Popen

    def replace_then_spawn(*args, **kwargs):
        runner.executable.write_text(
            PREFIX + f"open({str(marker)!r},'w').close()\n"
            "r['original_code']=False\nprint(json.dumps(r))\n")
        return original_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", replace_then_spawn)
    assert runner.run(REQUEST)["original_code"] is True
    assert not marker.exists()
