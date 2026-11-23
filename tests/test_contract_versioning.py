"""One contract, three generated artifacts, one version number.

`tests/test_contract_json_schema.py` and `tests/test_contract_typescript.py` already compare
the committed JSON Schema and the committed TypeScript with their generators. This file checks
the part neither of them can: that the long table, the JSON Schema and the TypeScript header
are rendered from the same `contract_schema()`, that they name `CONTRACT_VERSION`, and that a
change landing in one artifact only is reported rather than passing.

The repository-facing test reads the files *named* after `CONTRACT_VERSION`, so a bump without
regeneration fails on the missing file with the command that writes it, not on a bare
`FileNotFoundError`. `test_a_single_place_edit_is_reported` feeds the same checker synthetic
documents, one artifact at a time, and asserts it names the stale artifact — the failure this
checklist exists to prevent.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from islandos_core.app_view_models import CONTRACT_VERSION
from islandos_core.contract_schemas import (
    JSON_SCHEMA_PATH,
    SCHEMA_PATH,
    TS_PATH,
    contract_schema,
    json_schema,
)

LONG_FORM = "the long-form table"
JSON_SCHEMA = "the JSON Schema"
TYPESCRIPT = "the TypeScript header"

_TS_HEADER = re.compile(r"contract version (\d+)", re.IGNORECASE)
_JSON_SCHEMA_ID = re.compile(r"app_view_models\.v(\d+)\.schema\.json")

COMMANDS = {
    LONG_FORM: "python -m islandos_core.contract_schemas",
    JSON_SCHEMA: "python -m islandos_core.contract_schemas --json-schema",
}

# The two artifact families, so a missing file is reported against the set that should hold it.
_ARTIFACT_NAME = {
    LONG_FORM: re.compile(r"app_view_models\.v\d+\.json$"),
    JSON_SCHEMA: re.compile(r"app_view_models\.v\d+\.schema\.json$"),
}
_NEWER_ARTIFACT = re.compile(r"app_view_models\.v(\d+)(\.schema)?\.json$")


def _long_form_version(document: dict) -> int | None:
    value = document.get("contract_version")
    return value if isinstance(value, int) else None


def _json_schema_versions(document: dict) -> list[int]:
    """The version in `$id` plus one per object that pins `schema_version`."""
    versions: list[int] = []
    match = _JSON_SCHEMA_ID.search(str(document.get("$id", "")))
    if match:
        versions.append(int(match.group(1)))
    for body in (document.get("$defs") or {}).values():
        prop = ((body or {}).get("properties") or {}).get("schema_version")
        if isinstance(prop, dict) and isinstance(prop.get("const"), int):
            versions.append(prop["const"])
    return versions


def _typescript_version(text: str) -> int | None:
    match = _TS_HEADER.search("\n".join(text.splitlines()[:3]))
    return int(match.group(1)) if match else None


def version_mismatches(
    long_form: dict, json_schema_document: dict, typescript: str, expected: int
) -> list[str]:
    """Every artifact whose version disagrees with `expected`, as one readable sentence each."""
    problems: list[str] = []

    observed = _long_form_version(long_form)
    if observed != expected:
        problems.append(
            f"{LONG_FORM}: contract_version is {observed}, expected {expected}"
        )

    versions = sorted(set(_json_schema_versions(json_schema_document)))
    if versions != [expected]:
        described = ", ".join(str(version) for version in versions) or "no version stamp"
        problems.append(
            f"{JSON_SCHEMA}: $id and schema_version consts say {described}, expected {expected}"
        )

    observed = _typescript_version(typescript)
    if observed != expected:
        problems.append(
            f"{TYPESCRIPT}: contract version is {observed}, expected {expected}"
        )

    return problems


def _read_artifact(path: Path, label: str) -> dict:
    if not path.exists():
        pattern = _ARTIFACT_NAME.get(label)
        siblings = sorted(p.name for p in path.parent.glob("app_view_models.v*"))
        if pattern is not None:
            siblings = [name for name in siblings if pattern.match(name)]
        pytest.fail(
            f"{label}: {path.name} does not exist; docs/contracts holds "
            f"{', '.join(siblings) or 'no file of that kind'}. "
            f"A bumped CONTRACT_VERSION must be followed by {COMMANDS.get(label, 'regeneration')}."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _artifacts_newer_than_current(contracts_dir: Path, current: int) -> list[str]:
    """Files naming a version above the constant: a rolled-back bump leaves them behind."""
    newer: list[str] = []
    for candidate in sorted(contracts_dir.glob("app_view_models.v*")):
        match = _NEWER_ARTIFACT.search(candidate.name)
        if match and int(match.group(1)) > current:
            newer.append(candidate.name)
    return newer


def test_the_committed_artifacts_are_one_contract_at_one_version():
    long_form = _read_artifact(SCHEMA_PATH, LONG_FORM)
    json_document = _read_artifact(JSON_SCHEMA_PATH, JSON_SCHEMA)
    typescript = TS_PATH.read_text(encoding="utf-8")

    problems = version_mismatches(
        long_form, json_document, typescript, CONTRACT_VERSION
    )
    assert not problems, "\n".join(problems)

    schema = contract_schema()
    assert long_form == schema

    # The `$id` is the file's own name, so an artifact cannot claim one identity and sit under
    # another.
    assert json_document["$id"].endswith("/" + JSON_SCHEMA_PATH.name), json_document["$id"]

    # Both renderers read that same dict: the fields they emit are the fields declared there.
    assert json_schema()["$defs"]["run_request"]["required"] == [
        field["name"] for field in schema["contracts"]["run_request"]["fields"]
    ]
    for field in schema["contracts"]["run_result_summary"]["fields"]:
        assert f"  {field['name']}: " in typescript


def test_the_generated_paths_carry_the_constant_not_a_copy():
    assert SCHEMA_PATH.name == f"app_view_models.v{CONTRACT_VERSION}.json"
    assert JSON_SCHEMA_PATH.name == f"app_view_models.v{CONTRACT_VERSION}.schema.json"


def test_no_artifact_names_a_version_above_the_contract():
    """A bump that was regenerated and then rolled back leaves a file nothing points at."""
    newer = _artifacts_newer_than_current(SCHEMA_PATH.parent, CONTRACT_VERSION)
    assert not newer, (
        f"docs/contracts holds artifacts newer than CONTRACT_VERSION={CONTRACT_VERSION}: "
        f"{', '.join(newer)}. Rolling a bump back means deleting the files it wrote, or keeping "
        "the constant at the version those files name."
    )


@pytest.mark.parametrize("artifact", [LONG_FORM, JSON_SCHEMA, TYPESCRIPT])
def test_a_single_place_edit_is_reported(artifact):
    """Bump one artifact and leave the module alone: the gate fails and names it."""
    expected = CONTRACT_VERSION
    bumped = expected + 1
    long_form = {"contract_version": expected}
    json_document = {
        "$id": f"https://islandos.local/contracts/app_view_models.v{expected}.schema.json",
        "$defs": {
            "run_request": {
                "properties": {"schema_version": {"type": "integer", "const": expected}}
            }
        },
    }
    typescript = (
        "// Generated by `python -m islandos_core.contract_schemas --typescript`; "
        f"contract version {expected}.\n"
        "// Field names, types, units and owners come from `contract_schema()`; do not edit.\n"
    )

    if artifact == LONG_FORM:
        long_form = {"contract_version": bumped}
    elif artifact == JSON_SCHEMA:
        json_document = {
            **json_document,
            "$id": "https://islandos.local/contracts/"
            f"app_view_models.v{bumped}.schema.json",
        }
    else:
        typescript = typescript.replace(
            f"contract version {expected}", f"contract version {bumped}", 1
        )

    problems = version_mismatches(long_form, json_document, typescript, expected)
    assert len(problems) == 1, problems
    assert problems[0].startswith(artifact)
