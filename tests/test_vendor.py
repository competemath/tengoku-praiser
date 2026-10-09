import hashlib
import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_sync():
    spec = importlib.util.spec_from_file_location("sync_contract", os.path.join(ROOT, "scripts", "sync_contract.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class VendoredContract(unittest.TestCase):
    def test_vendored_copy_matches_the_pin(self):
        sync = load_sync()
        with open(os.path.join(ROOT, "vendor", "EVIDENCE.sha256"), encoding="utf-8") as fh:
            pinned, path, commit = sync.parse_pin(fh.read())
        with open(os.path.join(ROOT, "vendor", "juridicator_evidence.py"), "rb") as fh:
            actual = hashlib.sha256(fh.read()).hexdigest()
        self.assertEqual(path, "juridicator/evidence.py")
        self.assertEqual(actual, pinned, "vendor/juridicator_evidence.py was edited; refresh it with scripts/sync_contract.py")
        self.assertRegex(commit, r"^[0-9a-f]{40}$")

    def test_pin_is_the_documented_one(self):
        with open(os.path.join(ROOT, "vendor", "EVIDENCE.sha256"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "ddccbc97eef67c9e9dec395541c60b3e9de9956c88d486ecff36fad9ce6bc93e  juridicator/evidence.py"
                                        "  # tengoku-juridicator 3e70f62fc20081cd820d08c03828eaabfb0e2153\n")

    def test_a_changed_vendored_copy_would_be_noticed(self):
        sync = load_sync()
        with open(os.path.join(ROOT, "vendor", "juridicator_evidence.py"), "rb") as fh:
            data = fh.read()
        with open(os.path.join(ROOT, "vendor", "EVIDENCE.sha256"), encoding="utf-8") as fh:
            pinned = sync.parse_pin(fh.read())[0]
        self.assertNotEqual(hashlib.sha256(data + b"\n").hexdigest(), pinned)

    def test_pin_parser_refuses_other_shapes(self):
        sync = load_sync()
        for bad in ("", "abc  juridicator/evidence.py", "x" * 64 + "  juridicator/evidence.py  # tengoku-juridicator " + "1" * 40):
            with self.assertRaises(ValueError):
                sync.parse_pin(bad)
        self.assertEqual(sync.parse_pin(sync.render_pin("a" * 64, "b" * 40)), ("a" * 64, "juridicator/evidence.py", "b" * 40))

    def test_vendored_module_is_importable_and_has_the_contract(self):
        from vendor import juridicator_evidence as e

        self.assertEqual(e.SCHEMA, "tengoku-evidence/1")
        self.assertTrue(callable(e.make_evidence) and callable(e.validate))

    def test_vendor_package_is_present(self):
        self.assertTrue(os.path.exists(os.path.join(ROOT, "vendor", "__init__.py")))
        self.assertEqual(os.path.getsize(os.path.join(ROOT, "vendor", "__init__.py")), 0)


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class SyncScript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.checkout = os.path.join(self.tmp.name, "juridicator-checkout")
        os.makedirs(os.path.join(self.checkout, "juridicator"))
        self.source = os.path.join(self.checkout, "juridicator", "evidence.py")
        with open(self.source, "wb") as fh:
            fh.write(b"# a stand-in contract\nX = 1\n")
        for args in (["init", "-q", "-b", "main"], ["add", "."],
                     ["-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "seed"]):
            subprocess.run(["git", "-C", self.checkout, *args], check=True, capture_output=True)
        self.sync = load_sync()
        self.sync.VENDORED = os.path.join(self.tmp.name, "juridicator_evidence.py")
        self.sync.PIN = os.path.join(self.tmp.name, "EVIDENCE.sha256")

    def head(self):
        return subprocess.run(["git", "-C", self.checkout, "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()

    def test_copies_byte_for_byte_and_writes_a_pin_that_parses(self):
        digest = self.sync.sync(self.checkout)
        with open(self.sync.VENDORED, "rb") as fh:
            data = fh.read()
        self.assertEqual(data, b"# a stand-in contract\nX = 1\n")
        self.assertEqual(digest, hashlib.sha256(data).hexdigest())
        with open(self.sync.PIN, encoding="utf-8") as fh:
            self.assertEqual(self.sync.parse_pin(fh.read()), (digest, "juridicator/evidence.py", self.head()))

    def test_refuses_a_source_that_is_not_the_committed_one(self):
        with open(self.source, "ab") as fh:
            fh.write(b"X = 2\n")
        with self.assertRaises(SystemExit):
            self.sync.sync(self.checkout)
        self.assertFalse(os.path.exists(self.sync.VENDORED))
        self.assertFalse(os.path.exists(self.sync.PIN))


if __name__ == "__main__":
    unittest.main()
