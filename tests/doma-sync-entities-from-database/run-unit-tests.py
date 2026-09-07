#!/usr/bin/env python3
"""Load every hyphenated Doma entity-sync unittest module deterministically."""
from __future__ import annotations

import argparse
import importlib.util
import sys
import unittest
from pathlib import Path


TEST_FILES = (
    "test-configure-codegen.py",
    "test-entity-merge.py",
    "test-generate-wrapper.py",
    "test-schema-snapshot.py",
    "test-security.py",
    "test-source-model.py",
)


def _suite(test_dir: Path) -> unittest.TestSuite:
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    for index, filename in enumerate(TEST_FILES):
        path = test_dir / filename
        if not path.is_file():
            raise RuntimeError("required test module is missing: " + filename)
        spec = importlib.util.spec_from_file_location(f"doma_sync_test_{index}", path)
        if spec is None or spec.loader is None:
            raise RuntimeError("test module cannot be loaded: " + filename)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        suite.addTests(loader.loadTestsFromModule(module))
    return suite


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-files", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    if args.list_files:
        print("\n".join(TEST_FILES))
        return 0
    sys.dont_write_bytecode = True
    try:
        suite = _suite(Path(__file__).resolve().parent)
    except (ImportError, OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
