import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import arm64_progress

NM = """
Threads.cpp.o:
_sceKernelOpen_nid_postfix T 0 0
__ZN6Kernel9ResetOnceEv T 20 0
_gTable D 30 8
_undefinedImport U 0 0
_localHelper t 40 0
"""

COMPILED = """
int APS5_VABI sceKernelOpen_nid_postfix(const char* path) { return OpenHost(path); }
int APS5_VABI sceKernelGetModuleInfo_nid_postfix(int handle) { return NotImplemented_nid_no_patch(__func__); }
int APS5_VABI sceKernelClose_nid_postfix(int fd) { return host::NotImplemented_nid_no_patch(fd); }
"""

PREPROCESSED = """# 1 "/tmp/x/libkernel__Open.cpp"
# 1 "<built-in>" 1
int fromHeader();
# 3 "/tmp/x/libkernel__Open.cpp" 2
int ANYPS5PROGRESSVABI sceKernelOpen_nid_postfix() { return 0; }
"""


class SymbolTest(unittest.TestCase):
    def test_only_defined_global_symbols(self):
        symbols = arm64_progress.defined_symbols(NM)
        self.assertEqual(symbols, {"_sceKernelOpen_nid_postfix", "__ZN6Kernel9ResetOnceEv", "_gTable"})

    def test_c_names_strip_underscore_and_skip_cpp(self):
        self.assertEqual(arm64_progress.c_names({"_sceKernelOpen_nid_postfix", "__ZN6Kernel9ResetOnceEv", "plain"}),
                         {"sceKernelOpen_nid_postfix", "plain"})


class PreprocessTest(unittest.TestCase):
    def test_arguments_drop_outputs_and_the_source(self):
        source = Path("/repo/core/libs/prx/libkernel/File/Open.cpp")
        command = f"clang++ -DX=1 -Iinc -MD -MT a.o -MF a.d -o a.o -c {source}"
        arguments = arm64_progress.preprocess_arguments(command, source, Path("/tmp/x/libkernel__File__Open.cpp"))
        self.assertEqual(arguments, ["clang++", "-DX=1", "-Iinc", "-E", "-iquote", "/repo/core/libs/prx/libkernel/File",
                                     "/tmp/x/libkernel__File__Open.cpp"])

    def test_keeps_only_the_main_file(self):
        text = arm64_progress.main_file_lines(PREPROCESSED, Path("/tmp/x/libkernel__Open.cpp"))
        self.assertNotIn("fromHeader", text)
        self.assertIn("sceKernelOpen_nid_postfix", text)


class ScanTest(unittest.TestCase):
    def test_stub_and_live_definitions(self):
        live, stub = arm64_progress.scan_compiled(COMPILED)
        self.assertEqual(live, {"sceKernelOpen_nid_postfix", "sceKernelClose_nid_postfix"})
        self.assertEqual(stub, {"sceKernelGetModuleInfo_nid_postfix"})


class CoverageTest(unittest.TestCase):
    LIBRARIES = {"total": 10, "groups": [
        {"name": "libkernel", "done": 4, "done_names": ["a", "b", "c", "exit"]},
        {"name": "libSceEmpty", "done": 0, "done_names": []},
        {"name": "libc", "done": 2, "done_names": ["d", "exit"]}]}

    def test_counts_live_compiled_symbols_once(self):
        live = {"libkernel": {"a", "b"}, "libc": {"d", "exit"}}
        stub = {"libkernel": {"c"}}
        result = arm64_progress.coverage(self.LIBRARIES, live, stub, {"a", "c", "d", "exit", "zzz"})
        self.assertEqual((result["upstream_done"], result["arm64"], result["arm64_stubs"], result["upstream_total"]),
                         (6, 3, 1, 10))
        self.assertEqual(result["percent"], 50.0)
        self.assertEqual({g["name"]: g["arm64"] for g in result["groups"]}, {"libkernel": 1, "libc": 2})

    def test_a_name_live_in_two_libraries_counts_once(self):
        live = {"libkernel": {"exit"}, "libc": {"exit"}}
        result = arm64_progress.coverage(self.LIBRARIES, live, {}, {"exit"})
        self.assertEqual(result["arm64"], 1)

    def test_no_implemented_functions(self):
        self.assertEqual(arm64_progress.coverage({"total": 0, "groups": []}, {}, {}, set())["percent"], 0)


class CtestTest(unittest.TestCase):
    def test_reads_the_last_summary(self):
        log = "99% tests passed, 2 tests failed out of 737\n...\n100% tests passed, 0 tests failed out of 2\n"
        self.assertEqual(arm64_progress.ctest_result(log), {"passed": 2, "total": 2})

    def test_missing_summary(self):
        self.assertIsNone(arm64_progress.ctest_result("no summary here"))


if __name__ == "__main__":
    unittest.main()
