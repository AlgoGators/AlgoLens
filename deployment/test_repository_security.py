"""Repository-level deployment hygiene contracts."""
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
FROM = re.compile(r"^FROM\s+([^\s]+)", re.MULTILINE)


def tracked_files():
    output = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    ).stdout
    return [ROOT / value.decode("utf-8") for value in output.split(b"\0") if value]


def test_every_container_base_is_pinned_to_an_immutable_digest():
    dockerfiles = [path for path in tracked_files() if path.name == "Dockerfile"]
    assert dockerfiles
    offenders = []
    for path in dockerfiles:
        for image in FROM.findall(path.read_text(encoding="utf-8")):
            if "@" not in image or not DIGEST.fullmatch(image.rsplit("@", 1)[1]):
                offenders.append(f"{path.relative_to(ROOT)}: {image}")
    assert offenders == []


def test_deployment_guidance_contains_no_literal_credentials_or_public_database_host():
    text = (ROOT / "deployment/DEPLOYMENT.md").read_text(encoding="utf-8")
    assignment = re.compile(r"^(DB_PASSWORD|JWT_SECRET_KEY)=([^\s#]+)$", re.MULTILINE)
    bad_assignments = [name for name, value in assignment.findall(text)
                       if not re.fullmatch(r"\$\{[A-Z][A-Z0-9_]+\}", value)]
    assert bad_assignments == []
    assert re.search(r"secret[\s-]+manager", text, re.IGNORECASE)

    active_guidance = [ROOT / "deployment/DEPLOYMENT.md",
                       ROOT / "algolens-api/scripts/production_readiness.sh"]
    public_ipv4 = []
    for path in active_guidance:
        for value in re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
                                path.read_text(encoding="utf-8")):
            if not value.startswith(("10.", "127.", "192.168.")):
                public_ipv4.append(f"{path.relative_to(ROOT)}: {value}")
    assert public_ipv4 == []


def test_active_code_and_configuration_contain_no_developer_home_paths():
    forbidden = ("/home/" + "devcontainers/", "/home/" + "john-riley/")
    active_suffixes = {".py", ".ts", ".tsx", ".js", ".sh", ".yml", ".yaml", ".toml"}
    offenders = []
    for path in tracked_files():
        if path == Path(__file__) or (path.suffix not in active_suffixes and path.name != "Dockerfile"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(value in text for value in forbidden):
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []


def test_historical_developer_paths_are_confined_to_non_executable_fixture_provenance():
    """Captured path strings are evidence only; digests, not paths, authenticate artifacts."""
    forbidden = ("/home/" + "devcontainers/", "/home/" + "john-riley/")
    allowed = {
        "algolens-api/tests/fixtures/configuration_inspection_cpp_controlled_v1.provenance.json",
        "algolens-frontend/src/infrastructure/api/__fixtures__/equityActionActual/manifest.json",
        "algolens-frontend/src/infrastructure/api/__fixtures__/equityModelFullRun/capture-pins.json",
        "algolens-frontend/src/infrastructure/api/__fixtures__/equityModelFullRun/manifest.json",
    }
    found = set()
    for path in tracked_files():
        if path.suffix != ".json":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(value in text for value in forbidden):
            relative = path.relative_to(ROOT).as_posix()
            found.add(relative)
            value = json.loads(text)
            assert "sha256" in text.lower(), f"{relative} lacks artifact digest evidence"
            assert isinstance(value, dict)
    assert found == allowed
