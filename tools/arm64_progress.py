import argparse
import json
import re
import shlex
import subprocess
import sys
import tempfile
from datetime import date
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import progress

ROOT = Path(__file__).resolve().parents[1]
MARK = "ANYPS5PROGRESSVABI"
GLOBAL_TYPES = set("TDSBRVW")
DROPPED_WITH_VALUE = {"-o", "-MF", "-MT", "-MQ"}
DROPPED = {"-c", "-MD", "-MMD"}
HANDLER = re.compile(r"\bcase\s+RdnaOpcode::(\w+)\s*:")
DECODED = re.compile(r"\{\s*0x[0-9a-fA-F]+u?\s*,\s*RdnaOpcode::(\w+)\s*,")
CTEST_SUMMARY = re.compile(r"(\d+)% tests passed, (\d+) tests? failed out of (\d+)")
LINE_MARKER = re.compile(r'^# \d+ "([^"]+)"')
LIGHT = (f'<style>@media (prefers-color-scheme: light) {{ [fill="{progress.BORDER}"] {{ fill: #ffffff; }} '
         f'[stroke="{progress.BORDER}"] {{ stroke: #ffffff; }} '
         f'[stroke="{progress.TODO_COLOR}"] {{ stroke: #d0d7de; }} [fill="{progress.TEXT}"] {{ fill: #1f2328; }} }}</style>')


def defined_symbols(nm_output):
    names = set()
    for line in nm_output.splitlines():
        fields = line.split()
        if len(fields) >= 2 and not line.endswith(":") and fields[1] in GLOBAL_TYPES:
            names.add(fields[0])
    return names


def c_names(symbols):
    return {symbol[1:] if symbol.startswith("_") else symbol for symbol in symbols if not symbol.startswith(("__Z", "_Z"))}


def archive_symbols(archives):
    symbols = set()
    for archive in archives:
        output = subprocess.run(["nm", "-g", "--defined-only", "-P", str(archive)], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", check=True).stdout
        symbols |= defined_symbols(output)
    return c_names(symbols)


def preprocess_arguments(command, source, copy):
    arguments, skip = [], False
    for argument in shlex.split(command):
        if skip:
            skip = False
        elif argument in DROPPED_WITH_VALUE:
            skip = True
        elif argument in DROPPED or Path(argument).name == source.name and argument.endswith(source.name):
            continue
        else:
            arguments.append(argument)
    return arguments + ["-E", "-iquote", str(source.parent), str(copy)]


def main_file_lines(output, copy):
    lines, current = [], None
    for line in output.splitlines():
        marker = LINE_MARKER.match(line)
        if marker:
            current = marker.group(1)
        elif current == str(copy):
            lines.append(line)
    return "\n".join(lines)


def scan_compiled(text):
    text = progress.code(text)
    calls = progress.stub_calls(text)
    live, stub = set(), set()
    for match in progress.DEFINITION.finditer(text):
        body = text[match.end() - 1:progress.body_end(text, match.end() - 1)]
        if any(call.group(1) in calls and not progress.QUALIFIED.search(body, 0, call.start())
               for call in progress.CALL.finditer(body)):
            stub.add(match.group(1))
        else:
            live.add(match.group(1))
    return live, stub - live


def source_root(build):
    for line in (build / "CMakeCache.txt").read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("CMAKE_HOME_DIRECTORY:"):
            return Path(line.split("=", 1)[1]).resolve()
    raise RuntimeError(f"{build} has no CMAKE_HOME_DIRECTORY in CMakeCache.txt")


def preprocessed(entry, copy):
    source = Path(entry["directory"], entry["file"]).resolve()
    copy.write_text(source.read_text(encoding="utf-8", errors="ignore").replace("APS5_VABI", MARK), encoding="utf-8")
    result = subprocess.run(preprocess_arguments(entry["command"], source, copy), cwd=entry["directory"],
                            capture_output=True, text=True, errors="replace")
    if result.returncode:
        raise RuntimeError(f"preprocessing {source} failed: {result.stderr.strip()[:400]}")
    return main_file_lines(result.stdout, copy).replace(MARK, "APS5_VABI")


def compile_entries(build):
    return json.loads(subprocess.run(["ninja", "-C", str(build), "-t", "compdb"], capture_output=True, text=True,
                                     check=True).stdout)


def compiled_libraries(build, entries):
    prx = source_root(build) / "core" / "libs" / "prx"
    live, stub = {}, {}
    with tempfile.TemporaryDirectory() as scratch:
        for entry in entries:
            if "anyps5_native_" not in entry.get("output", ""):
                continue
            source = Path(entry["directory"], entry["file"]).resolve()
            try:
                relative = source.relative_to(prx)
            except ValueError:
                continue
            if "tests" in relative.parts:
                continue
            text = preprocessed(entry, Path(scratch, str(relative).replace("/", "__")))
            found_live, found_stub = scan_compiled(text)
            library = relative.parts[0]
            live.setdefault(library, set()).update(found_live)
            stub.setdefault(library, set()).update(found_stub)
    return live, {library: names - live.get(library, set()) for library, names in stub.items()}


def isa_names(opcodes, isa):
    by_camel = {progress.camel(name): name for name in isa}
    names = set()
    for opcode in opcodes:
        names.update(name for name in progress.OPCODE_VARIANTS.get(opcode, ()) if name in isa)
        name = progress.OPCODE_ALIASES.get(opcode) or by_camel.get(opcode)
        if name in isa:
            names.add(name)
            if name.startswith("FLAT_"):
                names.update(n for n in (s + name.removeprefix("FLAT_") for s in progress.FLAT_SEGMENTS) if n in isa)
    return names


def read_isa():
    isa = {}
    for line in progress.ISA.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line and not line.startswith("#"):
            name, encoding = line.split()
            isa[name] = encoding
    return isa


def shader_groups(isa, handled):
    groups = {}
    for name, encoding in isa.items():
        group = groups.setdefault(encoding, {"name": encoding, "known": 0, "arm64": 0, "missing": []})
        group["known"] += 1
        if name in handled:
            group["arm64"] += 1
        else:
            group["missing"].append(name)
    return sorted(groups.values(), key=lambda g: (-g["known"], g["name"]))


def shader_opcodes(text):
    return set(HANDLER.findall(text)) | set(DECODED.findall(text))


def shader_coverage(build, entries):
    isa = read_isa()
    recompiler = source_root(build) / "core" / "shader" / "recompiler"
    upstream = set()
    for folder in ("Translation", "RdnaDecoder"):
        for source in (ROOT / "core" / "shader" / "recompiler" / folder).rglob("*.cpp"):
            upstream |= shader_opcodes(progress.code(source.read_text(encoding="utf-8", errors="ignore")))
    native = set()
    with tempfile.TemporaryDirectory() as scratch:
        for index, entry in enumerate(entries):
            if "shader_recompiler_native" not in entry.get("output", ""):
                continue
            source = Path(entry["directory"], entry["file"]).resolve()
            if not any(source.is_relative_to(recompiler / folder) for folder in ("Translation", "RdnaDecoder")):
                continue
            native |= shader_opcodes(progress.code(preprocessed(entry, Path(scratch, f"{index}_{source.name}"))))
    handled = isa_names(native, isa)
    groups = shader_groups(isa, handled)
    return {"known": len(isa), "upstream_declared": progress.collect_shaders()["done"],
            "upstream_translated": len(isa_names(upstream, isa)), "arm64_translated": len(handled),
            "missing": sorted(name for g in groups for name in g["missing"]),
            "groups": [{key: g[key] for key in ("name", "known", "arm64")} for g in groups]}


def coverage(libraries, live, stub, symbols):
    groups, counted, stubbed = [], set(), 0
    for group in libraries["groups"]:
        known = group["done"] + group["todo"]
        if not known:
            continue
        done = set(group["done_names"])
        native = sorted((done & live.get(group["name"], set()) & symbols) - counted)
        counted.update(native)
        stubbed += len(done & stub.get(group["name"], set()))
        groups.append({"name": group["name"], "known": known, "upstream_done": group["done"], "arm64": len(native)})
    known = sum(g["known"] for g in groups)
    upstream_done = sum(g["upstream_done"] for g in groups)
    share = lambda part, whole: round(100 * part / whole, 2) if whole else 0
    return {"known": known, "upstream_done": upstream_done, "arm64": len(counted), "arm64_stubs": stubbed,
            "percent": share(len(counted), known), "upstream_percent": share(upstream_done, known),
            "of_upstream_percent": share(len(counted), upstream_done),
            "groups": sorted(groups, key=lambda g: (-g["arm64"], g["name"]))}


def cell_runs(cells, done):
    runs = {}
    for i, (x, y, w, h) in enumerate(cells):
        color = progress.DONE_COLOR if i < done else progress.TODO_COLOR
        segments = runs.setdefault((color, w, h), [])
        if segments and segments[-1][1] == y and abs(segments[-1][2] - x) < 1e-6:
            segments[-1][2] = x + w
        else:
            segments.append([x, y, x + w])
    parts = []
    for (color, w, h), segments in runs.items():
        if w > 0.5 and h > 0.5:
            line = "".join(f"M{x:.2f} {y + h / 2:.2f}H{end:.2f}" for x, y, end in segments)
            parts.append(f'<path d="{line}" fill="none" stroke="{color}" stroke-width="{h - 0.5:.2f}" '
                         f'stroke-dasharray="{w - 0.5:.4f} 0.5" stroke-dashoffset="{w - 0.25:.4f}"/>')
    return parts


def library_map(libraries):
    groups = sorted((g for g in libraries["groups"] if g["known"]), key=lambda g: -g["known"])
    width, height = progress.PANEL_WIDTH, progress.HEADER + progress.MAP_HEIGHT
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">', LIGHT,
             progress.rect(0, 0, width, height, progress.BORDER, 0),
             progress.text(4, 21, f'Mac system libraries: {libraries["percent"]}% ({libraries["arm64"]}/{libraries["known"]})', 16)]
    areas = progress.squarify([g["known"] for g in groups], 0, progress.HEADER, width, progress.MAP_HEIGHT)
    for group, (x, y, w, h) in zip(groups, areas):
        label = group["name"].removeprefix("libSce")
        parts.append(f'<g><title>{escape(group["name"])}: {group["arm64"]}/{group["known"]} '
                     f'({100 * group["arm64"] / group["known"]:.0f}%)</title>')
        parts += cell_runs(progress.cells(group["known"], x + 1, y + 1, w - 2, h - 2), group["arm64"])
        parts.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" fill="none" stroke="{progress.BORDER}" stroke-width="2"/>')
        shown = label[:int((w - 10) / 7)] if int((w - 10) / 7) > 0 else ""
        if (shown == label or len(shown) >= 3) and h > 22:
            parts.append(progress.text(x + 5, y + 16, shown, 12))
        parts.append("</g>")
    return "\n".join(parts + ["</svg>"]) + "\n"


def ctest_result(text):
    found = CTEST_SUMMARY.findall(text)
    if not found:
        return None
    _, failed, total = map(int, found[-1])
    return {"passed": total - failed, "total": total}


def git(*arguments):
    return subprocess.run(["git", "-C", str(ROOT), *arguments], capture_output=True, text=True, check=True).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description="measure how much of upstream's implemented library surface the native ARM64 build compiles")
    parser.add_argument("build", type=Path, help="native ARM64 build directory (the graphics build)")
    parser.add_argument("--ctest-log", type=Path, help="output of a ctest run of the AOT build")
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--upstream", help="upstream branch to count commits behind, for example upstream/main")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--svg", type=Path, help="write the library map as an SVG image")
    arguments = parser.parse_args()
    archives = sorted((arguments.build / "core" / "libs" / "native").glob("*.a")) + sorted((arguments.build / "core" / "aot").glob("*.a"))
    if not archives:
        parser.error(f"no ARM64 archives under {arguments.build}")
    entries = compile_entries(arguments.build)
    live, stub = compiled_libraries(arguments.build, entries)
    result = {"date": date.today().isoformat(), "commit": git("rev-parse", "--short", arguments.ref),
              "libraries": coverage(progress.collect_libraries(), live, stub, archive_symbols(archives)),
              "shaders": shader_coverage(arguments.build, entries)}
    if arguments.ctest_log:
        result["tests"] = ctest_result(arguments.ctest_log.read_text(encoding="utf-8", errors="replace"))
    if arguments.upstream:
        result["behind"] = int(git("rev-list", "--count", f"{arguments.ref}..{arguments.upstream}"))
    if arguments.svg:
        arguments.svg.write_text(library_map(result["libraries"]), encoding="utf-8")
    text = json.dumps(result, indent=2) + "\n"
    if arguments.output:
        arguments.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
