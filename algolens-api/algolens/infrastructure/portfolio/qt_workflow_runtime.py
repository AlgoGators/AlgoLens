"""Infrastructure implementations of the QT source and evaluator ports."""
from pathlib import Path

from algolens.infrastructure.portfolio.qt_evaluation_inputs import load_qt_evaluation_inputs, canonical_qt_input_bytes
from algolens.infrastructure.portfolio.qt_evaluator_client import QtEvaluatorClient
from algolens.infrastructure.portfolio.qt_evaluator_process import QtEvaluatorProcess
from algolens.infrastructure.portfolio.qt_authorization import resolve_approved_person, two_person_quorum
from algolens.infrastructure.portfolio.qt_provenance import reconcile_qt_source
from algolens.infrastructure.portfolio.qt_read_set import capture_qt_read_set, canonical_internal_snapshot_bytes
from algolens.infrastructure.portfolio.qt_decision_report_proof import _prove_processed


class QtRuntimeEvidence:
    def __init__(self, *, evaluator_bundle_directory=None):
        self._bundle_directory = (Path(evaluator_bundle_directory)
            if evaluator_bundle_directory is not None else None)
        self._recompute_client_factory = (self._create_equity_recompute_client
            if self._bundle_directory is not None else None)
        self._finalization_recompute_client_factory = (self._create_equity_finalization_recompute_client
            if self._bundle_directory is not None else None)

    def _create_equity_recompute_client(self, authority):
        # Called only after the accounting proof binds these original pins to
        # the immutable preview. A payload never chooses the executable path.
        from algolens.infrastructure.portfolio.qt_equity_recompute_client import QtEquityRecomputeClient
        return QtEquityRecomputeClient(QtEvaluatorProcess(
            self._bundle_directory / 'bin/qt_evaluator', authority['evaluator_sha256'],
            authority['evaluator_build'], bundle_directory=self._bundle_directory,
            expected_bundle_sha256=authority['evaluator_bundle_sha256']))

    def _create_equity_finalization_recompute_client(self, authority):
        # Archived original S authority is proved before this factory. Only
        # server configuration chooses the retained directory, never a payload.
        from algolens.infrastructure.portfolio.qt_equity_finalization_recompute_client import QtEquityFinalizationRecomputeClient
        return QtEquityFinalizationRecomputeClient(QtEvaluatorProcess(
            self._bundle_directory / 'bin/qt_evaluator', authority['evaluator_sha256'],
            authority['evaluator_build'], bundle_directory=self._bundle_directory,
            expected_bundle_sha256=authority['evaluator_bundle_sha256']))

    def reconcile_source(self, *args, **observed):
        return reconcile_qt_source(*args, **observed,
            recompute_client_factory=self._recompute_client_factory,
            finalization_recompute_client_factory=self._finalization_recompute_client_factory)
    def capture_read_set(self, facts): return capture_qt_read_set(facts)
    def canonical_snapshot(self, kind, payload): return canonical_internal_snapshot_bytes(kind, payload)
    def input_bytes(self, payload): return canonical_qt_input_bytes(payload)
    def prove_report(self, evidence):
        return _prove_processed(evidence, recompute_client_factory=self._recompute_client_factory,
            finalization_recompute_client_factory=self._finalization_recompute_client_factory)


class QtGovernedInputLoader:
    def load(self, tx, **scope): return load_qt_evaluation_inputs(tx, **scope)


class QtRuntimeAuthorization:
    def resolve(self, actor_id, tx): return resolve_approved_person(actor_id, tx)
    def quorum(self, people): return two_person_quorum(people)


class QtRuntimeEvaluator:
    def __init__(self, *, evaluator_executable=None, evaluator_bundle_directory=None):
        self.bundle_directory = Path(evaluator_bundle_directory) if evaluator_bundle_directory is not None else None
        self.executable = self.bundle_directory / 'bin/qt_evaluator' if self.bundle_directory is not None else evaluator_executable

    def create_client(self, inputs):
        return QtEvaluatorClient(QtEvaluatorProcess(self.executable, inputs.evaluator_sha256, inputs.evaluator_build,
            bundle_directory=self.bundle_directory, expected_bundle_sha256=inputs.evaluator_bundle_sha256),
            allowed_override_codes=inputs.allowed_override_codes)
