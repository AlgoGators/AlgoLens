"""Bundle admission must compose with the existing bounded response transport."""
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path

import pytest

from algolens.infrastructure.portfolio.qt_evaluator_process import QtEvaluatorProcess, QtEvaluatorUnavailable
from algolens.infrastructure.portfolio.qt_evaluator_bundle import QtBundleLaunch, QtEvaluatorBundleUnavailable
from tests.test_qt_evaluator_process import REQUEST, PREFIX


def test_verified_bundle_launch_is_used_until_response_finishes(tmp_path, monkeypatch):
    import algolens.infrastructure.portfolio.qt_evaluator_bundle as bundles
    executable = tmp_path / "synthetic-evaluator"
    executable.write_text(PREFIX + "assert 'QT_SYNTHETIC_SENTINEL' not in os.environ\nprint(json.dumps(r))\n")
    executable.chmod(0o700)
    pin = sha256(executable.read_bytes()).hexdigest()
    state = []
    class Bundle:
        def __init__(self, *args):
            assert args == (tmp_path, "b" * 64, pin, "synthetic-build")
        @contextmanager
        def launch(self):
            state.append("open")
            try: yield QtBundleLaunch(("/usr/bin/unshare", "-Urn", "--", str(executable)), ())
            finally: state.append("closed")
    monkeypatch.setattr(bundles, "QtEvaluatorBundle", Bundle)
    monkeypatch.setenv("QT_SYNTHETIC_SENTINEL", "must-not-be-inherited")
    runner = QtEvaluatorProcess(executable, pin, "synthetic-build",
        bundle_directory=tmp_path, expected_bundle_sha256="b" * 64)
    assert runner.run(REQUEST) == REQUEST
    assert state == ["open", "closed"]


def test_bundle_failure_never_uses_direct_executable_fallback(tmp_path, monkeypatch):
    import algolens.infrastructure.portfolio.qt_evaluator_bundle as bundles
    marker = tmp_path / "launched"
    executable = tmp_path / "synthetic-evaluator"
    executable.write_text(PREFIX + f"open({str(marker)!r},'w').close()\nprint(json.dumps(r))\n")
    executable.chmod(0o700)
    class Refused:
        def __init__(self, *args): pass
        @contextmanager
        def launch(self):
            raise QtEvaluatorBundleUnavailable("evaluator_bundle_unavailable")
            yield
    monkeypatch.setattr(bundles, "QtEvaluatorBundle", Refused)
    runner = QtEvaluatorProcess(executable, sha256(executable.read_bytes()).hexdigest(), "synthetic-build",
        bundle_directory=tmp_path, expected_bundle_sha256="b" * 64)
    with pytest.raises(QtEvaluatorUnavailable, match="evaluator_bundle_unavailable"):
        runner.run(REQUEST)
    assert not marker.exists()


@pytest.mark.parametrize("directory,pin", [(None,"b"*64),(Path("relative"),"b"*64),(Path("/tmp/bundle"),None)])
def test_incomplete_bundle_configuration_is_rejected(directory, pin):
    with pytest.raises(ValueError):
        QtEvaluatorProcess(Path("/tmp/fixture"),"a"*64,"synthetic-build",
            bundle_directory=directory,expected_bundle_sha256=pin)
