import re
import sys
import unittest
import xml.etree.ElementTree as ET
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
        {"name": "libkernel", "done": 4, "todo": 2, "done_names": ["a", "b", "c", "exit"]},
        {"name": "libSceEmpty", "done": 0, "todo": 0, "done_names": []},
        {"name": "libSceTodo", "done": 0, "todo": 2, "done_names": []},
        {"name": "libc", "done": 2, "todo": 0, "done_names": ["d", "exit"]}]}

    def test_counts_live_compiled_symbols_once_against_all_known(self):
        live = {"libkernel": {"a", "b"}, "libc": {"d", "exit"}}
        stub = {"libkernel": {"c"}}
        result = arm64_progress.coverage(self.LIBRARIES, live, stub, {"a", "c", "d", "exit", "zzz"})
        self.assertEqual((result["known"], result["upstream_done"], result["arm64"], result["arm64_stubs"]), (10, 6, 3, 1))
        self.assertEqual((result["percent"], result["upstream_percent"], result["of_upstream_percent"]), (30.0, 60.0, 50.0))
        self.assertEqual({g["name"]: (g["arm64"], g["known"]) for g in result["groups"]},
                         {"libkernel": (1, 6), "libc": (2, 2), "libSceTodo": (0, 2)})

    def test_a_name_live_in_two_libraries_counts_once(self):
        live = {"libkernel": {"exit"}, "libc": {"exit"}}
        self.assertEqual(arm64_progress.coverage(self.LIBRARIES, live, {}, {"exit"})["arm64"], 1)

    def test_no_known_functions(self):
        self.assertEqual(arm64_progress.coverage({"total": 0, "groups": []}, {}, {}, set())["percent"], 0)


class ShaderTest(unittest.TestCase):
    ISA = {"V_ADD_F32": "VOP2", "FLAT_LOAD_DWORD": "FLAT", "GLOBAL_LOAD_DWORD": "FLAT", "S_ENDPGM": "SOPP",
           "S_ENDPGM_SAVED": "SOPP", "V_MUL_F32": "VOP2"}

    def test_handlers_map_to_isa_names(self):
        text = "switch (op) { case RdnaOpcode::VAddF32: break; case RdnaOpcode::FlatLoadDword: case RdnaOpcode::SEndpgm: break; }"
        opcodes = set(arm64_progress.HANDLER.findall(text))
        self.assertEqual(opcodes, {"VAddF32", "FlatLoadDword", "SEndpgm"})
        self.assertEqual(arm64_progress.isa_names(opcodes, self.ISA),
                         {"V_ADD_F32", "FLAT_LOAD_DWORD", "GLOBAL_LOAD_DWORD", "S_ENDPGM", "S_ENDPGM_SAVED"})

    def test_decoder_table_entries_count(self):
        text = "{0x63u, RdnaOpcode::ImageGather8hPck, nullptr, RdnaImageSampleFlagGatherHorizontal},"
        self.assertEqual(arm64_progress.shader_opcodes(text), {"ImageGather8hPck"})

    def test_groups_by_encoding_with_missing_names(self):
        groups = arm64_progress.shader_groups(self.ISA, {"V_ADD_F32", "S_ENDPGM", "S_ENDPGM_SAVED"})
        self.assertEqual({g["name"]: (g["known"], g["arm64"], g["missing"]) for g in groups},
                         {"VOP2": (2, 1, ["V_MUL_F32"]), "FLAT": (2, 0, ["FLAT_LOAD_DWORD", "GLOBAL_LOAD_DWORD"]),
                          "SOPP": (2, 2, [])})

    def test_mentions_outside_case_labels_do_not_count(self):
        self.assertEqual(arm64_progress.HANDLER.findall("if (op == RdnaOpcode::VMulF32) {}"), [])


class MapTest(unittest.TestCase):
    LIBRARIES = {"known": 9, "arm64": 3, "percent": 33.33, "groups": [
        {"name": "libkernel", "known": 6, "upstream_done": 4, "arm64": 2},
        {"name": "libSceAgc", "known": 2, "upstream_done": 2, "arm64": 1},
        {"name": "libScePad", "known": 1, "upstream_done": 0, "arm64": 0}]}

    def test_one_box_per_library_and_one_cell_per_function(self):
        text = arm64_progress.library_map(self.LIBRARIES)
        root = ET.fromstring(text)
        namespace = "{http://www.w3.org/2000/svg}"
        self.assertNotIn("width", root.attrib)
        self.assertEqual(root.findall(f".//{namespace}script"), [])
        boxes = root.findall(f"{namespace}g")
        self.assertEqual([box.find(f"{namespace}title").text for box in boxes],
                         ["libkernel: 2/6 (33%)", "libSceAgc: 1/2 (50%)", "libScePad: 0/1 (0%)"])
        cells = {}
        for path in root.iter(f"{namespace}path"):
            step = sum(map(float, path.get("stroke-dasharray").split()))
            for x, end in re.findall(r"M([\d.]+) [\d.]+H([\d.]+)", path.get("d")):
                cells[path.get("stroke")] = cells.get(path.get("stroke"), 0) + round((float(end) - float(x)) / step)
        self.assertEqual(cells, {arm64_progress.progress.DONE_COLOR: 3, arm64_progress.progress.TODO_COLOR: 6})
        self.assertIn("Mac system libraries: 33.33% (3/9)", text)
        self.assertIn("prefers-color-scheme: light", text)


class CtestTest(unittest.TestCase):
    def test_reads_the_last_summary(self):
        log = "99% tests passed, 2 tests failed out of 737\n...\n100% tests passed, 0 tests failed out of 2\n"
        self.assertEqual(arm64_progress.ctest_result(log), {"passed": 2, "total": 2})

    def test_missing_summary(self):
        self.assertIsNone(arm64_progress.ctest_result("no summary here"))


if __name__ == "__main__":
    unittest.main()
