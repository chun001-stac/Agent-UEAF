from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from jsonschema import validators
from referencing import Registry, Resource


def load_schema(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"schema root must be an object: {path}")
    return cast(dict[str, Any], raw)


def build_schema_registry(schema_root: Path) -> Registry[Any]:
    registry: Registry[Any] = Registry()
    for path in sorted(schema_root.rglob("*.schema.json")):
        schema = load_schema(path)
        uri = schema.get("$id")
        if not isinstance(uri, str) or not uri:
            raise ValueError(f"schema missing stable $id: {path}")
        registry = registry.with_resource(uri, Resource.from_contents(schema))
    return registry


def validate_instance(instance: Any, schema_path: Path, schema_root: Path) -> None:
    schema = load_schema(schema_path)
    validator_cls = validators.validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema, registry=build_schema_registry(schema_root))
    validator.validate(instance)
