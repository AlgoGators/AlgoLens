"""Runtime dependency composition for HTTP adapters."""

from werkzeug.security import check_password_hash, generate_password_hash

from algolens.application.runtime_control import RuntimeControlService
from algolens.application.configuration_inspection import ConfigurationInspectionService
from algolens.infrastructure.config.runtime_control import RuntimeControlConfig
from algolens.infrastructure.db.postgres import execute_query, get_db_connection
from algolens.infrastructure.identity.dev_config import EnvironmentDevAuthConfig
from algolens.infrastructure.identity.repositories import PostgresUserRepository
from algolens.infrastructure.identity.security import WerkzeugPasswordHasher
from algolens.infrastructure.identity.sessions import FlaskJwtSessionIssuer
from algolens.infrastructure.portfolio.market_data import PostgresMarketData
from algolens.infrastructure.portfolio.instrument_catalog import PostgresInstrumentCatalog
from algolens.infrastructure.portfolio.repositories import PostgresPortfolioRepository
from algolens.infrastructure.portfolio.runtime_control import PostgresRuntimeControlRepository
from algolens.infrastructure.portfolio.configuration_inspection import PostgresConfigurationInspectionReader
from algolens.infrastructure.portfolio.strategy_registry import PostgresStrategyRegistry
from algolens.application.portfolio.qt_workflow import QtWorkflowService
from algolens.application.portfolio.qt_decision_read import QtDecisionReadService
from algolens.infrastructure.portfolio.qt_workflow_repository import QtWorkflowRepository
from algolens.infrastructure.portfolio.qt_decision_read_repository import QtDecisionReadRepository, QtDecisionReadQueries
from algolens.infrastructure.portfolio.qt_workflow_runtime import (
    QtRuntimeEvidence, QtGovernedInputLoader, QtRuntimeAuthorization, QtRuntimeEvaluator)


def create_identity_dependencies(
    execute_query_func=None,
    connection_factory=None,
    verify_func=None,
    hash_func=None,
):
    users = PostgresUserRepository(
        execute_query_func=execute_query_func or execute_query,
        connection_factory=connection_factory or get_db_connection,
    )
    hasher = WerkzeugPasswordHasher(
        verify_func=verify_func or check_password_hash,
        hash_func=hash_func or generate_password_hash,
    )
    sessions = FlaskJwtSessionIssuer()
    return users, hasher, sessions


def create_portfolio_dependencies(connection_factory=None):
    registry = PostgresStrategyRegistry(connection_factory=connection_factory)
    reader = PostgresPortfolioRepository(connection_factory=connection_factory)
    return registry, reader


def create_market_data(connection_factory=None):
    """Prices and contract sizes, from the schemas data-ngin owns."""
    return PostgresMarketData(connection_factory=connection_factory)


def create_instrument_catalog(connection_factory=None):
    """Compose the read-only type lookup without opening a connection."""
    return PostgresInstrumentCatalog(connection_factory=connection_factory)


def create_dev_auth_config():
    return EnvironmentDevAuthConfig()


def create_runtime_control_service(connection_factory=None, environment=None):
    """Compose runtime policy and persistence without opening a connection."""
    return RuntimeControlService(
        PostgresRuntimeControlRepository(connection_factory=connection_factory),
        RuntimeControlConfig(environment),
    )


def create_configuration_inspection_service(connection_factory=None):
    return ConfigurationInspectionService(
        PostgresConfigurationInspectionReader(connection_factory=connection_factory)
    )


def create_qt_workflow_service(repository=None, *, connection_factory=None, evaluator_executable=None,
                               evaluator_bundle_directory=None, evidence=None, input_loader=None,
                               evaluator=None, authorization=None):
    """Compose actual persistence, source authority and sealed evaluator execution."""
    runtime_evidence = evidence if evidence is not None else QtRuntimeEvidence(
        evaluator_bundle_directory=evaluator_bundle_directory)
    factory = runtime_evidence._recompute_client_factory if isinstance(runtime_evidence, QtRuntimeEvidence) else None
    finalizer_factory = runtime_evidence._finalization_recompute_client_factory if isinstance(runtime_evidence, QtRuntimeEvidence) else None
    return QtWorkflowService(repository if repository is not None else QtWorkflowRepository(
        connection_factory, recompute_client_factory=factory, finalization_recompute_client_factory=finalizer_factory),
        evidence=runtime_evidence,
        input_loader=input_loader if input_loader is not None else QtGovernedInputLoader(),
        evaluator=evaluator if evaluator is not None else QtRuntimeEvaluator(
            evaluator_executable=evaluator_executable, evaluator_bundle_directory=evaluator_bundle_directory),
        authorization=authorization if authorization is not None else QtRuntimeAuthorization())


def create_qt_decision_read_service(repository=None, *, connection_factory=None, evaluator_bundle_directory=None,
                                  evidence=None, input_loader=None, authorization=None, queries=None):
    """Compose the read application without opening a database or evaluator."""
    evidence = evidence if evidence is not None else QtRuntimeEvidence(
        evaluator_bundle_directory=evaluator_bundle_directory)
    factory = evidence._recompute_client_factory if isinstance(evidence, QtRuntimeEvidence) else None
    finalizer_factory = evidence._finalization_recompute_client_factory if isinstance(evidence, QtRuntimeEvidence) else None
    repository = repository if repository is not None else QtDecisionReadRepository(
        connection_factory, recompute_client_factory=factory, finalization_recompute_client_factory=finalizer_factory)
    workflow = create_qt_workflow_service(repository, evaluator_bundle_directory=evaluator_bundle_directory,
        evidence=evidence, input_loader=input_loader, authorization=authorization)
    return QtDecisionReadService(repository, evidence=workflow.evidence, input_loader=workflow.input_loader,
        authorization=workflow.authorization, workflow=workflow,
        queries=queries if queries is not None else QtDecisionReadQueries(),
        evaluator_bundle_directory=workflow.evaluator_bundle_directory)


def create_qt_investor_publication_service(*, connection_factory=None, evaluator_bundle_directory=None):
    from algolens.application.portfolio.qt_investor_publication import QtInvestorPublicationService
    from algolens.infrastructure.portfolio.qt_investor_publication import QtInvestorPublicationRepository
    return QtInvestorPublicationService(create_qt_decision_read_service(
        connection_factory=connection_factory, evaluator_bundle_directory=evaluator_bundle_directory),
        QtInvestorPublicationRepository(connection_factory))
