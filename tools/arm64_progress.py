import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import progress

CTEST_SUMMARY = re.compile(r"(\d+)% tests passed, (\d+) tests? failed out of (\d+)")


def defined_symbols(nm_output):
    names = set()
    for line in nm_output.splitlines():
        fields = line.split()
        if len(fields) >= 2 and not line.endswith(":") and fields[1].upper() in "TDSBRVW" and len(fields[1]) == 1:
            names.add(fields[0])
    return names


def base_names(symbols, demangled):
    names = set()
    for symbol in symbols:
        if symbol in demangled:
            head = demangled[symbol].split("(", 1)[0]
            names.add(re.sub(r"<.*>", "", head).rsplit("::", 1)[-1].strip())
        else:
            names.add(symbol[1:] if symbol.startswith("_") else symbol)
    return names


def archive_symbols(archives):
    symbols = set()
    for archive in archives:
        output = subprocess.run(["nm", "-g", "--defined-only", "-P", str(archive)], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", check=True).stdout
        symbols |= defined_symbols(output)
    mangled = sorted(s for s in symbols if s.startswith(("__Z", "_Z")))
    demangled = {}
    if mangled:
        output = subprocess.run(["c++filt"], input="\n".join(mangled), capture_output=True, text=True,
                                encoding="utf-8", errors="replace", check=True).stdout.splitlines()
        demangled = dict(zip(mangled, output))
    return base_names(symbols, demangled)


def coverage(libraries, available):
    groups = []
    for group in libraries["groups"]:
        if not group["done"]:
            continue
        native = sorted(set(group["done_names"]) & available)
        groups.append({"name": group["name"], "upstream_done": group["done"], "arm64": len(native)})
    done = sum(g["upstream_done"] for g in groups)
    arm64 = sum(g["arm64"] for g in groups)
    return {"upstream_done": done, "upstream_total": libraries["total"], "arm64": arm64,
            "percent": round(100 * arm64 / done, 2) if done else 0,
            "groups": sorted(groups, key=lambda g: (-g["arm64"], g["name"]))}


def ctest_result(text):
    found = CTEST_SUMMARY.findall(text)
    if not found:
        return None
    _, failed, total = map(int, found[-1])
    return {"passed": total - failed, "total": total}


def behind(ref, upstream):
    output = subprocess.run(["git", "rev-list", "--count", f"{ref}..{upstream}"], capture_output=True, text=True,
                            check=True).stdout
    return int(output.strip())


def main():
    parser = argparse.ArgumentParser(description="measure how much of upstream's implemented library surface the native ARM64 build provides")
    parser.add_argument("archives", nargs="+", type=Path, help="static libraries of the native ARM64 build")
    parser.add_argument("--ctest-log", type=Path, help="output of a ctest run of the AOT build")
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--upstream", help="upstream branch to count commits behind, for example upstream/main")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    result = {"date": date.today().isoformat(),
              "commit": subprocess.run(["git", "rev-parse", "--short", arguments.ref], capture_output=True, text=True,
                                       check=True).stdout.strip(),
              "libraries": coverage(progress.collect_libraries(), archive_symbols(arguments.archives))}
    if arguments.ctest_log:
        result["tests"] = ctest_result(arguments.ctest_log.read_text(encoding="utf-8", errors="replace"))
    if arguments.upstream:
        result["behind"] = behind(arguments.ref, arguments.upstream)
    text = json.dumps(result, indent=2) + "\n"
    if arguments.output:
        arguments.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
