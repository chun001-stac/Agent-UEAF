from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEST_ID_OWNER = ROOT / "docs/05-实施规范/04-V1验收与一致性测试规范.md"
TEST_ID_EXTENSION = ROOT / "docs/05-实施规范/08-V1-P0能力验收扩展.md"

DELEGATED_TEST_ID_RANGES = {
    "PRM": (1, 11),
    "ACT": (7, 17),
    "CTX": (1, 8),
    "RAG": (5, 16),
    "SEC": (6, 19),
    "EVAL": (4, 18),
}

ALLOWED_PREFIXES = (
    "CON",
    "RUN",
    "ADP",
    "PRM",
    "CTX",
    "ACT",
    "RAG",
    "SEC",
    "EVD",
    "EVAL",
    "REL",
    "EVO",
    "REP",
    "MUT",
    "OBJ",
    "STR",
    "ETH",
    "P0-SCH",
    "P0-PORT",
)
ID_PREFIX_PATTERN = "|".join(re.escape(prefix) for prefix in ALLOWED_PREFIXES)
FUNCTION_PREFIX_PATTERN = "|".join(
    re.escape(prefix.lower().replace("-", "_")) for prefix in ALLOWED_PREFIXES
)
TEST_ID_PATTERN = re.compile(rf"^(?:{ID_PREFIX_PATTERN})-\d{{3}}$")
FUNCTION_ID_PATTERN = re.compile(
    rf"^test_(?P<prefix>{FUNCTION_PREFIX_PATTERN})"
    r"_(?P<number>\d{3})(?:_|$)"
)
OWNER_HEADING_PATTERN = re.compile(
    rf"^###\s+(?P<test_id>(?:{ID_PREFIX_PATTERN})-\d{{3}})(?:\s|$)",
    re.MULTILINE,
)
OWNER_DELEGATION_PATTERN = re.compile(
    r"`(?P<prefix>PRM|ACT|CTX|RAG|SEC|EVAL)-"
    r"(?P<start>\d{3})\.\.(?P<end>\d{3})`\s+在 08 中"
)
EXTENSION_HEADING_PATTERN = re.compile(
    rf"^##\s+(?P<test_id>(?:{ID_PREFIX_PATTERN})-\d{{3}})(?:\s|$)",
    re.MULTILINE,
)

_ID_NODE_COUNTS: Counter[str] = Counter()
_FILE_NODE_COUNTS: Counter[str] = Counter()
_FILE_ID_COVERAGE: dict[str, set[str]] = defaultdict(set)


def _registered_test_ids() -> set[str]:
    owner_text = TEST_ID_OWNER.read_text(encoding="utf-8")
    owner_ids = [match.group("test_id") for match in OWNER_HEADING_PATTERN.finditer(owner_text)]
    delegation_matches = [
        (
            match.group("prefix"),
            (int(match.group("start")), int(match.group("end"))),
        )
        for match in OWNER_DELEGATION_PATTERN.finditer(owner_text)
    ]
    duplicate_delegations = sorted(
        prefix
        for prefix, count in Counter(prefix for prefix, _ in delegation_matches).items()
        if count > 1
    )
    if duplicate_delegations:
        raise pytest.UsageError(
            f"duplicate Test ID delegation ranges in {TEST_ID_OWNER}: {duplicate_delegations}"
        )
    owner_delegations = dict(delegation_matches)
    if owner_delegations != DELEGATED_TEST_ID_RANGES:
        raise pytest.UsageError(
            f"unexpected Test ID delegation ranges in {TEST_ID_OWNER}: {owner_delegations!r}"
        )

    delegated_ids = {
        f"{prefix}-{number:03d}"
        for prefix, (start, end) in DELEGATED_TEST_ID_RANGES.items()
        for number in range(start, end + 1)
    }
    extension_text = TEST_ID_EXTENSION.read_text(encoding="utf-8")
    extension_ids = [
        match.group("test_id")
        for match in EXTENSION_HEADING_PATTERN.finditer(extension_text)
        if match.group("test_id") in delegated_ids
    ]
    extension_counts = Counter(extension_ids)
    duplicate_extension_ids = sorted(
        test_id for test_id, count in extension_counts.items() if count > 1
    )
    missing_extension_ids = sorted(delegated_ids - set(extension_ids))
    if duplicate_extension_ids or missing_extension_ids:
        raise pytest.UsageError(
            f"delegated Test ID headings in {TEST_ID_EXTENSION} are not a complete "
            f"closed range: duplicates={duplicate_extension_ids}, "
            f"missing={missing_extension_ids}"
        )

    registered = [*owner_ids, *extension_ids]
    duplicates = sorted(test_id for test_id, count in Counter(registered).items() if count > 1)
    if duplicates:
        raise pytest.UsageError(
            f"duplicate Test ID headings across the Owner and delegated extension: {duplicates}"
        )

    registered_set = set(registered)
    numbers_by_prefix: dict[str, set[int]] = defaultdict(set)
    for test_id in registered_set:
        prefix, number = test_id.rsplit("-", 1)
        numbers_by_prefix[prefix].add(int(number))
    registered_prefixes = set(numbers_by_prefix)
    expected_prefixes = set(ALLOWED_PREFIXES)
    if registered_prefixes != expected_prefixes:
        raise pytest.UsageError(
            "Test ID registry families do not match the allowed closed set: "
            f"missing={sorted(expected_prefixes - registered_prefixes)}, "
            f"unexpected={sorted(registered_prefixes - expected_prefixes)}"
        )
    gaps: dict[str, list[int]] = {}
    for prefix, numbers in numbers_by_prefix.items():
        missing = sorted(set(range(1, max(numbers) + 1)) - numbers)
        if missing:
            gaps[prefix] = missing
    if gaps:
        raise pytest.UsageError(
            "Test ID registry contains numbering gaps across the Owner and delegated "
            f"extension: {gaps}"
        )
    return registered_set


def _function_test_id(item: pytest.Item) -> str | None:
    function_name = item.name.split("[", 1)[0]
    match = FUNCTION_ID_PATTERN.match(function_name)
    if match is None:
        return None
    prefix = match.group("prefix").upper().replace("_", "-")
    return f"{prefix}-{match.group('number')}"


def _marker_test_ids(item: pytest.Item) -> set[str]:
    test_ids: set[str] = set()
    for marker in item.iter_markers(name="test_id"):
        for value in marker.args:
            if not isinstance(value, str):
                raise pytest.UsageError(f"{item.nodeid}: test_id marker arguments must be strings")
            test_ids.add(value)
    return test_ids


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    del config
    registered_ids = _registered_test_ids()
    errors: list[str] = []
    _ID_NODE_COUNTS.clear()
    _FILE_NODE_COUNTS.clear()
    _FILE_ID_COVERAGE.clear()

    for item in items:
        test_ids = _marker_test_ids(item)
        inferred_id = _function_test_id(item)
        if inferred_id is not None:
            test_ids.add(inferred_id)

        if not test_ids:
            errors.append(f"{item.nodeid}: no UEAF Test ID mapping")
            continue

        invalid_ids = sorted(
            test_id for test_id in test_ids if not TEST_ID_PATTERN.fullmatch(test_id)
        )
        if invalid_ids:
            errors.append(f"{item.nodeid}: invalid UEAF Test IDs {invalid_ids}")
            continue

        unregistered_ids = sorted(test_ids - registered_ids)
        if unregistered_ids:
            errors.append(
                f"{item.nodeid}: Test IDs are not registered in {TEST_ID_OWNER}: {unregistered_ids}"
            )
            continue

        relative_file = item.path.resolve().relative_to(ROOT).as_posix()
        _FILE_NODE_COUNTS[relative_file] += 1
        _FILE_ID_COVERAGE[relative_file].update(test_ids)
        for test_id in sorted(test_ids):
            item.user_properties.append(("test_id", test_id))
            _ID_NODE_COUNTS[test_id] += 1

    if errors:
        detail = "\n".join(f"- {error}" for error in errors)
        raise pytest.UsageError(f"UEAF Test ID traceability failed:\n{detail}")


def pytest_terminal_summary(
    terminalreporter: Any,
    exitstatus: int,
    config: pytest.Config,
) -> None:
    del exitstatus, config
    terminalreporter.section("UEAF Test ID coverage")
    for relative_file in sorted(_FILE_ID_COVERAGE):
        ids = ", ".join(sorted(_FILE_ID_COVERAGE[relative_file]))
        node_count = _FILE_NODE_COUNTS[relative_file]
        terminalreporter.write_line(f"{relative_file}: {node_count} nodes -> {ids}")
    terminalreporter.write_line("Test ID node counts:")
    for test_id in sorted(_ID_NODE_COUNTS):
        terminalreporter.write_line(f"  {test_id}: {_ID_NODE_COUNTS[test_id]}")
