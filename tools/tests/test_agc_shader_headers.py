import re
import unittest
from pathlib import Path

CMAKE = Path(__file__).resolve().parents[2] / "core" / "libs" / "prx" / "libSceAgcDriver" / "CMakeLists.txt"


def block(text, opener):
    start = text.index(opener)
    return text[start:text.index("\n)", start) if opener.startswith("set(") else text.index("\nfind_package", start)]


class AgcShaderHeadersTest(unittest.TestCase):
    def test_every_generated_header_of_the_driver_sources_is_built_by_the_native_target(self):
        text = CMAKE.read_text(encoding="utf-8")
        sources = set(re.findall(r"\$\{(agc\w*Headers?)\}", block(text, "set(agcDriverSources")))
        target = set(re.findall(r"(agc\w*Headers?)", block(text, "add_custom_target(agc_shader_headers")))
        self.assertTrue(sources)
        self.assertEqual(sorted(sources - target), [])


if __name__ == "__main__":
    unittest.main()
