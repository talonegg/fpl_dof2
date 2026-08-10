"""Generate TypeScript types from the JSON Schemas.

The types the app compiles against come from the same schemas the publisher validates against, so
the two cannot drift. Hand-written types would be a second, silent definition of the contract.

Deliberately a small generator rather than an npm dependency: the schemas use a narrow subset of
JSON Schema, and a code generator we can read in one sitting is worth more here than one that
handles every keyword.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fpl_dof.publish.contract import ARTEFACTS, Contract

HEADER = """// Generated from contracts/v{version}/*.schema.json — do not edit by hand.
// Regenerate with: fpl-dof publish
//
// These types are generated from the same schemas the publisher validates against, so the app
// cannot compile against a shape the pipeline does not produce.
"""


def _type_name(artefact: str) -> str:
    return "".join(part.capitalize() for part in artefact.split("_"))


def _render(schema: dict[str, Any], defs: dict[str, Any], indent: int = 0) -> str:
    pad = "  " * indent
    if "$ref" in schema:
        ref = str(schema["$ref"])
        return _type_name(ref.rsplit("/", 1)[-1])

    kind = schema.get("type")
    if isinstance(kind, list):
        parts = [_render({**schema, "type": single}, defs, indent) for single in kind]
        return " | ".join(dict.fromkeys(parts))

    if kind == "array":
        return f"{_render(schema.get('items', {}), defs, indent)}[]"

    if kind == "object":
        properties = schema.get("properties")
        if not properties:
            value = schema.get("additionalProperties")
            inner = _render(value, defs, indent) if isinstance(value, dict) else "unknown"
            return f"Record<string, {inner}>"
        required = set(schema.get("required", []))
        lines = ["{"]
        for name, subschema in properties.items():
            optional = "" if name in required else "?"
            description = subschema.get("description")
            if description:
                lines.append(f"{pad}  /** {description} */")
            lines.append(f"{pad}  {name}{optional}: {_render(subschema, defs, indent + 1)};")
        lines.append(f"{pad}}}")
        return "\n".join(lines)

    if "enum" in schema:
        return " | ".join(f'"{value}"' for value in schema["enum"])
    if "const" in schema:
        value = schema["const"]
        return str(value) if isinstance(value, int | float) else f'"{value}"'
    if kind == "integer" or kind == "number":
        return "number"
    if kind == "boolean":
        return "boolean"
    if kind == "string":
        return "string"
    if kind == "null":
        return "null"
    return "unknown"


def generate(contract: Contract) -> str:
    parts = [HEADER.format(version=contract.version)]
    parts.append(f"export const CONTRACT_VERSION = {contract.version};\n")

    emitted: set[str] = set()
    for artefact in ARTEFACTS:
        schema = contract.schema(artefact)
        defs = schema.get("$defs", {})
        for name, subschema in defs.items():
            type_name = _type_name(name)
            if type_name in emitted:
                continue
            emitted.add(type_name)
            description = subschema.get("description")
            if description:
                parts.append(f"/** {description} */")
            parts.append(f"export interface {type_name} {_render(subschema, defs)}\n")

        description = schema.get("description")
        if description:
            parts.append(f"/** {description} */")
        parts.append(f"export interface {_type_name(artefact)} {_render(schema, defs)}\n")

    return "\n".join(parts)


def write_types(contract: Contract, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(generate(contract), encoding="utf-8")
    return destination
