#!/usr/bin/env python3
"""Resolve /Game package imports against the metadata-only VanillaPlus SQLite catalog.

This tool performs no asset loading. SQLite is opened with mode=ro and query_only.
Catalog hits establish indexed package-path presence only, not object presence/loadability.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            return json.loads(raw.decode(encoding))
        except UnicodeError:
            continue
    raise ValueError(f"Could not decode JSON as UTF-8 or UTF-16: {path}")


def package_path_from_game_reference(reference: str) -> str | None:
    normalized = reference.replace("\\", "/")
    if not normalized.startswith("/Game/"):
        return None
    relative = normalized[len("/Game/") :].strip("/")
    if not relative or any(part in (".", "..") for part in relative.split("/")):
        return None
    return f"Voyage/Content/{relative}"


def resolve(report: dict[str, Any], database: Path) -> dict[str, Any]:
    imports = report.get("Imports")
    if not isinstance(imports, list):
        raise ValueError("Input report has no Imports array")

    package_imports: list[tuple[int, dict[str, Any], str]] = []
    unresolved_references: list[dict[str, Any]] = []
    excluded_non_game_references: list[dict[str, Any]] = []
    for index, item in enumerate(imports):
        if not isinstance(item, dict) or item.get("ClassName") != "Package":
            continue
        reference = item.get("ObjectName")
        if not isinstance(reference, str):
            unresolved_references.append(
                {"import_index": index, "reference": reference, "catalog_status": "reference_unresolved", "reason": "package_import_object_name_not_a_string"}
            )
            continue
        package_base = package_path_from_game_reference(reference)
        if package_base is not None:
            package_imports.append((index, item, package_base))
        elif reference.replace("\\", "/").startswith("/Game/"):
            unresolved_references.append(
                {"import_index": index, "reference": reference, "catalog_status": "reference_unresolved", "reason": "invalid_or_ambiguous_game_package_path"}
            )
        else:
            excluded_non_game_references.append(
                {"import_index": index, "reference": reference, "catalog_status": "out_of_scope_non_game_package"}
            )

    database_uri = database.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(database_uri, uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        metadata = dict(
            connection.execute(
                "SELECT key,value FROM catalog_metadata "
                "WHERE key IN ('container_metadata_fingerprint','parser_version',"
                "'engine_profile','indexed_package_count','last_synced_utc')"
            )
        )
        results = []
        for import_index, item, package_base in package_imports:
            candidates: list[dict[str, Any]] = []
            for extension in (".uasset", ".umap"):
                candidate_path = package_base + extension
                rows = connection.execute(
                    "SELECT path,name,extension,size_bytes,is_encrypted "
                    "FROM asset_files WHERE path_key=? COLLATE NOCASE AND is_ue_package=1",
                    (candidate_path.casefold(),),
                ).fetchall()
                candidates.extend(
                    {
                        "path": row[0],
                        "name": row[1],
                        "extension": row[2],
                        "size_bytes": row[3],
                        "is_encrypted": bool(row[4]),
                    }
                    for row in rows
                )

            child_references = []
            expected_outer = -(import_index + 1)
            for child_index, child in enumerate(imports):
                if not isinstance(child, dict) or child.get("OuterIndex") != expected_outer:
                    continue
                child_path = child.get("ReferencePath")
                child_references.append(
                    {
                        "import_index": child_index,
                        "object_name": child.get("ObjectName"),
                        "reference": child_path,
                    }
                )

            results.append(
                {
                    "package_reference": item["ObjectName"],
                    "referencing_objects": child_references,
                    "package_path_candidates": [package_base + ".uasset", package_base + ".umap"],
                    "catalog_status": (
                        "package_not_found"
                        if not candidates
                        else "package_found"
                        if len(candidates) == 1
                        else "ambiguous"
                    ),
                    "match_method": "normalized_exact_path_key_case_insensitive",
                    "normalization": "/Game/<relative> -> Voyage/Content/<relative> + exact .uasset/.umap path_key lookup",
                    "match_count": len(candidates),
                    "matches": candidates,
                    "object_status": "not_verified",
                    "load_status": "not_tested",
                }
            )

        return {
            "tool": "resolve_external_dependencies",
            "tool_version": "1.0.1",
            "catalog_path": str(database.resolve()),
            "catalog_size_bytes": database.stat().st_size,
            "catalog_metadata": metadata,
            "source_format": report.get("Format", "unknown"),
            "source_hashes": {
                "uasset_sha256": report.get("UassetSHA256"),
                "uexp_sha256": report.get("UexpSHA256"),
            },
            "results": results,
            "unresolved_references": unresolved_references,
            "excluded_non_game_references": excluded_non_game_references,
            "limitations": [
                "A package_found result means only that an exact normalized path exists in this catalog snapshot.",
                "A package_not_found result is limited to this catalog snapshot and does not prove absence from the game.",
                "Object existence, package loading, class resolution, and engine/game compatibility are not tested.",
                "No asset payload is opened; the SQLite connection is read-only.",
            ],
        }
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="inspect_legacy_exports JSON report")
    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path(os.environ.get("LOCALAPPDATA", ""))
        / "VanillaPlus/CUE4Parse/catalogs/the-last-caretaker.sqlite",
        help="SQLite catalog path (opened read-only)",
    )
    parser.add_argument("--output", type=Path, help="write JSON output here; stdout if omitted")
    args = parser.parse_args()
    try:
        result = resolve(load_json(args.report), args.catalog)
    except (OSError, ValueError, sqlite3.Error) as error:
        print(f"resolve_external_dependencies: {error}", file=sys.stderr)
        return 2
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
