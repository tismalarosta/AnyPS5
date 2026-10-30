import argparse
import json
import re
import shlex
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import progress

ROOT = Path(__file__).resolve().parents[1]
MARK = "ANYPS5PROGRESSVABI"
GLOBAL_TYPES = set("TDSBRVW")
DROPPED_WITH_VALUE = {"-o", "-MF", "-MT", "-MQ"}
DROPPED = {"-c", "-MD", "-MMD"}
CTEST_SUMMARY = re.compile(r"(\d+)% tests passed, (\d+) tests? failed out of (\d+)")
LINE_MARKER = re.compile(r'^# \d+ "([^"]+)"')


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


def compiled_libraries(build):
    prx = source_root(build) / "core" / "libs" / "prx"
    entries = json.loads(subprocess.run(["ninja", "-C", str(build), "-t", "compdb"], capture_output=True, text=True,
                                        check=True).stdout)
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
            copy = Path(scratch, str(relative).replace("/", "__"))
            copy.write_text(source.read_text(encoding="utf-8", errors="ignore").replace("APS5_VABI", MARK), encoding="utf-8")
            result = subprocess.run(preprocess_arguments(entry["command"], source, copy), cwd=entry["directory"],
                                    capture_output=True, text=True, errors="replace")
            if result.returncode:
                raise RuntimeError(f"preprocessing {relative} failed: {result.stderr.strip()[:400]}")
            found_live, found_stub = scan_compiled(main_file_lines(result.stdout, copy).replace(MARK, "APS5_VABI"))
            library = relative.parts[0]
            live.setdefault(library, set()).update(found_live)
            stub.setdefault(library, set()).update(found_stub)
    return live, {library: names - live.get(library, set()) for library, names in stub.items()}


def coverage(libraries, live, stub, symbols):
    groups, counted, stubbed = [], set(), 0
    for group in libraries["groups"]:
        if not group["done"]:
            continue
        done = set(group["done_names"])
        native = sorted((done & live.get(group["name"], set()) & symbols) - counted)
        counted.update(native)
        stubbed += len(done & stub.get(group["name"], set()))
        groups.append({"name": group["name"], "upstream_done": group["done"], "arm64": len(native)})
    upstream_done = sum(g["upstream_done"] for g in groups)
    return {"upstream_done": upstream_done, "upstream_total": libraries["total"], "arm64": len(counted),
            "arm64_stubs": stubbed, "percent": round(100 * len(counted) / upstream_done, 2) if upstream_done else 0,
            "groups": sorted(groups, key=lambda g: (-g["arm64"], g["name"]))}


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
    arguments = parser.parse_args()
    archives = sorted((arguments.build / "core" / "libs" / "native").glob("*.a")) + sorted((arguments.build / "core" / "aot").glob("*.a"))
    if not archives:
        parser.error(f"no ARM64 archives under {arguments.build}")
    live, stub = compiled_libraries(arguments.build)
    result = {"date": date.today().isoformat(), "commit": git("rev-parse", "--short", arguments.ref),
              "libraries": coverage(progress.collect_libraries(), live, stub, archive_symbols(archives))}
    if arguments.ctest_log:
        result["tests"] = ctest_result(arguments.ctest_log.read_text(encoding="utf-8", errors="replace"))
    if arguments.upstream:
        result["behind"] = int(git("rev-list", "--count", f"{arguments.ref}..{arguments.upstream}"))
    text = json.dumps(result, indent=2) + "\n"
    if arguments.output:
        arguments.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
