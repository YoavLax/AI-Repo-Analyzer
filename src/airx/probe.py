"""Deterministic repository fact extraction (plan.md §5.2, plan-v2-fable.md §3.4).

Facts are computed only from files named here, read defensively: an unreadable
or undecodable file is treated as absent. Everything returned is sorted, so the
facts — like every other pipeline stage — are a pure function of the tree.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from airx.fs import RepoTree

_MAKEFILE_TARGET_RE = re.compile(r"^([A-Za-z0-9_.-]+):(?!=)", re.MULTILINE)
_LANGUAGE_EXTENSIONS = frozenset({
    "py", "ts", "tsx", "js", "jsx", "go", "rs", "java", "kt", "rb", "cs",
    "cpp", "cc", "c", "h", "swift", "php", "scala", "sh", "sql",
})
_JS_TEST_CONFIGS = ("jest.config", "vitest.config")
_CI_FILES = (PurePosixPath(".gitlab-ci.yml"), PurePosixPath("Jenkinsfile"))
_LINT_HINTS = (
    ".eslintrc", "eslint.config", ".prettierrc", ".golangci.yml", "ruff.toml",
    ".flake8", "rustfmt.toml",
)
#: Matches "Dockerfile" itself plus common variant naming conventions
#: (Dockerfile.dev, Dockerfile-prod, backend.dockerfile, worker_Dockerfile),
#: not just the exact bare filename.
_DOCKERFILE_RE = re.compile(r"(?i)^dockerfile([._-].+)?$|^.+[._-]dockerfile$")

#: .NET test project naming convention (Foo.Tests.csproj, Foo.UnitTests.fsproj,
#: Foo.IntegrationTests.vbproj) \u2014 the de facto standard for locating test
#: projects in a .NET solution, since they are rarely named "tests"/"test".
_DOTNET_TEST_PROJECT_RE = re.compile(
    r"(?i)\.(?:unit|integration)?tests?\.(?:cs|vb|fs)proj$"
)


def _looks_like_dockerfile(name: str) -> bool:
    return _DOCKERFILE_RE.match(name) is not None


@dataclass(frozen=True)
class RepoFacts:
    languages: tuple[tuple[str, int], ...]
    package_scripts: tuple[str, ...]
    makefile_targets: tuple[str, ...]
    has_pytest: bool
    has_js_test_config: bool
    test_evidence: bool
    lint_evidence: bool
    build_evidence: bool
    ci_workflows: tuple[PurePosixPath, ...]
    gitignore_lines: tuple[str, ...]
    has_env_example: bool
    has_devcontainer: bool
    has_setup_script: bool
    version_pins: tuple[str, ...]


def _read_text(tree: RepoTree, rel: PurePosixPath) -> str | None:
    try:
        return (tree.root / str(rel)).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None


def probe(tree: RepoTree) -> RepoFacts:
    files = set(tree.files)
    names = {f.name for f in tree.files}

    # Languages: extension histogram, top 5, sorted by (-count, ext).
    counts: dict[str, int] = {}
    for f in tree.files:
        ext = f.suffix.lstrip(".").lower()
        if ext in _LANGUAGE_EXTENSIONS:
            counts[ext] = counts.get(ext, 0) + 1
    languages = tuple(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5])

    # package.json scripts.
    package_scripts: tuple[str, ...] = ()
    pkg_raw = _read_text(tree, PurePosixPath("package.json"))
    if pkg_raw is not None:
        try:
            pkg = json.loads(pkg_raw)
            scripts = pkg.get("scripts")
            if isinstance(scripts, dict):
                package_scripts = tuple(sorted(str(k) for k in scripts))
        except (json.JSONDecodeError, AttributeError):
            pass

    # Makefile targets.
    makefile_targets: tuple[str, ...] = ()
    mk_raw = _read_text(tree, PurePosixPath("Makefile"))
    if mk_raw is not None:
        makefile_targets = tuple(sorted(set(_MAKEFILE_TARGET_RE.findall(mk_raw))))

    pyproject_raw = _read_text(tree, PurePosixPath("pyproject.toml")) or ""

    has_pytest = (
        "pytest.ini" in names
        or "conftest.py" in names
        or "[tool.pytest" in pyproject_raw
    )
    has_js_test_config = any(n.startswith(_JS_TEST_CONFIGS) for n in names)
    # Non-Python/JS ecosystem test conventions: .NET test projects (e.g.
    # Foo.Tests.csproj), Go *_test.go files, and Maven/Gradle src/test/ layout.
    has_dotnet_test_project = any(_DOTNET_TEST_PROJECT_RE.search(n) for n in names)
    has_go_test_files = any(f.name.endswith("_test.go") for f in tree.files)
    has_maven_test_dir = any(
        "src" in f.parts and "test" in f.parts and f.parts.index("test") == f.parts.index("src") + 1
        for f in tree.files
    )
    has_tests_dir = (
        any(f.parts[0] in ("tests", "test") for f in tree.files)
        or has_dotnet_test_project
        or has_go_test_files
        or has_maven_test_dir
    )
    test_evidence = (
        has_pytest or has_js_test_config or has_tests_dir
        or "test" in package_scripts or "test" in makefile_targets
        or "tox.ini" in names
    )

    lint_evidence = (
        any(n.startswith(_LINT_HINTS) for n in names)
        or "[tool.ruff" in pyproject_raw
        or "lint" in package_scripts
        or "lint" in makefile_targets
    )
    build_evidence = (
        "build" in package_scripts
        or "build" in makefile_targets
        or "[build-system]" in pyproject_raw
        or "Cargo.toml" in names
        or "go.mod" in names
    )

    ci_workflows = tuple(sorted(
        (
            f for f in tree.files
            if (
                len(f.parts) == 3
                and f.parts[0] == ".github"
                and f.parts[1] == "workflows"
                and f.suffix in (".yml", ".yaml")
            )
            or f in _CI_FILES
            or (f.name.startswith("azure-pipelines") and f.suffix in (".yml", ".yaml"))
        ),
        key=lambda p: p.as_posix(),
    ))

    gitignore_lines: tuple[str, ...] = ()
    gi_raw = _read_text(tree, PurePosixPath(".gitignore"))
    if gi_raw is not None:
        gitignore_lines = tuple(
            line.strip() for line in gi_raw.splitlines()
            if line.strip() and not line.strip().startswith("#")
        )

    has_env_example = ".env.example" in names or ".env.template" in names
    has_devcontainer = any(_looks_like_dockerfile(n) for n in names) or any(
        f.parts[0] == ".devcontainer" for f in tree.files
    )
    has_setup_script = (
        "setup" in makefile_targets
        or has_devcontainer
        or any(
            f.parts[0] == "scripts" and (f.name.startswith("setup") or f.name.startswith("bootstrap"))
            for f in tree.files
        )
    )

    pins: list[str] = []
    for pin_file in (".nvmrc", ".tool-versions", ".python-version"):
        if PurePosixPath(pin_file) in files:
            pins.append(pin_file)
    if PurePosixPath("rust-toolchain.toml") in files:
        pins.append("rust-toolchain.toml")
    if "requires-python" in pyproject_raw:
        pins.append("pyproject.toml:requires-python")
    version_pins = tuple(sorted(pins))

    return RepoFacts(
        languages=languages,
        package_scripts=package_scripts,
        makefile_targets=makefile_targets,
        has_pytest=has_pytest,
        has_js_test_config=has_js_test_config,
        test_evidence=test_evidence,
        lint_evidence=lint_evidence,
        build_evidence=build_evidence,
        ci_workflows=ci_workflows,
        gitignore_lines=gitignore_lines,
        has_env_example=has_env_example,
        has_devcontainer=has_devcontainer,
        has_setup_script=has_setup_script,
        version_pins=version_pins,
    )
