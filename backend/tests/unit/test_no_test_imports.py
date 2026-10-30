import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"


def test_application_code_imports_nothing_from_tests():
    offenders = []
    for path in APP.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(name == "tests" or name.startswith("tests.") for name in names):
                offenders.append(str(path))
    assert not offenders
