import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import arm64_progress

NM = """
Threads.cpp.o:
_sceKernelOpen_nid_postfix T 0 0
_EqueueAddEvent_nid_postfix T 10 0
__ZN6Kernel9ResetOnceEv T 20 0
_gTable D 30 8
_undefinedImport U 0 0

Other.cpp.o:
_sceKernelClose_nid_postfix t 40 0
"""


class SymbolTest(unittest.TestCase):
    def test_defined_global_symbols_only(self):
        symbols = arm64_progress.defined_symbols(NM)
        self.assertIn("_sceKernelOpen_nid_postfix", symbols)
        self.assertIn("_gTable", symbols)
        self.assertNotIn("_undefinedImport", symbols)
        self.assertNotIn("Threads.cpp.o:", symbols)

    def test_base_names_strip_underscore_and_demangle(self):
        symbols = {"_sceKernelOpen_nid_postfix", "__ZN6Kernel9ResetOnceEv", "__ZN3Foo3BarIiEEvT_"}
        demangled = {"__ZN6Kernel9ResetOnceEv": "Kernel::ResetOnce()", "__ZN3Foo3BarIiEEvT_": "void Foo::Bar<int>(int)"}
        self.assertEqual(arm64_progress.base_names(symbols, demangled), {"sceKernelOpen_nid_postfix", "ResetOnce", "Bar"})


class CoverageTest(unittest.TestCase):
    def test_counts_only_upstream_implemented_names(self):
        libraries = {"total": 10, "groups": [
            {"name": "libkernel", "done": 3, "done_names": ["a", "b", "c"]},
            {"name": "libSceEmpty", "done": 0, "done_names": []},
            {"name": "libc", "done": 1, "done_names": ["d"]}]}
        result = arm64_progress.coverage(libraries, {"a", "c", "zzz"})
        self.assertEqual((result["upstream_done"], result["arm64"], result["percent"], result["upstream_total"]),
                         (4, 2, 50.0, 10))
        self.assertEqual([g["name"] for g in result["groups"]], ["libkernel", "libc"])

    def test_no_implemented_functions(self):
        self.assertEqual(arm64_progress.coverage({"total": 0, "groups": []}, set())["percent"], 0)


class CtestTest(unittest.TestCase):
    def test_reads_the_last_summary(self):
        log = "99% tests passed, 2 tests failed out of 737\n...\n100% tests passed, 0 tests failed out of 2\n"
        self.assertEqual(arm64_progress.ctest_result(log), {"passed": 2, "total": 2})

    def test_missing_summary(self):
        self.assertIsNone(arm64_progress.ctest_result("no summary here"))


if __name__ == "__main__":
    unittest.main()
