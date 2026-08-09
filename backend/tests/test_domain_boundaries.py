"""Import-boundary guards for the layer-first backend package."""

import ast
import os


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALGOLENS_DIR = os.path.join(BACKEND_DIR, "algolens")

DOMAIN_BANNED_ROOTS = {
    "database",
    "dotenv",
    "flask",
    "flask_jwt_extended",
    "os",
    "psycopg2",
    "routes",
    "services",
    "werkzeug",
}

APPLICATION_BANNED_ROOTS = DOMAIN_BANNED_ROOTS | {"extensions"}

ADAPTER_ALLOWED_INFRASTRUCTURE_IMPORTS = {
    "algolens.infrastructure.config.dependencies",
}


def _python_sources(layer):
    layer_dir = os.path.join(ALGOLENS_DIR, layer)
    for root, _dirs, files in os.walk(layer_dir):
        for filename in files:
            if filename.endswith(".py"):
                yield os.path.join(root, filename)


def _imports(path):
    with open(path, encoding="utf-8") as source:
        tree = ast.parse(source.read(), filename=path)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def _format_offender(path, imported):
    return f"{os.path.relpath(path, BACKEND_DIR)} imports {imported}"


def test_domain_has_no_framework_or_infrastructure_imports():
    offenders = []
    for path in _python_sources("domain"):
        for imported in _imports(path):
            root_name = imported.split(".", 1)[0]
            if (
                root_name in DOMAIN_BANNED_ROOTS
                or imported.startswith("algolens.infrastructure")
                or imported.startswith("algolens.adapters")
            ):
                offenders.append(_format_offender(path, imported))

    assert not offenders, (
        "Domain layer imports forbidden dependencies:\n  " + "\n  ".join(offenders)
    )


def test_application_does_not_depend_on_infrastructure_or_adapters():
    offenders = []
    for path in _python_sources("application"):
        for imported in _imports(path):
            root_name = imported.split(".", 1)[0]
            if (
                root_name in APPLICATION_BANNED_ROOTS
                or imported.startswith("algolens.infrastructure")
                or imported.startswith("algolens.adapters")
            ):
                offenders.append(_format_offender(path, imported))

    assert not offenders, (
        "Application layer imports forbidden dependencies:\n  "
        + "\n  ".join(offenders)
    )


def test_adapters_use_composition_instead_of_direct_infrastructure_imports():
    offenders = []
    for path in _python_sources("adapters"):
        for imported in _imports(path):
            root_name = imported.split(".", 1)[0]
            if root_name == "database":
                offenders.append(_format_offender(path, imported))
            elif imported.startswith("algolens.infrastructure") and not any(
                imported == allowed or imported.startswith(f"{allowed}.")
                for allowed in ADAPTER_ALLOWED_INFRASTRUCTURE_IMPORTS
            ):
                offenders.append(_format_offender(path, imported))

    assert not offenders, (
        "Adapters must use composition instead of direct infrastructure imports:\n  "
        + "\n  ".join(offenders)
    )
