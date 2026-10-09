"""The package is standard library only, reads no clock, calls no AI, and keeps file access in the loaders."""
import ast
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "praiser")
IO_MODULES = {"loaders.py", "cli.py", "__main__.py"}
FORBIDDEN_IN_LOGIC = {"os", "subprocess", "socket", "urllib", "http", "requests", "datetime", "time", "random", "pathlib",
                      "shutil", "tempfile", "glob", "ssl", "sys"}


def modules():
    for name in sorted(os.listdir(PKG)):
        if name.endswith(".py"):
            with open(os.path.join(PKG, name), encoding="utf-8") as fh:
                yield name, ast.parse(fh.read())


def imported(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            out.add(node.module.split(".")[0])
    return out


class Hygiene(unittest.TestCase):
    def test_only_standard_library_and_the_vendored_contract(self):
        allowed = set(sys.stdlib_module_names) | {"vendor", "praiser"}
        for name, tree in modules():
            self.assertLessEqual(imported(tree) - allowed, set(), name)

    def test_logic_modules_do_no_io_and_read_no_clock(self):
        for name, tree in modules():
            if name in IO_MODULES:
                continue
            self.assertEqual(imported(tree) & FORBIDDEN_IN_LOGIC, set(), name)
            calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
            self.assertNotIn("open", calls, name)
            self.assertNotIn("input", calls, name)

    def test_logic_modules_do_not_import_the_loaders(self):
        for name, tree in modules():
            if name in IO_MODULES:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level:
                    self.assertNotIn(node.module, ("loaders", "cli"), name)

    def test_no_module_names_an_ai_vendor_library(self):
        banned = {"anthropic", "openai", "google", "transformers", "langchain", "litellm", "cohere", "mistralai", "ollama"}
        for name, tree in modules():
            self.assertEqual(imported(tree) & banned, set(), name)

    def test_every_backend_interface_checks_tools(self):
        for name, tree in modules():
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and any(getattr(b, "id", "") == "Protocol" for b in node.bases):
                    body = ast.dump(node)
                    self.assertIn("tools", body, f"{name}:{node.name} must declare tools")


if __name__ == "__main__":
    unittest.main()
