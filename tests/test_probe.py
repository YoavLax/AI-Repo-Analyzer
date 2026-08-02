"""RepoFacts probe tests."""
import json
from pathlib import Path, PurePosixPath

from airx import fs
from airx.probe import probe


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _facts(root: Path):
    return probe(fs.scan(root))


def test_package_scripts_and_makefile_targets(tmp_path: Path) -> None:
    _write(tmp_path, "package.json", json.dumps({"scripts": {"test": "vitest", "build": "tsc", "lint": "eslint ."}}))
    _write(tmp_path, "Makefile", "setup:\n\tpip install -e .\n\nlint:\n\truff check .\n")
    facts = _facts(tmp_path)
    assert facts.package_scripts == ("build", "lint", "test")
    assert facts.makefile_targets == ("lint", "setup")
    assert facts.test_evidence is True
    assert facts.lint_evidence is True
    assert facts.build_evidence is True
    assert facts.has_setup_script is True


def test_pytest_and_ci_detection(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", "[tool.pytest.ini_options]\ntestpaths=['tests']\n[build-system]\nrequires=['setuptools']\n")
    _write(tmp_path, "tests/test_x.py", "def test_x(): pass\n")
    _write(tmp_path, ".github/workflows/ci.yml", "on: push\n")
    facts = _facts(tmp_path)
    assert facts.has_pytest is True
    assert facts.test_evidence is True
    assert facts.build_evidence is True
    assert facts.ci_workflows == (PurePosixPath(".github/workflows/ci.yml"),)


def test_hygiene_and_pins(tmp_path: Path) -> None:
    _write(tmp_path, ".gitignore", "# comment\n.env\nnode_modules\n")
    _write(tmp_path, ".env.example", "TOKEN=\n")
    _write(tmp_path, ".nvmrc", "20\n")
    _write(tmp_path, "Dockerfile", "FROM python:3.12\n")
    facts = _facts(tmp_path)
    assert ".env" in facts.gitignore_lines
    assert "# comment" not in facts.gitignore_lines
    assert facts.has_env_example is True
    assert facts.has_devcontainer is True
    assert ".nvmrc" in facts.version_pins


def test_languages_histogram_sorted(tmp_path: Path) -> None:
    for i in range(3):
        _write(tmp_path, f"src/m{i}.py", "x = 1\n")
    _write(tmp_path, "src/app.ts", "const x = 1\n")
    facts = _facts(tmp_path)
    assert facts.languages[0] == ("py", 3)
    assert ("ts", 1) in facts.languages


def test_devcontainer_detects_dockerfile_naming_variants(tmp_path: Path) -> None:
    _write(tmp_path, "Dockerfile-varonis-forwarder", "FROM alpine\n")
    facts = _facts(tmp_path)
    assert facts.has_devcontainer is True


def test_devcontainer_false_for_unrelated_file_containing_docker(tmp_path: Path) -> None:
    _write(tmp_path, "docker-compose.yml", "services: {}\n")
    facts = _facts(tmp_path)
    assert facts.has_devcontainer is False


def test_test_evidence_detects_dotnet_test_project(tmp_path: Path) -> None:
    _write(tmp_path, "MessageTraceConsoleApp.Tests/MessageTraceConsoleApp.Tests.csproj", "<Project />\n")
    facts = _facts(tmp_path)
    assert facts.test_evidence is True


def test_test_evidence_detects_go_test_files(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/handler_test.go", "package pkg\n")
    facts = _facts(tmp_path)
    assert facts.test_evidence is True


def test_test_evidence_detects_maven_test_layout(tmp_path: Path) -> None:
    _write(tmp_path, "src/test/java/com/example/FooTest.java", "class FooTest {}\n")
    facts = _facts(tmp_path)
    assert facts.test_evidence is True


def test_empty_repo_has_empty_facts(tmp_path: Path) -> None:
    facts = _facts(tmp_path)
    assert facts.package_scripts == ()
    assert facts.test_evidence is False
    assert facts.ci_workflows == ()
    assert facts.version_pins == ()
