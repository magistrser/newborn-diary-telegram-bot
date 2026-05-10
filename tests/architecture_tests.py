from __future__ import annotations

import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or '')
    return names


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_domain_does_not_import_application_or_infrastructure(self) -> None:
        violations: list[str] = []
        for path in (PROJECT_ROOT / 'domain').rglob('*.py'):
            for name in _imports(path):
                if name == 'application' or name.startswith('application.'):
                    violations.append(f'{path}: imports {name}')
                if name == 'infrastructure' or name.startswith('infrastructure.'):
                    violations.append(f'{path}: imports {name}')

        self.assertEqual([], violations)

    def test_application_does_not_import_infrastructure(self) -> None:
        violations: list[str] = []
        for path in (PROJECT_ROOT / 'application').rglob('*.py'):
            for name in _imports(path):
                if name == 'infrastructure' or name.startswith('infrastructure.'):
                    violations.append(f'{path}: imports {name}')

        self.assertEqual([], violations)

    def test_source_packages_do_not_contain_generated_python_artifacts(self) -> None:
        generated: list[str] = []
        for package_name in ('application', 'domain', 'infrastructure'):
            package_path = PROJECT_ROOT / package_name
            generated.extend(str(path.relative_to(PROJECT_ROOT)) for path in package_path.rglob('__pycache__'))
            generated.extend(str(path.relative_to(PROJECT_ROOT)) for path in package_path.rglob('*.pyc'))

        self.assertEqual([], generated)


if __name__ == '__main__':
    unittest.main()
