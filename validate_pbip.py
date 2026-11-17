"""
validate_pbip.py - validates every JSON file of the generated PBIP against the official Microsoft
JSON schemas (github.com/microsoft/json-schemas, folder fabric/) and lints the TMDL files.

Usage:  python validate_pbip.py --pbip pbip --schemas <path to json-schemas repo root>
The schema repo is downloaded automatically into <scratch>/json-schemas-main when --schemas is omitted.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

from jsonschema import Draft7Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

BASE = "https://developer.microsoft.com/json-schemas/"


def get_schema_repo(path: str | None, cache: Path) -> Path:
    if path:
        return Path(path)
    dst = cache / "json-schemas-main"
    if not dst.exists():
        print("downloading microsoft/json-schemas ...")
        data = urllib.request.urlopen("https://github.com/microsoft/json-schemas/archive/refs/heads/main.zip", timeout=120).read()
        zipfile.ZipFile(io.BytesIO(data)).extractall(cache)
    return dst


def make_registry(repo: Path) -> Registry:
    def retrieve(uri: str):
        if not uri.startswith(BASE):
            raise LookupError(uri)
        rel = uri[len(BASE):].split("#")[0]
        p = repo / rel
        if not p.exists():
            raise LookupError(f"schema not in repo: {rel}")
        return Resource.from_contents(json.loads(p.read_text(encoding="utf-8")), default_specification=DRAFT7)
    return Registry(retrieve=retrieve)


def validate_json(pbip: Path, repo: Path) -> int:
    reg = make_registry(repo)
    errors = 0
    files = sorted(p for p in pbip.rglob("*") if p.suffix in (".json", ".pbip", ".pbir", ".pbism", ".platform") or p.name == ".platform")
    for f in files:
        if "StaticResources" in f.parts:
            continue  # theme files have their own (report theme) schema, not part of the PBIR set
        if f.name in ("localSettings.json", "cache.abf", "unappliedChanges.json"):
            continue  # written by Power BI Desktop for this machine only; git-ignored and not part of the definition
        try:
            doc = json.loads(f.read_text(encoding="utf-8-sig"))
        except Exception as e:  # noqa: BLE001
            print(f"[JSON ERROR] {f}: {e}")
            errors += 1
            continue
        uri = doc.get("$schema")
        if not uri:
            print(f"[SKIP no $schema] {f.relative_to(pbip)}")
            continue
        try:
            schema = reg.get_or_retrieve(uri).value.contents
        except Exception as e:  # noqa: BLE001
            print(f"[SCHEMA MISSING] {f.relative_to(pbip)} -> {uri}: {e}")
            errors += 1
            continue
        v = Draft7Validator(schema, registry=reg)
        errs = sorted(v.iter_errors(doc), key=lambda e: list(e.path))
        if errs:
            errors += len(errs)
            print(f"[INVALID] {f.relative_to(pbip)}  ({uri.split('/json-schemas/')[1]})")
            for e in errs[:8]:
                print(f"    at {'/'.join(map(str, e.path)) or '<root>'}: {e.message[:300]}")
        else:
            print(f"[ok] {f.relative_to(pbip)}  <- {uri.split('/fabric/')[1]}")
    return errors


def lint_tmdl(pbip: Path) -> int:
    errors = 0
    decl = re.compile(r"^\s*(table|column|measure|partition|relationship|expression|model|database|hierarchy|level|role|cultureInfo|calculationGroup|calculationItem|annotation|extendedProperty|ref)\b")
    expr_names, table_names = set(), set()
    for f in sorted(pbip.rglob("*.tmdl")):
        lines = f.read_text(encoding="utf-8").splitlines()
        if f.read_bytes().startswith(b"\xef\xbb\xbf"):
            print(f"[TMDL] {f.name}: has UTF-8 BOM"); errors += 1
        for i, line in enumerate(lines):
            lead = re.match(r"^[ \t]*", line).group(0)
            if " " in lead and "\t" in lead or (lead and " " in lead and not line.strip().startswith(("//", "in", "let", "Source", "Headers", "Typed", "}", "{"))):
                # allow spaces only inside expression bodies (which sit after a tab prefix)
                if not lead.startswith("\t"):
                    print(f"[TMDL] {f.name}:{i+1}: indentation uses spaces"); errors += 1
            if line.strip().startswith("///"):
                nxt = lines[i + 1] if i + 1 < len(lines) else ""
                if not (nxt.strip().startswith("///") or decl.match(nxt)):
                    print(f"[TMDL] {f.name}:{i+1}: '///' description not followed by a declaration"); errors += 1
            m = re.match(r"^expression\s+('([^']+)'|(\S+))", line)
            if m:
                expr_names.add(m.group(2) or m.group(3))
            m = re.match(r"^table\s+('([^']+)'|(\S+))", line)
            if m:
                table_names.add(m.group(2) or m.group(3))
        print(f"[ok] {f.relative_to(pbip)}  ({len(lines)} lines)")
    clash = expr_names & table_names
    if clash:
        print(f"[TMDL] expression/table name clash: {clash}"); errors += 1
    return errors


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbip", default="pbip")
    ap.add_argument("--schemas", default=None)
    ap.add_argument("--cache", default=str(Path(__file__).resolve().parent / "assets" / "schema-cache"))
    a = ap.parse_args()
    pbip = Path(a.pbip)
    repo = get_schema_repo(a.schemas, Path(a.cache))
    print(f"== JSON schema validation ({repo})")
    e1 = validate_json(pbip, repo)
    print("\n== TMDL lint")
    e2 = lint_tmdl(pbip)
    print(f"\nJSON schema errors: {e1}; TMDL lint errors: {e2}")
    sys.exit(1 if (e1 or e2) else 0)


if __name__ == "__main__":
    main()
