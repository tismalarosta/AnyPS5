# Build

## Relinker only

The relinker can be built without initializing submodules or configuring SDL, Vulkan, FFmpeg, FreeType or the shader recompiler. It requires CMake, a C++20 compiler and a build tool. Python 3.9 or newer enables the Python regression tests; Python 3.11 or newer also registers `validate_patch_catalog`, which needs `tomllib`.

```sh
cmake -S . -B build-relinker -G Ninja -DCMAKE_BUILD_TYPE=Release -DANYPS5_RELINKER_ONLY=ON -DBUILD_TESTING=ON
cmake --build build-relinker --parallel
ctest --test-dir build-relinker --output-on-failure
```

Python must be found during CMake configuration for Python tests to be registered. List registered tests with `ctest --test-dir build-relinker -N` and look for `input_magic`, a Python-backed relinker test. If automatic discovery fails, add `-DPython3_EXECUTABLE="C:/path/to/python.exe"` to the configure command, using the path to your Python interpreter, then list the tests again.

This mode builds the conversion tool and its tests on Linux, Windows and macOS, including Apple Silicon. macOS uses AppleClang from the Xcode command-line tools (`xcode-select --install`); CMake and Ninja come from Homebrew (`brew install cmake ninja`). Windows uses MinGW-w64 GCC with C++20 support and accepts distributions with static or shared runtimes; the full build also requires the exception support described below. The executable is `build-relinker/core/relinker/relinker` (`relinker.exe` on Windows with Ninja).

The output is x86-64: Linux ELF by default, Windows PE with `--windows` or Mach-O with `--macos` ([usage](../user/USAGE.md#input-and-conversion)). Converted games need system libraries built for the target OS and a compatible x86-64 host. This mode does not build those libraries, and releases ship them for Linux and Windows only. Tests inspect all three output formats; execution checks run only on their compatible hosts.

Use a separate build directory for the full build.

## Fuzzing

`ANYPS5_BUILD_FUZZERS` builds `relinker_conversion_fuzzer`, a libFuzzer target that runs the whole conversion on its input, as the web converter does. It requires `ANYPS5_RELINKER_ONLY`, Clang on Linux and the compiler-rt sanitizer runtimes (`libclang-rt-18-dev` on Ubuntu 24.04). Every target is built with AddressSanitizer and UndefinedBehaviorSanitizer, without `-fsanitize=function`: that check reads a signature before the target of every indirect call and faults on the generated code the codegen tests call. The first input byte selects the target system (modulo 3: Linux, Windows, macOS), bit 2 `--to-intel` and the byte shifted right by 3, modulo 3, the `unused-filter` level; the remaining bytes are the executable. A conversion that throws a `std::exception` is a rejected input; a sanitizer report, an abort or a timeout is a finding.

```sh
cmake -S . -B build-fuzz -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo -DANYPS5_RELINKER_ONLY=ON -DANYPS5_BUILD_FUZZERS=ON -DBUILD_TESTING=ON -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++
cmake --build build-fuzz --target relinker_conversion_fuzzer
python3 tools/relinker_fuzz_seeds.py build-fuzz/fuzz-corpus
build-fuzz/tests/relinker_conversion_fuzzer build-fuzz/fuzz-corpus -fork=2 -max_total_time=1200 -timeout=20
```

`relinker_fuzz_seeds.py` writes the executables built by the relinker's Python tests as seeds, one per target system. With `BUILD_TESTING=ON`, CTest runs 20000 inputs from an empty corpus as `relinker_conversion_fuzzer`. Findings are written to the working directory as `crash-*`, `timeout-*` or `oom-*`; reproduce one with `build-fuzz/tests/relinker_conversion_fuzzer <file>`.

## Experimental native Apple ARM64 compiler

`ANYPS5_NATIVE_AOT` enables an offline Apple ARM64 compiler on Apple Silicon or Linux. The default `apple-arm64` target emits Mach-O for Apple Silicon. The optional `linux-arm64` validation target emits AArch64 ELF so Linux ARM64 CI can execute compiler output natively. It reads x86-64 ELF code and explicit function/data contracts, emits LLVM IR, and optionally builds an ARM64 Mach-O object with Xcode's Clang. Generated code uses native calls and stack frames; there is no shipped x86 decoder, interpreter or JIT. This target is an initial compiler implementation, not a complete macOS game runtime.

It requires Python 3.10 or newer, Xcode command-line tools on macOS or Clang on Linux, and two pinned source submodules. Execution tests require a native ARM64 host. Linux x86-64 can cross-compile both object formats but does not run them. The regular relinker and full build keep their existing behavior when the option is off.

git submodule update --init 3rdparty/capstone 3rdparty/pyelftools
cmake -S . -B build-aot -G Ninja -DCMAKE_BUILD_TYPE=Release -DANYPS5_RELINKER_ONLY=ON -DANYPS5_NATIVE_AOT=ON -DBUILD_TESTING=ON
cmake --build build-aot --parallel
ctest --test-dir build-aot --output-on-failure --parallel 2
python3 build-aot/core/aot/native_aot.py input.elf --contracts contracts.json --output module.ll --object module.o

The contract has `schema: 1`, the input file's `sha256`, `functions`, `imports`, complete non-executable `data` segments, and `pointer_relocations`. Each function declares its guest address and size, native symbol name, scalar result and parameter types. Import keys are the ELF symbol names; values declare the native provider's name and signature. Relocation entries are `[guest_slot, guest_target]` pairs. The compiler checks these against the image instead of guessing an ABI. The generated object must be linked with native implementations of its imports and a native entry-point caller. It does not include PS5 system libraries, a process loader or application packaging.

Supported operations cover declared scalar integer, SSE and VEX integer/bitwise subsets. Native signatures support integer and pointer parameters, `float`/`double`, narrow integer extension and stack arguments. Direct calls and resolved tail calls use native functions. Register or memory calls require an instruction-address-bound signature and a declared compatible target set; target completeness remains the annotation author's responsibility. The recovery helper in `core/aot/recover.py` collects symbol, unwind and companion-object evidence but does not infer signatures or prove all indirect targets.

The tests build synthetic ELF inputs, compile and execute ARM64 code, check native callback/tail-call ABIs and compare supported operations with independent integer oracles and x86 SSE probes. The SSE reference executables use Rosetta on Apple Silicon; generated ARM64 programs do not. Those differential tests therefore require Rosetta to be installed. They do not qualify console hardware, complete games or performance.

### Source-built native runtime example

Initialize `3rdparty/ps5link-sdk` at its recorded commit. This optional source dependency builds the public SDK linker and startup code under its GPL-3.0 license; no third-party fixture binaries are checked in. The ordinary compiler build does not require it.

git submodule update --init 3rdparty/capstone 3rdparty/pyelftools 3rdparty/ps5link-sdk
cmake -S . -B build-aot -G Ninja -DCMAKE_BUILD_TYPE=Release -DANYPS5_RELINKER_ONLY=ON -DANYPS5_NATIVE_AOT=ON -DANYPS5_NATIVE_AOT_EXAMPLE=ON -DBUILD_TESTING=ON
cmake --build build-aot --target native_aot_hello_notify --parallel 3

On Apple Silicon this command compiles the SDK's `hello_notify` source to x86-64 ELF, derives hash-bound contracts from matched companion objects and DWARF stack locations, emits ARM64 Mach-O, links the runtime, and executes the resulting program. It checks the notification, process exit and teardown callback, an ARM64-only executable, and `sysctl.proc_translated=0`. The runtime reuses the repository's application heap, notification and timer implementations with native image registration and startup glue. Missing imports fail during contract generation or linking. No game runtime, module loader or interpreter is bundled.

The default CI source variant changes only the example's 30-second delay to 1,000 microseconds so each test remains below 30 seconds; the runtime's sleep function is not bypassed. The source hashes, function coverage, frame prologue and debug stack object must match the declared example. The generated `build-aot/core/aot/hello-notify/contracts.json`, `module.ll`, `module.optimized.ll` and `result.json` describe the actual input and result. To build and run the original delay on Apple Silicon or Linux ARM64, use `cmake --build build-aot --target native_aot_hello_notify_original`. This manual target writes to the `hello-notify/original` subdirectory and remains outside the time-limited CTest suite.

On Linux ARM64 the same target emits AArch64 ELF and executes it natively, checking the notification, exit, teardown, executable machine type and host architecture. Immutable imports use ELF RELRO and startup checks of the actual process mappings. Linux x86-64 cross-compiles the example to Apple ARM64 Mach-O without executing it. Both Linux configurations also run the native C++ image, heap, notification, timer and readonly-page tests. The ARM64 CI job runs the AOT tests only; the relinker's x86-only execution tests remain in the x86-64 job. Apple Silicon runs the full native compiler suite and the Mach-O example. Rosetta is needed only for the older x86 SSE reference tests, not for building or executing either native runtime example.

The CLI accepts `--target apple-arm64` (default) or `--target linux-arm64`; the selected target is recorded in the compilation report. Linux ARM64 exists to validate the same lowering and runtime consumer in Linux CI. Its qualification is limited to the tested scalar/provider/example paths and is not a complete additional platform port.


Guest TLS and C++ exceptions, aggregate and variadic ABIs, general computed jumps, x87, atomics, guest fault delivery, concurrent memory semantics and full module lifecycle are incomplete. Unsupported instructions and declared ABIs reject. Pointer operands need a proven native origin: declared pointer arguments/results, reconstructed image/frame addresses or tracked pointer cells. For acyclic direct calls within the image, the compiler infers writes from validated instruction states, including transitive tail calls. Private frame writes preserve caller memory proofs; fixed image writes invalidate overlapping pointer cells. For a single-entry straight-line loop, constant initialization, one positive 64-bit increment after an equality exit test, and exact reachability of the exit value can prove an unsigned index range without wraparound. The range applies only inside that loop; indexed frame writes preserve unrelated pointer cells only when their entire byte range stays inside the native frame. The report records these bounded-loop proofs. Fixed-size writes through declared pointer parameters are inferred with signed constant offsets and propagated through acyclic direct and tail calls. A known register argument or tracked stack argument resolves them to a bounded frame/image region or to a caller parameter. Overlapping ranges are combined per parameter; different parameters may alias. Unresolved caller parameters still invalidate memory proofs, while their relative writes remain available to higher-level callers. Other loop shapes, unqualified imports, indirect calls, recursive call chains and unresolved aliases retain conservative invalidation. Exact eight-byte pointer stores, spills and reloads retain their frame/image/parameter origin, including declared incoming stack parameters. Partial, wide or potentially aliasing writes invalidate every overlapping cell; unknown calls clear these origins. Control-flow joins retain only identical origins on all paths. Arbitrary pointer fields loaded from structs still reject. Inferred effects and provider-binding preconditions are included in the compilation report. Concurrent accesses are not qualified by the single-threaded memory model. See [TechnicalDebt](TechnicalDebt.md) for the remaining qualification limits.

Import contracts optionally accept `memory_effects` with exactly `writes`, `callbacks` and a nonempty `evidence` string. These are caller-verified assertions about the actual native provider and execution profile, not inferred or checked against its binary. `writes` must cover all changes to guest-visible memory, including captured aliases and globals. `callbacks: false` asserts no guest callback or reentry during the call. Private host state is excluded only when it cannot alias tracked guest memory; asynchronous mutation is outside this profile. Missing effects or possible guest callbacks invalidate memory proofs.

For example, a verified native `memset(ptr, i32, u64)` provider may declare:

```json
"memory_effects": {
  "writes": [{"parameter": 0, "size_parameter": 2}],
  "callbacks": false,
  "evidence": "Identify the provider implementation/version, source and verified execution constraints"
}

Each write starts at a pointer parameter and specifies either a constant unsigned byte `size` or an integer `size_parameter`. Indices are zero-based. The current analysis requires a register or tracked stack pointer argument with a proven frame/image address and a constant extent; unresolved or out-of-region destinations and unknown extents retain conservative invalidation. A zero extent performs no write. `writes: []` asserts no guest-visible writes. Known scalar stack bytes can supply null pointer arguments and constant extents, including stack-passed sizes. Partial values and conflicting control-flow paths do not prove a complete constant. An all-zero pointer argument is accepted as native null without assigning pointer provenance to arbitrary integers. Native return-pointer identity still follows the result ABI contract; return aliases are not inferred.

Provider effects apply only while the import slot retains its original binding. Writes invalidate binding proofs even when they store another native pointer. Callee binding preconditions propagate through direct, tail and declared indirect calls, including recursive dependencies, and must hold before calling code compiled under those assumptions. External native callers must honor the reported preconditions as well. Internal functions cannot override inferred effects with annotations. The report retains provider evidence for review; linking the matching provider remains the caller's responsibility.


The optional `native_runtime_registration: true` contract validates the process/libc parameter chain and allocator callback ABIs, emits a versioned native image descriptor, and registers it after pointer relocations. The descriptor is version 2 ([checked at registration](../../core/libs/native/NativeAotImage.cpp)): it also carries the input ELF's program header table, which the runtime copies and counts against the flexible-memory budget. Objects built for version 1 are refused and must be regenerated. Link these objects with the `anyps5_native_image` static target and the actual native import providers. The registry supplies `ApplicationProcessParameters_nid_no_patch`; do not also link the ordinary executable-image implementation of that symbol. No fixed guest data address is required in the launcher. The component accepts one main image with static metadata lifetime; module loading/unloading and complete runtime integration remain outside this target. Allocator extension callbacks without a supported signature reject.

Functions may opt into `checked_stack_accesses`: each record has an instruction `address`, memory `operand` index, a declared stack object's `object_offset`, and a boolean `pointer`. The instruction must have one memory operand with a proven native frame base. The compiler emits native bounds checks before the access and traps on violation; this does not provide guest fault delivery. A `pointer: true` scalar load additionally checks eight-byte cell alignment and requires every candidate cell to contain an independently proved native pointer. Declaring a pointer table does not establish its contents. Stores conservatively invalidate the object's affected pointer proofs. Object layouts remain source/recovery contracts. The report lists these checked accesses separately from statically bounded loops; their runtime cost must be measured on each workload.

`immutable_data` optionally lists complete data segments as `{"address": ..., "evidence": "..."}`. This profile forbids writes, rebinding, unmapping or reprotection of those segments. Pointer relocations are emitted as symbolic native initializers in Mach-O `__DATA_CONST`; they are not patched by stores in the AOT constructor. The native image support library verifies readable, non-writable mappings before guest entry. Statically resolved writes and writable call effects into those ranges reject. Their pointer cells/import bindings remain invariant across calls; mutable segments retain conservative invalidation. External providers must honor the immutable-region contract. This is a constrained static-linking profile, not support for self-modifying import tables. See [LLVM global variables](https://llvm.org/docs/LangRef.html#global-variables) and [Apple dyld initialization](https://github.com/apple-oss-distributions/dyld/blob/main/doc/dyld4.md).

### Checked graphics contracts

Graphics inputs may supply instruction-bound `checked_pointer_loads`, `checked_pointer_arguments` and `checked_pointer_bases`. Each record requires source/ABI evidence, a byte extent and the relevant instruction or argument. The compiler emits native mapping checks where requested; it does not introduce a runtime decoder or interpreter. These checks establish readable host mappings, not allocation ownership, object type, lifetime or general guest-address translation. Nullability is explicit. Unannotated accesses retain the static-provenance requirements.

`pointer_outputs` declares source-qualified native-provider output fields and a `zero` or `nonnegative` status predicate. Proof is available only after an immediate matching status test and branch, with the original provider binding intact. Internal declarations additionally require `within_parameter`: an emitted native guard checks the returned field against the input's known image region or declared stack object. Independently inferred parameter-field outputs must hold on every return path; an arbitrary zero store alone does not establish a native pointer origin.

`checked_frame_exclusion` emits a guard that prevents a declared external store from touching the private frame, including copied incoming stack arguments. Image aliases remain conservative. A checked stack-access record may set `dynamic_base: true` to prove membership in its declared frame object at runtime. Neither form permits writes outside its checked range. SIMD aliases and partial register writes invalidate affected proofs.

`guard_diagnostics: true` reports the guest instruction and guard category before a trap. The object gate still rejects residual virtual-register allocations and freezes of literal poison/undef; legitimate SSA freezes inserted by LLVM loop optimization are counted separately. `debug_pointer_loads.py` collects candidates only from matched companion-object DWARF locations and their lexical/inlined scopes. Candidates still require source-profile qualification; they are not general ABI recovery.
## Full build

```sh
git submodule update --init --recursive
```

## Requirements

- x86-64, Git, CMake 3.22.1 or newer, Ninja, C++20. On Apple silicon the default build is x86-64 and runs under Rosetta; the opt-in native AOT profiles are described separately.
- Linux display refresh queries require SDL's XRandR support (`libxrandr-dev` on Debian/Ubuntu; `libXrandr-devel` on Fedora). Bundled SDL configuration fails without it. Keep `SDL_X11_XRANDR` enabled.
- Linux: GCC, G++, binutils. SDL's X11 backend requires X11 and Xext development headers (`libx11-dev` and `libxext-dev` on Debian/Ubuntu). SDL's Wayland backend requires the Wayland, xkbcommon and EGL development files (`libwayland-dev`, `libxkbcommon-dev` and `libegl-dev` on Debian/Ubuntu; `wayland-devel`, `libxkbcommon-devel` and `mesa-libEGL-devel` on Fedora), and `libdecor-0-dev` (`libdecor-devel`) for window decorations on GNOME. SDL loads both backends at run time and prefers Wayland when `WAYLAND_DISPLAY` is set; `SDL_VIDEODRIVER=x11` selects X11 (XWayland). Titles that bundle their own SDL read `SDL_VIDEODRIVER` too, and some of them fail to start with `x11`. Without the Wayland files configuration still succeeds, and the build uses X11 only. Audio output needs SDL's PipeWire, PulseAudio or ALSA backend, built from their development files (`libpipewire-0.3-dev`, `libpulse-dev` and `libasound2-dev` on Debian/Ubuntu; `pipewire-devel`, `pulseaudio-libs-devel` and `alsa-lib-devel` on Fedora). SDL loads them at run time. Without any of them SDL keeps only its silent dummy and disk drivers, so configuration fails.
- Fedora: if CMake reports `Could NOT find Threads`, install `glibc-static` and `libstdc++-static` with `sudo dnf install glibc-static libstdc++-static`, then rerun configuration. The project enables static executable linking, and FFmpeg's thread check needs these libraries.
- Windows: x86-64 MinGW-w64 GCC with POSIX threads. The compiler must provide DWARF exceptions with `-fno-asynchronous-unwind-tables`, or SEH exceptions for System V ABI functions; CMake checks these capabilities. WinLibs GCC 15.2.0 (`x86_64-ucrt-posix-seh`, release [`15.2.0posix-14.0.0-ucrt-r7`](https://github.com/brechtsanders/winlibs_mingw/releases/tag/15.2.0posix-14.0.0-ucrt-r7)) uses DWARF. [MSYS2 UCRT64 GCC](https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-gcc) 16.2.0-6 uses SEH. Add the selected toolchain's `bin` directory to `PATH` before configuring.
- Windows antivirus software can block or quarantine the executables that the relinker tests create and run, which fails `optional_plt`, `empty_tls`, `windows_address_space`, `windows_bss`, `windows_fixed_base` and `windows_icon`. CTest sets `TMPDIR`, `TEMP` and `TMP` of the relinker tests to `core/relinker/test-temp` in the build directory, so setting them before running `ctest` does not move these files; add that directory to the scanner's exclusions instead.
- Bitdefender Advanced Threat Defense hooks Windows calls that `sceKernelRaiseException` makes while its target thread is suspended. When the target is suspended inside ntdll's exception dispatch while it holds an ntdll lock, the hook waits for that lock and `guest_raise_exception` hangs until its timeout. A scanning exception for the build directory does not prevent it; add `guest_raise_exception_tests.exe` to the Advanced Threat Defense exceptions.
- macOS: AppleClang from the Xcode command-line tools, and Rosetta on Apple silicon (`softwareupdate --install-rosetta`). The full build selects x86-64 itself, so configure without `CMAKE_OSX_ARCHITECTURES`. The GPU tests and converted titles need the Vulkan loader and MoltenVK as x86-64 or universal binaries, such as those of the LunarG Vulkan SDK: set `DYLD_LIBRARY_PATH=<sdk>/macOS/lib` and `VK_DRIVER_FILES` to the SDK's `MoltenVK_icd.json`. Homebrew's `vulkan-loader` and `molten-vk` on Apple silicon are arm64 only and cannot be loaded. Without a loader the GPU tests are skipped. Run the GPU tests one at a time with a timeout (`ctest -j1 --timeout 30`) and leave out `agc_driver_lds_atomics64` and the flip and display tests, which open windows: a wedged GPU can stop WindowServer and restart the Mac.
- FFmpeg binaries are downloaded during configuration unless `FFMPEG_PREBUILT_DIR` is set. With the WinLibs CMake, the download fails with status 60 (`SSL peer certificate or SSH remote key was not OK`) unless `SSL_CERT_FILE` names a CA bundle, for example `C:\Program Files\Git\ucrt64\etc\ssl\certs\ca-bundle.crt` from Git for Windows 2.56 and later (`mingw64` instead of `ucrt64` before 2.56), as in CI.
- Windows: libusb's `version_describe.h` is generated by `build-aux/gen-describe.ps1`, which CMake runs with `-ExecutionPolicy Bypass`. An execution policy set by Group Policy (`MachinePolicy` or `UserPolicy` in `Get-ExecutionPolicy -List`) takes precedence over that switch ([about_Execution_Policies](https://learn.microsoft.com/powershell/module/microsoft.powershell.core/about/about_execution_policies?view=powershell-5.1)); with `Restricted` or `AllSigned` the build stops at `version_describe.h` with `running scripts is disabled on this system`. The script only starts `build-aux/gen-describe.sh` with the `bash.exe` of Git for Windows, so a `.cmd` file that runs the shell script directly can replace PowerShell for this step without changing the policy. CMake passes it the `.ps1` path as the fifth argument and the source and output paths as the sixth and seventh; configure with `-DLIBUSB_POWERSHELL_EXECUTABLE=<path of the .cmd file>`:

  ```bat
  @"C:\Program Files\Git\bin\bash.exe" "%~dpn5.sh" %6 %7
  ```

## Web converter releases

The Release workflow builds the web converter and the Linux and Windows libraries from the same commit. It tests the converter and publishes its frontend and WASM files as `web-<tag>.zip`, with the tag and commit recorded in `web-release.json`.

Pages downloads the converter and both library archives from one release selected through GitHub's latest-release API. `release.json` records the same tag and commit. Missing, corrupt or mismatched assets fail the Pages job before deployment. Releases made before the web asset was added need a new release; Pages does not combine them with a converter built from `main`.

Changes to the converter or its frontend reach Pages through a release. Progress reports still come from `main`. For local development, build `relinker_web` with Emscripten and run `python3 tools/test_web.py --build build-wasm`. To stage a complete published release without compiling, run `python3 tools/build_web.py --build build-wasm --release`; `--libraries` is an alias for this mode.

## Commands

```sh
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=gcc -DCMAKE_CXX_COMPILER=g++
cmake --build build --parallel
cmake --build build --target libs --parallel
```

On macOS, configure with AppleClang instead:

```sh
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
```

`libs` is a custom target: every library under [core/libs/prx](../../core/libs/prx) is built with
`EXCLUDE_FROM_ALL`. With the default `BUILD_TESTING=OFF`, the default build does not produce them,
so the explicit `--target libs` step is required. With `BUILD_TESTING=ON`, the default full build
also builds `libs` through the `patched_libraries_tests` dependency. Titles load the patched `.prx`
files from `build/core/libs/libs`; running a title after a library change without rebuilding `libs`
therefore tests the previous binaries and can show no effect at all.

[Relinker usage and runtime layout](../user/USAGE.md).

## Windows setup and troubleshooting

The full build also requires Python 3 for glslang and Git for Windows with Bash for libusb's version-header generation. A minimal Git installation without Bash is insufficient for the full build.

For MSYS2, install `mingw-w64-ucrt-x86_64-gcc` with `pacman -S mingw-w64-ucrt-x86_64-gcc` and use `C:\msys64\ucrt64\bin` in PowerShell. Adjust the prefix for a Scoop installation of MSYS2. Use a separate build directory for each toolchain, and select both `gcc` and `g++` from the same installation.

The [Windows MSYS2 workflow](../../.github/workflows/windows-msys2.yml) builds and tests the full runtime nightly at 08:23 UTC and can be started manually with `workflow_dispatch`. The regular Windows build uses WinLibs.

Scoop's standalone GCC 15.2.0 package cannot build the runtime: disabling SEH selects SjLj exceptions, and its SEH backend cannot compile System V ABI catch handlers. Use MSYS2 UCRT64 or a DWARF-capable WinLibs distribution. This restriction does not apply to relinker-only builds.

In PowerShell, prepend the supported WinLibs toolchain and Git for Windows to the current session's `PATH`. Adjust the paths for the installed locations; a Portable Git installation can be used in place of `C:\Program Files\Git`.

```powershell
$env:PATH = "C:\tools\winlibs\mingw64\bin;C:\Program Files\Git\cmd;C:\Program Files\Git\usr\bin;$env:PATH"
```

If configuration reports `Could NOT find Python3` or selects an unusable interpreter, pass the absolute path to a working Python 3 executable:

```powershell
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=gcc -DCMAKE_CXX_COMPILER=g++ -DPython3_EXECUTABLE="C:/path/to/python.exe"
```

The documentation runs the Python tools as `python3`. With the python.org installer for Windows, which provides `python.exe` and the `py` launcher but no `python3.exe`, `python3` resolves to the Microsoft Store alias in `WindowsApps`, which prints `Python was not found` and exits with code 9009 (49 in Git Bash). Installs that provide `python3.exe`, such as the Python Install Manager, are not affected. In that case run these commands with `python` or `py -3`, for example `py -3 tools/check_conventions.py --base origin/main`.

If `gen-describe.ps1` fails while generating libusb's `version_describe.h`, check the Bash path printed in the build output. A WindowsApps or System32 `bash.exe` can launch WSL and fail with `WSL_E_DEFAULT_DISTRO_NOT_FOUND` when no distribution is installed. Install Git for Windows with Bash, or use Portable Git, and put its `cmd` and `usr\bin` directories on `PATH` before retrying the build. Use Bash and `cygpath.exe` from the same Git installation.

If the build stops with `fatal error: opening dependency file ...\*.cpp.obj.d: No such file or directory` for a few sources with long names, the path of an object or dependency file under `build` is at or near the 260-character Windows limit. A checkout whose path was 92 characters failed this way with `LongPathsEnabled` set to 1 in the registry; the same tree at `C:\a5` built. Clone the repository to a short path such as `C:\a5` and configure in a new build directory: a CMake build tree stores absolute paths, so moving an existing `build` directory does not help.

After `cmake --build build --target libs --parallel` succeeds, copy the toolchain's runtime DLLs beside the patched libraries:

```powershell
$toolchainBin = "C:\tools\winlibs\mingw64\bin"
foreach ($runtimeName in @("libgcc_s_seh-1.dll", "libstdc++-6.dll", "libwinpthread-1.dll")) {
    Copy-Item -LiteralPath (Join-Path $toolchainBin $runtimeName) -Destination "build/core/libs/libs"
}
```

When preparing a title's `libs/` directory, copy these DLLs with the patched `.prx` files. The Windows runtime loader does not search `PATH` for these dependencies; missing DLLs can cause error 126 even when the `.prx` is present. See [runtime layout](../user/USAGE.md#runtime-layout).

## CMake flags

Project switches accept `ON` or `OFF`:

| Flag                             | Default | Effect                                           |
|----------------------------------|---------|--------------------------------------------------|
| `-DBUILD_TESTING=ON`             | `OFF`   | Build and register tests.                        |
| `-DANYPS5_RELINKER_ONLY=ON`      | `OFF`   | Build only the relinker and its tests, without third-party dependencies. |
| `-DANYPS5_BUILD_WASM=ON`         | `OFF`   | Build only the browser relinker (`relinker_web` target). Requires `emcmake` from Emscripten and `BUILD_TESTING=OFF`. |
| `-DANYPS5_ENABLE_SPIRV_TOOLS=ON` | `OFF`   | Enable SPIR-V validation and optimization.       |
| `-DANYPS5_ENABLE_ASAN=ON`       | `OFF`   | Build with AddressSanitizer on Linux and move the guest arena out of ASan's shadow gap. |
| `-DANYPS5_ENABLE_TSAN=ON`       | `OFF`   | Build with ThreadSanitizer on Linux and link executables dynamically. Cannot be combined with `-DANYPS5_ENABLE_ASAN=ON`. |
| `-DANYPS5_USE_SYSTEM_DEPS=ON`    | `OFF`   | Resolve SDL2, freetype, Vulkan-Headers, SPIRV-Headers, glslang and SPIRV-Tools from the system instead of the submodules. |
| `-DANYPS5_RELINKER_CLI=OFF`     | `ON`    | Skip the native relinker command line (`ANYPS5_BUILD_WASM` turns it off). |
| `-DAPS5_ENABLE_TIMING_LOG=ON`    | `OFF`   | Compile frame timing logging.                    |
| `-DAPS5_ENABLE_TRACY=ON`         | `OFF`   | Build the [Tracy](#tracy) profiler client into the agc driver. |
| `-DAGC_BUILD_VISUAL_TEST=ON`     | `OFF`   | Build the standalone AGC SPIR-V visual test.     |
| `-DANYPS5_REQUIRE_CPU_LEAD_TEST=ON` | `OFF` | With `BUILD_TESTING=ON`, also register `agc_driver_sparse_dma_buf_cpu_lead`, which runs `agc_driver_sparse_dma_buf_import_tests --require-cpu-lead` and fails instead of skipping when the nonzero-lead dma-buf CPU publish is not exercised, such as on Windows or without an accessible `/dev/udmabuf`. |
| `-DANYPS5_LIBRESSL_ORACLE=ON`    | `OFF`   | With `BUILD_TESTING=ON`, download LibreSSL 2.5.4 from ftp.openbsd.org at build time, check its SHA-256 and register `guest_libressl_oracle`, which compares `libSceLibreSsl` and `libSceLibreSsl3` exports with it and prints the cases and differences per function. Without the flag nothing is downloaded. |

GCC and Clang compile libc with `-ffp-contract=off` whatever the target CPU. Toolchains that default to x86-64-v3, such as GCC 15 on Ubuntu 26.04, would otherwise fuse `a * b + c` into FMA instructions, which changes the last bit of math results that must match the console.

The [Sanitizers workflow](../../.github/workflows/sanitizers.yml) builds the full runtime on Ubuntu with `-DANYPS5_ENABLE_ASAN=ON` and UBSan (`-fsanitize=undefined -fno-sanitize=vptr`) nightly at 03:41 UTC, runs every test and can be started manually with `workflow_dispatch`. It builds only the `F16ToF32Unpack`, `F64FmaSubnormals` and `RegistrationPrepareShutdown` AGC execution tests, like the Windows MSYS2 workflow. A test that fails because of the sanitizers themselves, or because of a bug whose fix is still open, is listed with the reason in [sanitizer-known-failures.txt](../../.github/sanitizer-known-failures.txt), one test per line with its sanitizers and the reason. The job summary, written by `tools/sanitizer_report.py`, separates unexpected failures from known ones and names listed tests that passed or did not run, so their entries can be removed. To repeat a run locally, set `ASAN_OPTIONS=detect_leaks=0` and `UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1`, so that undefined behavior fails the test.

Build configuration parameters:

| Flag                                   | Value                                                              |
|----------------------------------------|--------------------------------------------------------------------|
| `-DCMAKE_BUILD_TYPE=Release`           | `Debug`, `Release`, `RelWithDebInfo`, or `MinSizeRel`.             |
| `-DCMAKE_C_COMPILER=gcc`               | C compiler name or absolute path.                                  |
| `-DCMAKE_CXX_COMPILER=g++`             | C++ compiler name or absolute path.                                |
| `-DCMAKE_C_COMPILER_LAUNCHER=ccache`   | Optional C compiler cache; requires `ccache`.                      |
| `-DCMAKE_CXX_COMPILER_LAUNCHER=ccache` | Optional C++ compiler cache; requires `ccache`.                    |
| `-DFFMPEG_PREBUILT_DIR=<path>`         | Unpacked FFmpeg package for the target platform; empty by default. |
| `-DANYPS5_NODE=<path>`                 | Node.js 26 or newer that runs the memory64 Emscripten tests `guest_long_double` and `emscripten_module_unwind`; `node` by default, Emscripten builds only. |
| `-DANYPS5_VIDEO_OUT_TEST_DRIVER=<driver>` | SDL video driver for the VideoOut flip tests; `windows` on Windows and `offscreen` elsewhere. |
| `-DANYPS5_AGC_EXECUTION_TESTS=<names>` | Semicolon-separated file names, without `.cpp`, of the `core/libs/prx/libSceAgcDriver/tests/execution` tests to build. Every other execution test is built from a stub that prints `skipped, this build leaves the test out with ANYPS5_AGC_EXECUTION_TESTS` and exits 77. A name with no source there fails the configure. Empty by default, which builds them all. |

SDL and FreeType settings forced by the root `CMakeLists.txt` cannot be overridden with `-D`.

With `ANYPS5_USE_SYSTEM_DEPS=ON` those libraries come from the system (on Debian and Ubuntu: `libsdl2-dev`, `libfreetype-dev`, `libvulkan-dev`, `spirv-headers`, `glslang-dev`, `glslang-tools` and `spirv-tools`). A missing package, Vulkan-Headers older than 1.4.310 (the agc driver uses `VK_KHR_maintenance8`), or an SDL2 without the HIDAPI joystick driver (sdl2-compat over SDL3, or a build with HIDAPI disabled, which breaks the pad and disk-audio tests), fails the configure with an error and never falls back to the submodule. The forced SDL and FreeType settings from the root `CMakeLists.txt` do not apply with the flag ON: the system SDL2 comes with whatever its distribution enabled. The prx libraries are shared objects, so SDL2 is linked from the system as a shared library; the default build keeps its own static SDL2. `ffmpeg-core`, `libjpeg-turbo`, `stb`, `VulkanMemoryAllocator`, `LibAtrac9`, `ogg`, `vorbis`, `opus`, `libusb-cmake`, `mbedtls`, `vgmstream`, `zstd`, `ZArchive` and, on Windows, `mimalloc` always stay bundled and still need `git submodule update --init`.

## HTTP locale tests

The Linux HTTP URI locale regression needs an ISO-8859-1 locale. With tests enabled, CMake uses host `localedef` and installed locale sources to generate a private `en_US.ISO8859-1` under the HTTP build directory. This runs from the checked-out PR tree, including when CI dispatches the workflow from `main`, and changes no system locales. `-DANYPS5_HTTP_TEST_LOCALE_DIR=<directory>` overrides generation. Only `guest_http_uri_locale` receives the private directory through `LOCPATH`. If `localedef` or its source data is unavailable, configuration reports it and leaves the test to probe installed locales. Without an effective Latin-1 locale the test explicitly skips; the CI skip audit rejects that loss of coverage. Windows requires `.1252`.

## ThreadSanitizer

A ThreadSanitizer build runs its tests with `TSAN_OPTIONS=suppressions=$PWD/tools/tsan-suppressions.txt`, which silences reports from Mesa's lavapipe, the LLVM it compiles shaders with, and PulseAudio: those system libraries are not instrumented, so ThreadSanitizer cannot see their locking. Guest memory written by the emulated GPU while a guest thread polls it, such as labels and fences, is shared without C++ atomics on purpose, as on the console, so ThreadSanitizer also reports those accesses.

## Quick syntax checks

After configuring a build directory, use `tools/check_compile.py` to check the given source files. The tool reads their compile commands from `compile_commands.json` or Ninja, preserving compilation options while dropping object and dependency output options. It handles `-MF`, `-MT`, `-MQ` and `-MJ` with separate or attached values so that unused output options do not cause false failures under `-Werror`.

```sh
python3 tools/check_compile.py --build build-relinker core/relinker/main.cpp
```

Real compile errors still fail. Syntax checks do not replace a full build and test run.

## Repeated Vulkan validation

`tools/vulkan_validation_gate.py` builds two pinned clean source worktrees into a new output directory and alternates the same focused CTests between them. Execution currently supports POSIX hosts only. Linux hardware runs establish GPU behaviour; macOS synthetic tool tests do not establish native Linux/Windows or GPU correctness. Windows is refused before creating output.

```sh
python3 tools/vulkan_validation_gate.py \
  --baseline /path/to/main FULL_MAIN_COMMIT \
  --candidate /path/to/change FULL_CHANGE_COMMIT \
  --output /path/to/new-validation-run \
  --target agc_driver_recorder_tests --target libs \
  --tests '^agc_recorder_completion_labels$' --gpu 'expected device name' \
  --repeat 20 --runtime core/libs/libs
```

Both worktrees must have the expected full commit ID and no tracked or untracked source changes. Output must be outside both worktrees and must not already exist. Each build uses Ninja, Release and `BUILD_TESTING=ON`; shared cache options can be supplied as `--cmake-arg=-DNAME=VALUE`. Test targets are explicit; the tool does not infer them. Configure and build logs, selected CTest commands, compiler/build configuration, commit IDs and hashes of selected command files and explicit build-relative `--runtime` files/directories are retained. Other dynamically loaded libraries and ignored source files are not inventoried. A clean commit alone does not identify an arbitrary existing binary, so existing build directories are not accepted.

Each iteration runs serially with `ANYPS5_REQUIRE_VULKAN=1`, `ANYPS5_NO_SHADER_CACHE=1`, `VK_INSTANCE_LAYERS=VK_LAYER_KHRONOS_validation` and the requested `ANYPS5_GPU`. The tool rejects declared test properties that override those values or the recorded `VK_ICD_FILENAMES`, `VK_DRIVER_FILES` and `VK_LAYER_PATH` values. The GPU name is a selection request, not an independent hardware measurement. Every iteration retains verbose output and JUnit, with CTest's passed/failed output-size limits disabled so diagnostics near either end of a long output are retained. Missing, disabled or skipped selected tests, test failures and the exact missing-layer phrase fail the gate, even if CTest returns zero.

The gate compares VUID and synchronization-hazard IDs per test across all baseline and candidate iterations. A new candidate ID fails; occurrence counts are reported without treating a count increase as a new violation. Existing baseline diagnostics remain visible and do not establish a clean validation run. Parsing covers standard `Validation Error/Warning:` and `VUID/SYNC-HAZARD (ERROR/WARNING / ...)` messages in JUnit test-body output, not arbitrary application formats or verbose CTest configuration text. Retain the logs for manual review of other formats. Source identity and selected artifact hashes are checked again after testing.

`report.json` records the comparison and execution order. Exit 0 means the comparison completed with no detected regression, 1 means a test/coverage/layer or new diagnostic failure, 2 means setup, attribution or incomplete evidence, and 130 means interrupted. `--test-timeout` supplies CTest's default timeout; explicit test timeout properties still apply. `--timeout` bounds each configure/build/CTest command. The active POSIX process group is killed on completion, timeout or interruption. Repetitions report observed outcomes; they do not prove absence of intermittent faults or statistical significance.

## Write watch tests

The macOS write watch can be built and tested separately, without submodules or the prx libraries:

```sh
cmake -S core/libs/tests/write_watch -B build/write-watch -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=x86_64
cmake --build build/write-watch
ctest --test-dir build/write-watch --output-on-failure
```

With `CMAKE_OSX_ARCHITECTURES=x86_64` Apple silicon runs the tests through Rosetta, which is how relinked titles run; without it they run natively. The full `BUILD_TESTING` build on macOS also registers them.

## Tracy

`-DAPS5_ENABLE_TRACY=ON` builds the [Tracy](https://github.com/wolfpld/tracy) 0.14.1 client from `3rdparty/tracy` as a shared library next to the patched `.prx` files (`libTracyClient.dll`, `libTracyClient.so.0.14.1` on Linux); copy it with them. Every `PerformanceTimer` scope of libSceAgcDriver and libSceVideoOut is a zone, every presented flip ends a frame, and the queue workers and the presenter are named threads. Connect the Tracy 0.14.1 profiler to `127.0.0.1`: the client listens only on localhost and records only while a profiler is connected. Sampling, system tracing, call stacks, code transfer and Tracy's crash handler are disabled. Without the flag nothing of Tracy is built.

On Windows MinGW frees `thread_local` objects before their destructors run, so the Tracy client is built without `thread_local` destructors and never destroys its event queue: a thread that emitted a zone and ended keeps its event blocks (2 MiB each) until the process exits.

## Compute pipeline replay

Build `agc_compute_pipeline_replay` in the full build with `-DANYPS5_ENABLE_SPIRV_TOOLS=ON`; replay validates the captured module before calling Vulkan. Set `APS5_DUMP_COMPUTE_PIPELINES` to a dedicated empty directory before starting a title to save each uncached compute pipeline's final SPIR-V, descriptor layouts, push constant ranges, specialization values, subgroup size and creation flags before compilation. Files are named `compute-<identity>/capture.aps5cp`; identical records are deduplicated. The pipelines of the start-up f32 denormal flush probe are not captured. At 128 records or 256 MiB in total, capture turns itself off for the rest of the run after a `[compute-capture] optional capture disabled` line and the title keeps running; a single record over 36 MiB (at most 8,388,608 SPIR-V words, or 32 MiB of shader code) is an error. Capture files contain shader code and device metadata, but no guest buffers or textures; review them before sharing.

Set `APS5_DUMP_COMPUTE_MIN_WORDS` to capture only modules at or above that SPIR-V word count, for example `100000` when investigating large NVIDIA compilations. The default is `0` (all modules); values outside `0` through `8388608` fail. The filter applies only when capture is enabled.

```sh
cmake --build build --target agc_compute_pipeline_replay
build/core/libs/prx/libSceAgcDriver/agc_compute_pipeline_replay capture.aps5cp --cache-out pipeline.cache --output fresh.json
build/core/libs/prx/libSceAgcDriver/agc_compute_pipeline_replay capture.aps5cp --cache-in pipeline.cache --output imported.json
```

Use `APS5_PIPELINE_STATS=1 agc_compute_pipeline_replay capture.aps5cp --inspect --output inspection.json` to inspect the captured pipeline without dispatching it. This requires `VK_KHR_pipeline_executable_properties`, requests statistics for this replay, and prints the driver's executable and counter names, values and descriptions to stderr. Available counters depend on the driver. The JSON report marks `mode` as `inspection`, sets `pipeline_statistics` to true, records the effective `replay_pipeline_flags`, and sets `milliseconds` to null. The captured identity and original flags are retained. Inspection output is not a compilation benchmark. Replay without `--inspect` continues to reject enabled statistics or captures carrying the statistics flag. `--inspect` cannot be combined with `--write-fixture`.

On Windows use `agc_compute_pipeline_replay.exe` and prepend `build/core/libs/libs/unpatched` to the process `PATH`. `ANYPS5_GPU` selects a device by name as for the driver. The tool uses the driver's compute pipeline creation path, without recording commands, dispatching work or importing guest memory. Compile-only devices also enable supported partially-bound, variable-count and runtime-array descriptor features to replay captured layouts; ordinary runtime devices are unchanged. Binding flags are preserved independently of update-after-bind. Replay accepts the unconditional Vulkan 1.0 capabilities listed in the pinned [Vulkan registry](https://github.com/KhronosGroup/Vulkan-Headers/blob/2fa203425eb4af9dfc6b03f97ef72b0b5bcb8350/registry/vk.xml); other capabilities must be enabled by the device target. Non-Vulkan capabilities such as Kernel and unknown capabilities fail before pipeline creation. Unsupported features, non-highest variable bindings and counts exceeding layout support fail explicitly. Unsupported inputs and mismatched cache vendor, device or UUID fail explicitly. Output files must not already exist.

Each invocation creates one pipeline. With no `--cache-in`, its application pipeline cache starts empty; `--cache-in` imports a raw cache previously written by `--cache-out` (at most 64 MiB), and `--cache-out` exports the resulting cache. The title's wrapped `vk-pipelines-*.bin` format is not accepted. It does not load or save the title's usual pipeline cache. NVIDIA and other driver caches remain uncontrolled: a fresh application cache is not a cold driver cache. JSON reports the capture identity, GPU/driver identifiers, word count, cache policy and separate wall times for shader module, layouts, pipeline creation and cache work. Device initialization is outside these timings. Pipeline statistics captures and `APS5_PIPELINE_STATS` are refused because they change compilation cost.

`--fixture` compiles a tiny synthetic compute shader with specialization, sparse descriptor binding and push constant metadata; `--write-fixture DIRECTORY` saves it without opening Vulkan. It performs no GPU work and does not reproduce a title's compile workload. With `BUILD_TESTING=ON`, `agc_compute_pipeline_capture` checks serialization and rejected inputs. With SPIRV-Tools also enabled, `agc_compute_pipeline_replay` compiles the fixture with fresh and imported application caches, verifies cache rejection, and checks required subgroup support. `agc_compute_pipeline_capture_run` verifies the existing branch-past-endpgm compute fixture's output with capture disabled and enabled, then replays the captured pipelines and checks their identities and metadata. `agc_compute_pipeline_inspection` checks executable counter queries, diagnostic JSON, retained capture identity, and benchmark-mode guards; its timeout is 60 seconds. The other tests have 30-second timeouts. Runtime tests skip when Vulkan is absent; set `ANYPS5_REQUIRE_VULKAN=1` to require execution. There is no performance pass threshold.

## PM4 submission replay

Set `APS5_DUMP_SUBMITS` to a directory before starting a title to save every submission the AGC driver accepts, as it enters the driver. `index.txt` gets one line per submission: ordinal, queue, `graphics` or `compute`, serial, microseconds on the clock of the `APS5_TRACE_GPU` lines, dword count, kind, file name, the dword offsets of the waits whose value passed their compare when the submission entered the driver (`held`, which the driver then does not wait for) and the COND_EXEC and predicated indirect buffer ranges as `start:end` dword offsets (`-` for none). `submission_<ordinal>.bin`, with the ordinal zero-padded to six digits (`submission_000001.bin`), holds the dwords the driver copied, with indirect buffers inlined. A REWIND tail is listed as `rewind` with the serial of its submission, a suspend point as `suspend` without a file. The index is truncated on the first submission. A failed write puts the driver in its failed state: the call that made the submission throws after the submission was queued, and every later driver call throws the same error. Unset, the switch costs one test per submission; set, one copy of the commands per submission before the driver lock, the ordinal, time and held waits under it without allocating, and the files written after it. A capture holds command buffers only, no guest memory. An index written before the held and conditional columns (column line `ordinal queue type serial time_us dwords kind file`) is still read, with both unknown.

`agc_pm4_replay <directory> [--full]` decodes the capture offline with the driver's packet decoder, validator and store decode (`Pm4::DecodeStores`) and reports each WAIT_REG_MEM, WAIT_REG_MEM_64 and REWIND as released, unreleased or unknown. It does not model cross-queue timing: a wait is released only when the capture alone proves that the driver releases it, and unknown, with the reason, whenever its outcome depends on when the stores of another queue run, since a store of another queue can run before, between or after the stores of the waiting queue whatever order the submissions entered the driver in. A memory wait is released when its compare always passes; when it was held at submit; when the last store to the awaited bytes before it on its queue (in that submission or an earlier one) covers them with a value the compare accepts, is not conditional, and no other queue stores to any of those bytes anywhere in the capture (current value); or when a RELEASE_MEM or WRITE_DATA label earlier in the waiting submission, one the driver keeps in its label history (4-byte aligned, at most 64 bytes, not conditional), stores a value the compare accepts and fewer than 4 other stores to the awaited bytes can run between it and the wait (label history). The driver keeps the last 4 label stores per dword over all queues (`LabelHistory.cpp`) and finds one there only if it ran after the waiting submission entered the driver, which the capture proves only for a store earlier in that submission. The stores counted against the history are those between the label and the wait on the waiting queue and every store of another queue to the awaited bytes, whatever its submit order; stores later on the waiting queue run after the wait. A REWIND is released when its tail is in the capture. One that was valid at submit without a tail in the capture is unknown, because the driver reads the valid bit again when the queue reaches the REWIND. A memory wait is unreleased when it was not held at submit and no store in the capture that can run before it may write a value the compare accepts (a store of part of the awaited bytes or of a value known only at run time may): the GPU does not release it, but a CPU store could, and so could a shader store, since the capture holds neither. A REWIND without a tail that was not valid at submit is unreleased. Every other wait is unknown: `unknown: depends on cross-queue timing (stores on queue X at #...)` when another queue stores to the awaited bytes; otherwise when the last store before it on its queue is conditional (COND_WRITE, inside a COND_EXEC range or a predicated packet), stores a value known only at run time or only part of the awaited bytes, or overwrites an accepted store that the capture does not prove is still in the label history (one in an earlier submission, one the history does not keep, or one with 4 or more stores after it). When the index has no held column, a wait that would be unreleased is unknown, since its value may have passed the compare at submit; without the conditional column every packet after a COND_EXEC or predicated INDIRECT_BUFFER is conditional to the end of its submission. The report counts the waits per outcome and route and the unknown waits that depend on cross-queue timing, says when the index lacks the columns, lists up to 32 unreleased and then unknown waits, newest first, each with the packets around it and the stores to the awaited bytes that decide it (for another queue, the 4 nearest the waiting submission in submit order), then the last submissions of each queue. `--full` lists every wait and prints every packet. A packet the driver rejects means the capture is corrupt and fails the analysis. The exit code is 1 when a wait is unreleased and 2 on errors.

```sh
cmake --build build --target agc_pm4_replay
build/core/libs/prx/libSceAgcDriver/agc_pm4_replay submits
```

On Windows use `agc_pm4_replay.exe` and prepend `build/core/libs/libs/unpatched` to the process `PATH`. With `BUILD_TESTING=ON`, `agc_driver_pm4_replay` captures submissions made with the libSceAgc command builders through the driver and checks the index, the held waits, the conditional ranges, the dwords, the decode and the outcome of each wait, then checks hand-made captures: each release route; a store of another queue to the awaited bytes that entered before or after the store of the waiting queue (unknown); the label history limit, with the stores after the label on the waiting queue or on another queue; a fill the history does not keep; a store in an earlier submission overwritten later; later stores, rejected values and a missing rewind tail (unreleased); the six captures of the reviews (a two-queue deadlock, a store of 0 behind a released wait on another queue, with and without that wait held at submit, and labels pushed out of the history by stores of another queue), none of whose waits may be released except the one held at submit; five groups of waits in eight submission orders with identical outcomes; an index without the held and conditional columns; corrupt captures; then a failed write. `agc_driver_pm4_replay_tool` runs the tool on the driver capture and checks its exit codes and report.

## Frame capture and replay

On Windows and Linux, set `APS5_FRAME_CAPTURE` to a directory to record a few frames of a title at the AGC driver boundary, then replay them with `agc_frame_replay` through any build of the driver with no title running. From the start of the process the driver keeps every shader registration and ABI resolution, video output registration and EOP flip reservation. At the frame boundary picked by `APS5_FRAME_CAPTURE_AT_FLIP` (default 1), or by the appearance of the file `APS5_FRAME_CAPTURE_TRIGGER` names (a number in it replaces the frame count), it waits for the driver to go idle and writes every committed, readable allocation of the guest allocation registry, the title's image included, as zstd chunks without their all-zero 64 KiB blocks. A frame ends at a CPU flip or at a submission that flips (a flip packet, or the EOP release of a reserved flip token); the reservation itself only records its token. For the next `APS5_FRAME_CAPTURE_FRAMES` (10) frames it records each submission (queue, command buffer address and size), flip and suspend point with the thread that made it and the accepted and completed serials, each preceded by the guest pages the write tracker saw the CPU write since the previous call that handed work to the GPU (`GuestMemory::CollectWrittenBlocks`, per 4 KiB where the tracker kept page stamps), read once the submissions already accepted have completed (a recorded submission, flip or suspend point reaches the driver before the recorder takes its next call, so that wait covers every call recorded before the delta); an allocation the registry gained after the snapshot is recorded there as a new range with its nonzero 64 KiB blocks. A submission ends a frame only when it flips itself, not when another thread's submission flipped while it was being submitted. Shader registrations and ABI resolutions only collect the blocks of the shader header and the arrays it points to, and the pages of the title's image only when their content changed. At the end it stores each display buffer the title presented, decoded, as a reference image. Without the guest write watch (`APS5_NO_WRITE_WATCH`, or no write watch on the host) the capture throws when it starts, since it could not record CPU stores. A capture is `calls.bin`, `memory.bin` and `capture.json` (commit, switches, sizes, warnings), and the recorder stops with a warning when its volume has less than 4 GiB free. A 20-frame capture in the Demon's Souls Nexus is 5.3 GiB of snapshot and 11.5 GiB of deltas before compression, 3.9 GiB on disk.

`agc_frame_replay <capture> [--no-pace] [--no-release] [--release-after-ms <n>] [--no-synthesize] [--strict] [--dump <address>:<bytes>:<file>]... [--frames <dir>]` maps the captured ranges at their addresses and registers them with their access (a range the replaying process already maps writable, such as the driver's fixed memory, is only refilled, and a non-GPU range it uses itself is skipped and counted), repeats the registrations, then replays the calls of each captured thread on a thread of its own, started in captured order. Before a call that hands work to the GPU it waits until no more submissions are in flight than when the title made it (`--no-pace` turns this off). Titles release GPU waits from threads that never call the driver, so when the driver completes nothing for 3 ms the replay reads the waits its queues are blocked on (`AgcDriverAwaitedWaits`) and writes the next recorded CPU value of the awaited dword that satisfies the compare, else the last earlier one, else a value derived from the reference (`--no-synthesize` turns this last step off). It prints one JSON line with the frame count and times, the submissions, the pacing wait, the released waits and how many were derived, the submissions that never completed and, for captures with reference images, the share of identical pixels and the largest channel difference of the replayed display buffers (`--frames` writes both images). Effects that depend on timing (temporal antialiasing, particles) make pixels differ, so expect a visual match rather than identical frames. Replay times follow the GPU clock state: lock the clocks (`nvidia-smi -lgc`, `-lmc`) when comparing two drivers.

```sh
cmake --build build --target agc_frame_replay
build/core/libs/prx/libSceAgcDriver/agc_frame_replay capture
```

On Windows use `agc_frame_replay.exe` and prepend `build/core/libs/libs/unpatched` to the process `PATH`. With `BUILD_TESTING=ON`, `agc_frame_capture` checks the file format (round trip, zero-block elision, truncated and corrupt files), and, on Windows only, `agc_driver_frame_capture_eop` reserves and submits six EOP flips with `APS5_FRAME_CAPTURE_FRAMES=3` and checks that the capture starts after the first flipping submission and holds three frames of one reservation and one submission each, then that a flipping submission on another thread leaves this thread's flip count unchanged, and, on Windows only, `agc_driver_frame_replay` captures two frames of CPU writes followed by DMA copies, the second from a block committed during the capture, replays them in `agc_frame_replay` and compares the copies.

## Pipeline statistics

Set `APS5_PIPELINE_STATS=1` to capture and print driver statistics for each newly created graphics or compute pipeline. This requires `VK_KHR_pipeline_executable_properties` and `pipelineExecutableInfo`; an unsupported device fails with an error. Statistic names and units are driver-specific. Capturing statistics can increase pipeline compilation cost. The setting is disabled by default.

## GPU memory accounting

Set `APS5_TRACE_MEMORY_BUDGET=1` to track Vulkan allocations by device, heap and allocation category. Dynamic storage-cache budget queries print `[gpu-memory]` reports at most once every 10 seconds. Reports contain byte counts for active and retained memory, the driver's heap budget and usage, and the storage budget's sampled, cached, reserved, available and cap terms. Image reuse changes the category without counting another allocation; slab free slots and pooled buffers count as retained memory. Host fallback allocations count against the heap actually used.

`unattributed_usage` is reported heap usage above tracked allocations; `tracked_above_usage` is the reverse difference. Vulkan heap usage is an estimate and includes driver allocations, so neither difference identifies a specific allocation class. `complete=0` means accounting metadata could not be recorded consistently. The switch records allocation lifetimes and leaves cache limits and eviction unchanged. A forced `APS5_TEXTURE_CACHE_MIB` bypasses dynamic budget queries and their reports.

## Device loss reports

On a device that supports `VK_EXT_device_fault`, the first `VK_ERROR_DEVICE_LOST` prints the driver's fault description, the faulting addresses and the vendor fault codes as `[device-fault]` lines. Set `APS5_GPU_CHECKPOINTS=1` to also record a `VK_NV_device_diagnostic_checkpoints` marker with the program address before each compute dispatch; the report then lists the last markers the GPU reached. On a device without that extension but with `VK_AMD_buffer_marker` (RADV and AMD's own drivers), each compute dispatch instead writes a numbered marker into a host-visible buffer when the GPU reaches it and another when it finishes; the report then names the programs of the last dispatch reached, of the last one finished and of up to eight dispatches between them. Checkpoints are disabled by default and ignored on devices without the extension.

## Worker sampler

Set `APS5_SAMPLE_WORKER=<file>` to sample queue worker 0 every millisecond (in practice every timer tick). Every 20 s and at exit it writes `<file>`, one `module offset self inclusive` line per sampled address, and `<file stem>.collapsed.txt`, the worker's whole stacks in the collapsed format that speedscope.app and flamegraph.pl read: one `frame;...;frame count` line per distinct stack, root first, each frame as `module+0xRVA`. A walk that ends before the thread's root starts with `[truncated]`. The `#` lines give the samples, the walk depth (64 frames), the truncated walks, the mean and longest time the worker was suspended, and the size and PE timestamp of each module, to check the binary a file is symbolized against. A frame with `.pdata` is stepped by `RtlVirtualUnwind`; any other frame by its DWARF record in `.ehfram`, the unwind data the libraries are built with. Those steps read only inside the worker's stack, and a module is indexed after the worker resumes, the first time a walk meets it. `python tools/symbolize_samples.py <file stem>.collapsed.txt --libs <libs directory>` names each frame from the COFF symbols of the module that ran, or from its export table when it has none, and leaves a module unsymbolized when its size or timestamp differs from its `# module` line or when it has none (`--unverified` symbolizes it anyway); `--since <earlier copy>` keeps only the samples taken after that copy, `--out` writes the named stacks and `--demangle` uses `c++filt`. Given `<file>`, it lists functions by self and by inclusive samples, where a function's inclusive count is the sum of its addresses' and overcounts a function that is on one stack more than once.

`APS5_SAMPLE_COMMITTER=<file>` samples queue 0's draw committer the same way and writes the same two files. The committer records the draws the worker hands over (`APS5_PIPELINED_DRAWS`), so when the worker's stacks wait in `DrawPipeline::Enqueue`, its stacks show what bounds the frame. It starts with the first pipelined draw; with `APS5_PIPELINED_DRAWS=0` nothing is sampled.

`APS5_SAMPLE_THREADS=<file>` samples every thread of the process every 2 ms and writes the 40 hottest addresses of each busy thread to `<file>`, 12 frames deep and through `.pdata` only, under a `thread <id> samples <n>` line per thread and with the same `# module` lines. The samplers exist only on Windows; the addresses are symbolized offline with `tools/symbolize_samples.py`, which adds up all threads or, with `--thread <id>`, keeps one.

## Performance trace

Set `APS5_TRACE_FRAMES=<start>:<count>` to record `<count>` presents from present `<start>` (counted from 0), or `APS5_TRACE_SECONDS=<start>:<length>` to record from the first present at least `<start>` seconds after the first present until the first present `<length>` seconds later. Both values are whole numbers and the length is above 0; a malformed value, or both switches together, fails the first present. The window opens and closes at presents.

Set `APS5_TRACE_EVENTS=<count>` to change the buffers of the queue workers, the presenter, the draw committer of pipelined draws (`APS5_PIPELINED_DRAWS`) and the draw finisher (`APS5_DRAW_PIPELINE`) for a frame or seconds window. The count is a whole number from 1 through 4,194,304; the default is 262,144. An invalid value fails when one of these threads first binds to the trace, before recording. Each buffer uses `count * sizeof(TraceThread::Slice)` bytes (currently 40 bytes per event, since each slice also carries its recorder batch): 10 MiB at the default, 120 MiB at `3145728`, and 160 MiB at the maximum, per thread. The buffers are allocated even while waiting for the window to open, and formatting the trace uses additional memory. Shader preparation keeps its explicitly sized 32,768-event buffers, as does a title thread named `title` that binds one the first time it registers a shader or resolves a shader ABI. The GPU range limit stays 262,144. Summary-only sessions allocate no event buffers and do not read this setting. A larger buffer can still fill; use a shorter window or increase the count within the bound.

Inside the window the queue workers, the presenter and the draw committer and finisher record every `PerformanceTimer` scope and stage as a complete event named after its frame timing key: `Driver.WorkerWait`, `Driver.Packet`, `Driver.Packet.draw`, `Graphics.Draw`, `Driver.Present`, `Driver.Present.inflight_wait`, `Vulkan.Retire` and so on. A slice shorter than 20 us is only counted: its time is in the thread's counter `<thread> folded` (milliseconds per present) and in the summary. A thread writes a present's counter sample at its first slice after the next present, so the last present of the window has no sample; its time is still in the summary. By default, each of these threads allocates a buffer for 262,144 events when it starts; a full buffer stops that thread's recording, sets `trace_dropped` and puts an instant event `trace buffer full` on the thread's track at the start of the first lost slice (slices are appended when their outer scope ends, so that can precede the last recorded slice by up to one outer-scope length), with the number of lost slices in `args.events_lost`. When the window closes, the presenter formats the trace once and a `ProfileOutput` writer thread writes `aps5-trace-<commit>-<pid>.json.gz` (Chrome trace-event JSON, opened by ui.perfetto.dev or chrome://tracing) and appends one line to `aps5-summary.jsonl`, both in `APS5_TRACE_DIR` or the working directory. A window that is still open when the title exits writes nothing.

The summary line has `commit` and `dirty` of the build, `env` (every `APS5_*` variable; a value containing `/` or `\` is written as `<path>`), `gpu`, `driver`, `os`, `cpu` (the CPU brand string), `cpu_threads` and `memory_mib` (physical memory) of the host (all three absent on a host that is not x86 or reports no brand string), `title_id`, `title` and `content_version` from `app0/sce_sys/param.json` (only when the title has one; `content_version` is empty when the file has no `contentVersion`, or one that is not a string of at most 15 characters), `resolution` (the video output's), `window`, `presents`, `frame_ms` (p50, p90, p99 and max of the intervals between presents), `gpu_busy_ms_per_present` (the batch timestamps behind `[present]`), `worker_busy_pct` (share of the window each queue worker spends in `Driver.Packet`, `Driver.Suspend`, `Driver.EndSubmission`, `Driver.Rewind` and `Driver.Completion`), `top_phases_ms_per_frame` (the eight largest scopes and stages, without `Driver.WorkerWait`), `trace_dropped`, `trace_dropped_threads` and `trace`. `trace_dropped` is `true` when any thread lost a slice, any thread's totals table (512 scope and stage entries) was full, or the `gpu` track was full. `trace_dropped_threads` is present only then and has one entry per such thread name (threads that share a name, such as the shader prepare threads, share one entry: `events_lost` is summed, `events_full_after_s` is the earliest, `totals_full` is true if any is): `events_full_after_s` (seconds from the first present of the window to the start of the first lost slice; absent for `gpu` and, in every summary line (windowed `APS5_TRACE_FRAMES`/`APS5_TRACE_SECONDS` and `APS5_TRACE_SUMMARY_EVERY`), whenever the first lost slice starts outside the line's span of presents, including a slice whose scope began before the window opened or one lost after the window's last present), `events_lost` (slices not recorded; absent when 0; in `APS5_TRACE_SUMMARY_EVERY` lines it counts the thread buffer's losses since it started, not only those of the line's span) and `totals_full` (`true` when the thread's totals table overflowed, which makes the summary numbers incomplete; a thread with `events_lost` only has complete totals). A trace holds timings, scope names, counts and thread names; no guest memory, paths or strings of the title.

The summary's scope durations are wall time aggregated across threads. Nested scopes include their children, and scopes on different threads can overlap; adding them does not give a frame's exclusive CPU or GPU cost. Only the eight largest aggregates are listed: a missing scope or stage does not establish that it did not run or cost nothing, even when `trace_dropped` is false. `worker_busy_pct` measures occupancy in the listed scopes, including waits inside them, rather than CPU utilization. Use the full trace and separately measured thread CPU time to distinguish these cases.

The shader preparation threads are traced as well, `shader prepare`, with a buffer for 32,768 events each. A wait for the GPU mutex on a traced thread is a `GpuMutex.wait.<site>` slice (`dispatch`, `draw`, `present`, `flush` and so on, as on the `[lock]` line).

The `gpu` track holds one `batch` slice per recorder batch, from the batch's timestamp pair. With `APS5_PROFILE_GPU=1` it also holds a slice per command class range, under the class names of the `[gputime]` line (`draw`, `copy`, `fill`, `present-blit`, ...); program ranges are left out. The track keeps up to 262,144 ranges; more set `trace_dropped`. The GPU clock is mapped onto the CPU clock with calibrated timestamps (`VK_KHR_calibrated_timestamps` or the EXT version, enabled only when a trace switch is set) against the performance counter on Windows and `CLOCK_MONOTONIC` elsewhere, or `CLOCK_MONOTONIC_RAW` on a device that calibrates against no `CLOCK_MONOTONIC` (MoltenVK), taken when the window opens and when it closes, so the two clocks are matched at both ends of the window. A batch is added when the driver reads its timestamps, after its fence signals, so the batches of the last frames of the window, which complete after it closes, are missing. Without calibrated timestamps the trace has no `gpu` track, and the `[trace]` line says so.

With any of the three switches set, the recorder writes a timestamp pair per batch for the whole run, as with `APS5_PROFILE_DRAW`. Without them, a `PerformanceTimer`, a GPU mutex acquisition and a read of batch timestamps each cost one more predictable branch.

Set `APS5_TRACE_DRAW_PROGRAMS=1` (any value) to print one `[draw-programs]` line on stderr per draw, with the submission serial, the queue, and for each selected program its stage and role, the shader's code address and its entry address (`vertex/main=0x100000(entry=0x100040)`). It is for comparing the shaders a draw selects with shader-preparation failure logs; it reads no GPU state.

### Summaries for a long session

Set `APS5_TRACE_SUMMARY_EVERY=<seconds>` (a whole number above 0; a malformed value fails the first present) to profile a long session in the background without a trace. The first present opens the first interval. Every `<seconds>` seconds, at the first present at least that long after the interval opened, the presenter appends one line to `aps5-summary.jsonl` in `APS5_TRACE_DIR` or the working directory and opens the next interval at that same present, so the intervals follow each other without a gap and their `frame_ms` cover every interval between presents. The line has the fields of the window summary line for that interval only, plus `interval_start_s` and `interval_end_s` (seconds since the first present). Its `window` is `{"spec":"summary_every <seconds>","first_present":<present the interval opened at>,"ms":<span of the interval's presents>}` and its `trace` is the empty string. No event buffer is allocated: each thread keeps only the per-scope totals it already folds (a few kilobytes), and the presenter subtracts the totals of the previous interval. An interval that is still open when the title exits writes nothing.

The switch combines with `APS5_TRACE_FRAMES` or `APS5_TRACE_SECONDS`. The intervals run for the whole session and the window records its full trace on top: the event buffers are allocated and filled only while the window is open, the window's own summary line (with `trace` set and no `interval_*` fields) holds only the time inside the window, and the interval lines continue unchanged around it. Without a window switch no buffer is allocated at all. The two switches do not share a clock origin: `interval_*` is relative to the first present, as the window's `APS5_TRACE_SECONDS` start is.

Set `APS5_TRACE_BENCH=1` together with `APS5_TRACE_SUMMARY_EVERY` to also keep every interval's frame times for a benchmark report. At each interval the presenter hands the kept intervals to a writer thread, which formats and compresses the file and rewrites `aps5-bench-<commit>-<pid>.json.gz` in `APS5_TRACE_DIR` or the working directory: one JSON object with `format` (`aps5-bench/1`), the identity fields of the summary line (`commit`, `dirty`, `env`, `gpu`, `driver`, `os`, `cpu`, `cpu_threads`, `memory_mib` and, with `param.json`, `title_id`, `title` and `content_version`), `intervals_dropped` and `intervals`. Each interval has `start_s`, `end_s`, `first_present`, `resolution`, `gpu_busy_ms` (the interval's total) and `frame_us`, the whole microseconds between consecutive presents. The file keeps the last 240 intervals; `intervals_dropped` counts older ones it no longer holds. Any other value, or the switch without `APS5_TRACE_SUMMARY_EVERY`, fails the first present. The file is written to `<name>.tmp` and then moved over the previous one, so a crash or kill during a rewrite leaves the last complete report. Only the newest report waits for the writer: one handed over while an older one is still pending replaces it. The frame times cost 4 bytes per present in memory.

`python tools/trace_digest.py aps5-summary.jsonl` prints the interval lines of such a file as one row per interval (frame p50, p90, p99, max, GPU busy per present, the busiest queue worker and the largest phase) and a text sparkline of the frame p99 and of the GPU busy time; lines of window captures in the file are skipped, and changes to build, environment, host, resolution or title metadata between intervals are reported. `--json` prints the rows, the first interval's identity and the indices of identity changes as JSON.

With `APS5_TRACE_SUMMARY_EVERY` set, the recorder writes a timestamp pair per batch for the whole run and every `PerformanceTimer` scope adds its time to the thread's totals, two clock reads per scope. A thread's totals are read while it runs, so a scope that straddles an interval boundary is counted in one interval or the other.

## GPU time per command class

Set `APS5_PROFILE_GPU=1` (any value) to time the recorder's GPU work with timestamp queries and print one `[gputime]` line on stderr. `APS5_PROFILE_DRAW` alone does not print it: a batch then gets only its whole-batch timestamp pair. A timed range is a pair of bottom-of-pipe stamps that both wait for all earlier work, so a range is the time its own work adds after everything recorded before it. A batch holds at most 512 ranges, its whole-batch range included. The line is written when a batch's timestamps are read after its fence, at least 10 s after the previous line, and covers every batch read since then.

The header fields: `<n> ms of GPU time` is the sum of the program-keyed ranges only (dispatches and buffer copies, see `by program`); draws and the driver's own commands are not in it. `in <n> batches` counts the batches read. `batch <n> ms first to last command` sums the whole-batch ranges, from the stamp written when the batch opens (it waits for the batches before it) to the stamp written at `Submit`. `classes <n> ms` is the plain sum of every class range, including `present-blit`, which runs outside the batches. `all ranges <n> ms` is, per batch, the union of its class and program ranges, with overlapping time counted once; `present-blit` is not in it. `untimed <n> ms` is `batch` minus `all ranges`: batch time that no range covers, including the work of dropped ranges. `<n> presents` counts the `VulkanDevice::present` calls since the previous line. `<n> ranges dropped at the 512 cap` counts ranges refused because their batch was full.

A class range covers a command together with its own barriers. In `VulkanDevice::CopyBuffer` the `copy` class range spans the leading barrier, the transfer and the trailing barrier, and the program-keyed range sits inside it around the transfer alone, so the transfer counts in both `GPU time` and `classes` but once in `all ranges`. A dispatch's leading and trailing barriers are ranges of their own classes, placed before and after its program range, not around it. `GPU time` plus `classes` can therefore exceed `batch`; compare `all ranges` with `batch` instead.

`by program` lists up to 12 keys, highest time first, as `0x<key> x<ranges> <ms>ms`. A dispatch's key is its guest program address, or the program's `variantId` when the address is 0. A buffer copy's key is the program address of the copy kernel it replaces, or 0 for a PM4 DMA copy (opcode 0x50). `by class` lists every class with at least one range since the previous line as `<name> x<ranges> <ms>ms <MiB>MiB (per present x<ranges> <ms>ms <MiB>MiB)`; the per-present figures are 0 when there was no present. MiB is the byte count each range passes to `EndGpuTiming`. The classes, with the function that opens each range:

- `dispatch-lead`: a dispatch's leading barrier, when it is recorded rather than merged into the previous trailing barrier (`VulkanDevice::recordDispatch`). 0 MiB.
- `dispatch-trail`: a dispatch's trailing barrier (`recordDispatch`). 0 MiB.
- `indirect-args`: the barrier that makes an indirect dispatch's host-imported group counts visible to the indirect read (`recordDispatch`). 12 bytes per range.
- `label-run`: a run of GPU label stores (`vkCmdUpdateBuffer`, plus the queued occlusion dump folds of a per-batch run) with its barriers (`Recorder::RecordStore` for inline runs, `Recorder::closeStoreRun` for per-batch runs). Stored bytes.
- `fill`: a guest fill of host-imported memory, as `vkCmdFillBuffer` or pattern copies, with its barriers (`VulkanDevice::FillBuffer`). Filled bytes.
- `fill-clear`: a fill done as a `vkCmdClearColorImage` of a storage image, between two layout barriers (`StorageTexture::FillClear`). Filled bytes.
- `copy`: the buffer copy of `VulkanDevice::CopyBuffer`, a whole-surface image copy (`StorageTexture::CopyFrom`) and the depth plane copies to and from storage images through a staging buffer (`copyPlane` and the layered copy in `DepthSurface.cpp`). Copied bytes.
- `staging-in`: a build's copies of guest buffer regions into staging or host-copy buffers, between two barriers (`GuestBufferMemory::recordGpuCopies`). Copied bytes.
- `staging-out`: the copies of shader-written sub-ranges back into the import (`GuestBufferMemory::RecordCopyBacks`). Copied bytes.
- `draw`: for a lean draw, from its first barrier to the end of its render pass, so draws that continue the pass fall inside one range (`recordDraw`, ended by `Recorder::endOpenRenderPass`); for a recorded draw with layout transitions, from its first barrier to its download barrier (`Draw`). 0 MiB.
- `storage-upload`: detiles of guest bytes into a storage image, whole (`StorageTexture::upload`) or by changed runs (`StorageTexture::uploadWindows`), and pending units copied from an alias image (`StorageTexture::borrowUnits`). Uploaded bytes.
- `storage-writeback`: retiles of a storage image back to guest memory, by windows (`StorageTexture::writeBackWindows`) or by layers (`StorageTexture::writeBackLayers`). Stored bytes.
- `dcc-clear`: a `vkCmdClearColorImage` of a storage image whose DCC keys read as a clear, at upload (`StorageTexture::upload`) or for a fill of its key bytes (`StorageTexture::clearByKeysFill`, with `APS5_KEYS_FILL_CLEAR=1`). Surface bytes.
- `dcc-keys`: queued DCC key stores, as `0xff` fills and seed copies between two barriers (`Recorder::recordKeyStores`). Key bytes.
- `present-blit`: the presentation command buffer from its first to its last command, timed in its own two-query pool (`VulkanDevice::present`) and added when its slot retires (`Recorder::AddGpuTiming`). Width x height x 4 bytes of the swapchain extent.
- `shadow-publish`: copies of unit shadow slabs into the import, with their barriers (`recordCopies` in `UnitShadow.cpp`, reached from `PublishShadow`). Copied bytes.
- `template-refresh`: the `vkCmdUpdateBuffer` updates of a cached dispatch's changed data words, as one range from the first update to the last (`ShaderResources::refreshData`, called from `recordDispatch`). Refreshed bytes.

## Guest clock scale

Set `APS5_TIME_SCALE=<factor>` to scale `sceKernelGetProcessTime`, `sceKernelGetProcessTimeCounter` and `sceKernelReadTsc` from their first observed value. A positive factor below 1 slows guest time; a factor above 1 speeds it up. An unset, zero, negative or non-numeric value uses `1.0` (normal speed). On Windows, `sceKernelClockGettime` monotonic clock ids are scaled too; on Linux they return the native host monotonic clock unchanged. A title's own `rdtsc` instruction and `sceKernelGetTscFrequency` are unscaled, so dividing scaled TSC deltas by the reported real frequency gives guest-time intervals. Host sleeps and waits still take real time, so this is a diagnostic aid for titles whose frame or timeout logic depends on guest time; it does not speed up the emulator or GPU work. The setting is read once when the process starts.

`APS5_PAD_INPUT_FILE` command durations and reload polling use `sceKernelGetProcessTime`, so they follow the scale. At `0.02`, a 1-second injected press lasts about 50 seconds of real time, and a new command can take up to 5 seconds to be noticed.

## Driver profile lines

With `APS5_PROFILE_DRAW` set (any value), the driver prints a profile line on stderr at most every 10 s. A line either counts the last 10 s (its counters are read and cleared when it is printed; the text says `(10 s)` or `over 10 s`) or counts from the start of the process (the text says `(cumulative)`). A rate is the difference of two cumulative lines divided by the time between them.

| Line | Counts |
|---|---|
| `[rescache] revalidate` | last 10 s |
| `[texture-cache]` | last 10 s |
| `[pipecache]` | last 10 s |
| `[rescache]` (hits, misses, entries) | from the start |
| `[vk]` | from the start |
| `[indirect]` (gpu-side, cpu-side) | from the start |
| `[flip]` | from the start |
| `[fill-sync]` | from the start |
| `[buffers] descriptor elements bound` | from the start |

`[gputime]` is described above and needs `APS5_PROFILE_GPU`. Other profile lines state their window in their text or are not listed here because their counters were not checked.

## Driver thread priority

Set `APS5_THREAD_PRIORITY=high` to raise the AGC driver's queue workers and the video output presenter above the title's threads. On Linux the threads get nice `APS5_THREAD_NICE` (default -10) through rtkit; on Windows they get `THREAD_PRIORITY_HIGHEST`. `APS5_THREAD_PRIORITY=rt` asks rtkit for real-time priority `APS5_THREAD_RT` (default 10, at most rtkit's `MaxRealtimePriority`) under rtkit's policy, `SCHED_RR` by default; on Windows it sets `THREAD_PRIORITY_TIME_CRITICAL`. rtkit only grants it when the process's hard `RLIMIT_RTTIME` is at most its `RTTimeUSecMax` (200000 us by default), so a hard limit above `APS5_THREAD_RTTIME_US` (default 200000, capped at `RTTimeUSecMax`) is lowered to it and the soft limit to at most half of it. The hard limit cannot be raised again and stays lowered for the whole process even if rtkit then refuses; see [technical debt](debt/libSceAgcDriver.md#functional). There is no fallback between the modes: when rtkit or `SetThreadPriority` refuses, a queue worker reports the refusal as a driver failure, which the next submission, wait or shutdown rethrows, and the presenter's start throws it. Each raised thread logs its priority once as `[thread-priority]`. The setting is `off` by default; a value other than `off`, `high` or `rt` is reported the same way as a refusal.

## Shader recompiler

The shader recompilation logic in [core/shader/recompiler](../../core/shader/recompiler) is isolated from the rest of the project and is a pure function of its input data, designed for integration into any other project. The current CMake target also includes cache support and links a supplied runtime target, glslang, and optionally SPIRV-Tools.

## Register context tests

The x86-64 register capture and restore tests can be built separately on Linux and macOS, without submodules or the prx libraries. On macOS:

```sh
cmake -S core/libs/tests/register_context -B build/register-context -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=x86_64
cmake --build build/register-context
ctest --test-dir build/register-context --output-on-failure
```

On Linux x86-64, omit `CMAKE_OSX_ARCHITECTURES`; the full `BUILD_TESTING` build also registers these tests. Apple silicon runs the x86-64 tests through Rosetta. They cover the unwinder's register transfer, not the complete macOS runtime or guest exception handling.


## Source-built native ARM64 graphics fixture

This optional target runs the public SDK's `gpu_cube` as an ARM64-only macOS process through Vulkan/MoltenVK. It is a source-qualified fixture, not general game compatibility. The guest CPU code comes from the x86-64 ELF through the AOT compiler. The C-compiled ARM64 executable is an independent test reference only.

The fixture stores `core/aot/examples/gpu_cube/contract-recipe.json`. Before compilation, `contract_recipe.py` verifies the input hash, a canonical digest of declared facts and guard policies, and source identities, including structured provider evidence. It derives memory-base guard sites from decoded operands and pointer-argument guard sites from resolved call ABIs. The build report records the derivation separately from the declared function/import ABIs and remaining pointer-load, stack and frame-exclusion annotations. Existing guards and compiler rejection rules still apply. The recipe does not infer object lifetime, pointee layout or missing call targets; changing a hash is not a substitute for requalifying those facts.

A qualified recipe can also be expanded independently with the AOT dependency environment active:

```sh
python3 core/aot/contract_recipe.py input.elf --recipe contract-recipe.json --source-root . --output generated-contracts.json
python3 build-aot/core/aot/native_aot.py input.elf --contracts generated-contracts.json --output module.ll --object module.o
```

The first command writes the contracts and `generated-contracts.derivation.json`; it refuses existing output paths. Source paths are relative to `--source-root`. The second command still performs the compiler's semantic validation. Expanded site counts measure generated records, not recovered ABI coverage or the number of independent manual facts.


Requirements: Apple Silicon, a logged-in macOS graphical session, Apple clang 21.0.0 (`clang-2100.3.34.2`), CMake, Ninja and Python 3. The input contract is hash-bound; another compiler revision that changes the ELF is rejected and requires contract requalification. Install a native Vulkan loader and MoltenVK; the validated driver is MoltenVK 1.4.2. Set `DYLD_LIBRARY_PATH` to the directory containing `libvulkan.1.dylib`, `SDL_VULKAN_LIBRARY` to that library, and `VK_ICD_FILENAMES` to the MoltenVK ICD JSON. These are GPU driver dependencies, not another AnyPS5 checkout. Do not set `APS5_*` diagnostic overrides for the acceptance run.

```sh
git submodule update --init --recursive 3rdparty/capstone 3rdparty/pyelftools 3rdparty/ps5link-sdk 3rdparty/SDL2 3rdparty/Vulkan-Headers 3rdparty/SPIRV-Headers 3rdparty/SPIRV-Tools 3rdparty/glslang 3rdparty/VulkanMemoryAllocator 3rdparty/ffmpeg-core 3rdparty/freetype 3rdparty/stb 3rdparty/libjpeg-turbo 3rdparty/LibAtrac9 3rdparty/libusb-cmake 3rdparty/mbedtls 3rdparty/tracy 3rdparty/ZArchive 3rdparty/zstd 3rdparty/opus 3rdparty/ogg 3rdparty/vorbis 3rdparty/vgmstream 3rdparty/jxrlib 3rdparty/mimalloc 3rdparty/nghttp2
cmake -S . -B build-graphics -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64 -DANYPS5_NATIVE_AOT=ON -DANYPS5_NATIVE_GRAPHICS=ON -DBUILD_TESTING=OFF
cmake --build build-graphics --target native_gpu_cube_check --parallel 6
```

The final command builds the required native runtime, reconstructs the x86 ELF from pinned source, compiles all 14 declared functions to ARM64, links both executables, runs 600 frames each, verifies all completed flip arguments and teardown, then compares eight 1920x1080 GPU captures with exact RGB equality. Empty, frozen, missing or mismatched images fail. Each executable has a 30-second runtime limit. Output goes into a fresh `build-graphics/core/libs/native/graphics-runs/run-*` directory with `acceptance.json`, logs and images. Link manifests bind each executable to its input object, source manifest and runtime archive hashes; the two executions must use identical runtime archives. No x86 interpreter, decoder, JIT or Rosetta is linked into the generated program.

The fixture uses the SDK at `ea771e535378740b6a058b8e5419eb8a0e0e0ec8`. The explicit source variant corrects `sceAgcInit`'s argument, the 80-byte VideoOut attribute layout, context-array capacity and depth convention, and waits for actual flip completion before reusing a buffer. The original source stays unchanged. The SDK's licensed, pinned `.sb` shader containers are embedded with its own tool; this does not rebuild PSSL shader source. The generated source patch is kept with the build artifacts.

The source reference preserves the input compiler's contracted constant folding (`-ffp-contract=on`) and expands remaining `llvm.fmuladd` operations into separate multiply/add operations before ARM64 code generation, matching the input's SSE2 arithmetic. Compiling the reference with contraction disabled from the start changes two projection constants by 2 ULP and three silhouette pixels in one capture. The reference-policy tests reject unrecognized or remaining fusion; the image comparison has no numerical tolerance.

Configure the graphics build separately from the relinker-only/hello-notify build. `ANYPS5_NATIVE_GRAPHICS` uses the shared macOS platform implementation and builds only the static runtime closure needed here. Variadic formatting, x87-dependent math and strings, guest exception/context restoration and jump buffers are not supplied by this target; requiring them fails at link time. Native C++ exceptions used internally by the host runtime remain available. The fixture's mapping checks do not establish object lifetime or general pointer provenance for arbitrary binaries.

To run the platform regressions, build the default native targets with `cmake --build build-graphics --parallel 6`, then use `ctest --test-dir build-graphics --output-on-failure`. These cover heap/direct memory, clock, TLS, shared-pointer compare/exchange, socket/event queues, write-watch, reference arithmetic policy and image validation. The graphics acceptance command requires the desktop/GPU session and is separate from these CTest cases.

### Reusable AOT provider facts

`core/aot/provider_catalog.py` resolves imported functions using the NID, published library and module names, and both versions from the ELF dynamic tables. Import-table indices are local to an image and are not catalog keys. The Apple catalog in `core/aot/catalogs/apple-runtime.json` checks declaration and implementation hashes before returning reviewed contracts; missing identities remain explicit obligations. Call `require_complete` before using a resolution as the complete import set. A caller may instead supply separately qualified contracts for the reported missing entries. Startup, object lifetimes and final native linkage still require consumer qualification.

`core/aot/debug_candidates.py` inventories scalar C signatures and fixed frame objects from a matching DWARF 4 companion. The output remains a candidate dossier: consumers must qualify the compilation profile and original object provenance before using it. Nonstandard calling conventions, aggregate or variadic ABIs, optimized locations, overlapping objects and ambiguous executable-section mappings remain unresolved. The final AOT compiler still validates every generated contract.

### Native controller consumer

After configuring the native graphics runtime, build and run `cmake --build build --target native_pad_input_check`. This rebuilds the unchanged public `ps5link-sdk` `pad_input` source as an x86-64 ELF, recovers matching DWARF 4 scalar ABI and frame candidates, checks the reusable provider catalog, and compiles its seven functions to Apple ARM64. The qualification profile uses O0, fixed frame pointers and pinned source; it is not stripped-binary recovery. The unsigned divisions in `append_uint` remain explicitly qualified from the constant divisor and source arithmetic.

The check compares six deterministic input/error scenarios against the same C source compiled independently for ARM64. Its test-only adapters publish input through the shared Pad provider, count sleeps, and inject user/initialization errors. Read/open errors call the real provider with invalid arguments. A separate production-provider run preserves the original 625 sleeps of 16 ms. Reports record binary/object/runtime hashes, notifications, input counts, teardown and remaining manual facts. These are simulated-input and source-translation checks, not physical-controller or console validation.

For the independent-source transfer probe, obtain `samples/hello_world/main.c` from `ps5-payload-dev/sdk` revision `f5d40f02770e9b0001dd9e18056eca70b3da8b40`, retaining its GPLv3-or-later notice. After `native_pad_input_check`, run from the repository root (replace `build` with the configured native graphics build directory):

```sh
PYTHONPATH=core/aot:3rdparty/pyelftools:3rdparty/capstone/bindings/python \
LIBCAPSTONE_PATH=build/core/aot/capstone \
python3 core/aot/examples/notification_transfer.py --source /path/to/main.c \
  --sdk 3rdparty/ps5link-sdk --linker build/core/libs/native/native_pad_linker \
  --runtime build/core/libs/native/libanyps5_native_graphics.a \
  --image-runtime build/core/aot/libanyps5_native_image.a --output-parent build/transfer-runs
```

The script checks the source hash and compares AOT against the source independently compiled for ARM64. Three catalog bindings transfer. The unprototyped `main()` is rejected by generic recovery and qualified explicitly in this source profile; its request storage is checked against matching DWARF. The probe supplies declaration-only cross headers and uses the verified ps5link CRT. It does not reproduce the original payload SDK loader. Startup, the C entry signature and host string bindings remain explicit facts.

The incremental DWARF dossier is produced with `python3 core/aot/debug_candidates.py input.elf --companion matching.o --output dossier.json` using the AOT Python environment. It retains independently recovered boundaries, source signatures, fixed frame facts and PC-scoped locations when another fact is unresolved. `facts.source_abi` describes the source type; it does not qualify an optimized internal machine ABI. `storage_candidates` and `value_locations` retain DIE and PC provenance and cannot be copied into whole-function lifetime contracts. `unresolved` identifies the stage and missing qualification. Both input bytes and companion mappings are checked on each run; changing either requires recovery again. The strict `recover_debug_candidates` API remains available for existing qualified consumers.

For the optimized controller consumer, configure the native graphics build with `-DANYPS5_PAD_OPTIMIZATION=O2`, then build `native_pad_input_check`. The default remains O0. Both profiles use the unchanged pinned SDK source and the same six deterministic input scenarios, source-compiled ARM64 reference and production sleep smoke. The minimal AOT test suite additionally compiles both profiles without requiring graphics dependencies.

`core/aot/examples/sha256_transfer.py` reproduces the external component comparison. Supply the original GPL-3.0-or-later `blackbearreloaded/ps5-native-app-boilerplate` checkout at `3ada439fa044f60c8b488678577a740761385711`; no external source is copied into this repository. Use the AOT Python environment and a built native graphics runtime:

```
python3 core/aot/examples/sha256_transfer.py \
  --source-root /path/to/ps5-native-app-boilerplate \
  --sdk 3rdparty/ps5link-sdk \
  --linker build/core/libs/native/native_pad_linker \
  --runtime build/core/libs/native/libanyps5_native_graphics.a \
  --image-runtime build/core/aot/libanyps5_native_image.a \
  --optimization O2 --output-parent /path/to/fresh-component-results
```

Repeat with `--optimization O0`. The component's original source and header hashes are checked before compilation. Each profile checks 64 combinations of known/random messages and stream chunk sizes against Python hashlib and an independently compiled native C reference, including block boundaries, output guards, hexadecimal conversion and comparison errors. The wrapper adds only an unused main for ELF packaging; the test calls the converted component functions. Scoped debug locations remain candidates. The qualified C source/profile supplies ABI and lifetime preconditions; compiler dataflow still checks each actual machine frame, including the optimized early-return path.

A holdout uses the unchanged MIT-licensed musl `src/string/memcmp.c` from the `AssemblyScript/musl` mirror at `aad50fcd791e009961621ddfbe3d4c245fd689a3`. Download the source and its COPYRIGHT from that revision separately, then replace `--source-root` with `--holdout-source /path/to/memcmp.c`. The hash is checked, and 108 buffer/length/alignment cases plus alias checks run against a bytewise oracle and an independently compiled native reference. No compiler rule was added for this input.

Set `ANYPS5_AOT_SHA256_SOURCE_ROOT` and/or `ANYPS5_AOT_MEMCMP_SOURCE` when configuring the native graphics build to register the corresponding O0/O2 component tests with CTest. Build `native_pad_linker` and `anyps5_native_graphics` first. These optional tests consume caller-supplied source files and never download dependencies during configure or test execution.

Each component receipt binds the source, linked input, generated object, contracts, native libraries, runtime archives, compiler and linker identities. The same symbol-free ELF is also analyzed without its companion; that report retains missing boundaries/ABIs and is not converted into an executable contract. Automated elapsed time covers build and acceptance only. Manual qualification time and port-wide speedups are not inferred from test or annotation counts.

`python3 core/aot/bundle.py bundle-manifest.json --output /path/to/fresh-bundle` converts a closed module graph to namespaced native objects and `registry.cpp`. The manifest schema is `anyps5.aot.bundle.v1` with `main` and `modules`. Each module record has `id`, numeric `version`, relative `input` and `contracts` paths, and a `dependencies` map of module IDs to required versions. Paths remain beneath the manifest directory; input hashes must match each qualified image contract. Dependencies must match DT_NEEDED and form a reachable acyclic graph. GNU symbol version tables and ambiguous/interposed exports reject.

Functions retain their qualified scalar machine ABIs. Data imports require `data_imports` entries with `name`, byte `size` and qualification `evidence`; the provider's bounded ELF object must match. SCE bindings compare NID plus library/module names and versions rather than local encoded indices. Standard ELF bindings use the declared dependency scope and unique default-visible symbols. Code/data namespaces prevent equal guest virtual addresses in different images from becoming the same native storage.

Link the generated objects and registry.cpp with `anyps5_native_image`. `NativeAotCompiledBundle_nid_no_patch` returns the validated registry. It checks module identities, versions, reachable dependency order, data ownership and function membership; lookup specifies module, version, symbol and kind. Only the main image may register process parameters. Arbitrary runtime loading and unloading are not supported. Those inputs continue to reject until their separate lifecycle/TLS lowering is selected.

Bundle-owned lifecycle reads INIT/PREINIT/INIT_ARRAY and FINI/FINI_ARRAY from each input. Array entries must have relative relocations to qualified returning `void()` functions. PREINIT is limited to the manifest's main module. Lifecycle fields were introduced in descriptor version 2; TLS/thread ownership requires version 3. `Start()` runs main preinitializers, then each dependency's INIT followed by its INIT_ARRAY; repeated successful Start calls do not repeat initialization. `Stop()` runs modules in reverse order, each FINI_ARRAY in reverse followed by FINI, and is idempotent after completion. A failed initialization finalizes only modules whose full initialization completed, makes the bundle non-restartable and preserves the failure. Cleanup failures are reported; a partially initialized module has no automatic rollback guarantee. Explicit Stop is required; registry destruction does not invoke guest code.

A module with PT_TLS opts into `tls_model: "general-dynamic"`. TLS templates, zero-fill, alignment and DTPMOD64/DTPOFF64 pairs are checked before lowering. TLS indexes must reside in immutable native data, and resolver calls must pass one of the verified image indexes. A qualified `__tls_get_addr` import binds to `Aps5GuestTlsGetAddr_nid_no_patch` with `ptr(ptr)` ABI and `tls_resolver: true`. Cross-module TLS imports declare `size` and `evidence` in `tls_imports`; the bundle derives the owning descriptor and offset from the matching provider. The native POSIX helper reuses the existing guest TLS implementation, without executing the x86 allocation stubs. Local/initial-exec addressing and arbitrary resolver indexes remain unsupported.

Descriptor version 3 includes TLS ownership and the qualified SysV `ptr(ptr)` entry points usable by guest threads. The native graphics runtime exports `NativeAotPthreadCreate_nid_no_patch` and `NativeAotPthreadJoin_nid_no_patch`, which delegate to the existing AnyPS5 providers. This profile admits default joinable threads. A bundle lease remains held until join completes, including host TLS destruction; Stop rejects unjoined guest threads. Worker exceptions are reported by join after releasing its ownership. Main-thread TLS is released after finalizers. Detach, cancellation and alternate exit/control-transfer paths are not qualified by this profile.

An optional module `guards` record contains `policies`, the original `facts_sha256` and `sources`. Original facts/source identities are checked before binding; guard sites are then derived against the namespaced contracts. Unmatched imports require explicit `host_binding_evidence` or the existing native binding qualification. Resolver search uses the complete closed startup group and rejects interposition ambiguities. Linked DWARF can be inspected explicitly with `debug_candidates.py --linked-debug`; this avoids applying unsupported object-file TLS debug relocations and retains linked-image provenance.

### Modular native consumer

Configure the native graphics build with `ANYPS5_AOT_SHA256_SOURCE_ROOT` pointing to the pinned checkout above and either `ANYPS5_AOT_MODULE_ELF_LINKER` pointing to LLVM `ld.lld` or `ANYPS5_AOT_MODULE_ZIG` pointing to Zig 0.14.1. The ELF linker is an offline fixture tool, not a runtime dependency. Then run:

```sh
cmake --build build-graphics --target native_module_bundle_check
```

The command builds three x86-64 ELF shared images from `core/aot/examples/module_bundle`, with separate namespaces, a dependency chain, shared data, initializer/finalizer arrays and general-dynamic TLS. Linked DWARF supplies candidates under the recorded C compilation profile. The SHA-256 source remains unchanged and external. Each image is converted separately, then linked with the native registry and production AnyPS5 thread providers into an ARM64-only executable. A second executable compiles the same C sources directly for ARM64.

Four pairs of guest-created workers verify initialized/zero-filled and cross-module TLS, distinct simultaneously live blocks, shared-data binding, join results and surrounding memory guards. Digests are compared with Python hashlib, and observable output is compared with the independent C build. An injected initializer failure verifies rollback of completed modules. Both paths check initialization/finalization order, no outstanding guest threads and native process execution. Fresh artifacts and receipts go under `core/libs/native/module-runs`; the optional `native_module_bundle` CTest rebuilds the fixture and reruns acceptance without downloading external sources.

This source-qualified closed bundle does not establish arbitrary Sony PRX startup, dynamic unload, guest C++ exceptions, cancellation, a general memory-ordering model or game compatibility. Thread failure/race unit tests use controlled provider substitutes; the modular consumer separately exercises production create/join. Recorded elapsed times are execution receipts, not a comparative performance benchmark.

### Whole-image guest-state AOT and C++ profile

`core/aot/guest_emit.py input.elf --output fresh-ir` produces ARM64 LLVM IR shards and an image descriptor for a position-independent x86-64 ELF. Run it in the existing AOT Python environment with Capstone and pyelftools. Compile every emitted `.ll` using `xcrun clang -c -O2 -arch arm64`, then link their objects with `core/libs/native/NativeAotGuest*.cpp` and `NativeAotGlibc*.cpp`, using `xcrun clang++ -std=c++20 -O2 -arch arm64 -Icore/libs`. The runtime targets Darwin and binds the declared glibc x86-64 imports. `--inventory` permits incomplete output for diagnosis; that output is not a qualified executable.

This path preserves guest registers, memory layout and a separate guest stack in native generated code. It differs from the signature-qualified compiler: internal functions do not need reconstructed C signatures, but guest state and indirect-target lookup remain runtime costs. There is no runtime x86 decoder, interpreter or code generator. Inputs requiring a missing provider or unsupported instruction fail explicitly.

The C++ increment adds LSDA-derived landing-pad/resume entries, static TLS variant II, raw x87 80-bit load/store forms and naturally aligned locked integer RMW/CAS. Guest unwind and exception support linked into the ELF are converted alongside the program. The provider layer covers the tested C locale, wide-character, synchronization and image-query boundaries; it does not provide general pthread create/cancel/detach or dynamic module loading. This is separate from the typed bundle's default-joinable thread adapter.

After configuring the AOT test build, run `ctest --test-dir build -R native_aot_guest_lowering --output-on-failure`. The Apple instruction lab compares the converted code with x86 execution under Rosetta. An additional specification-based CMPXCHG test checks all arithmetic flags and partial-register results independently of Rosetta, whose non-ZF results differ in the observed cases. Provider tests, TLS, nonlocal returns and unsupported/misaligned accesses are separate cases. Passing these tests does not qualify ordinary shared-memory ordering or all C++ exception ABIs.

For qualified concurrent glibc inputs, pass `--concurrent` to `guest_emit.py` and rebuild every IR shard and the descriptor together. This enables the conservative ordered-normal-memory profile required by `pthread_create`; its preconditions and exclusions are in [AOT technical debt](debt/aot.md). The descriptor version is 9 ([checked at load](../../core/libs/native/NativeAotGuest.cpp)); stale guest-state objects must be regenerated, including the expanded YMM state. Run `ctest --test-dir build-aot --output-on-failure -R native_aot_guest_lowering` on Apple Silicon to exercise real guest workers, TLS isolation, atomic contention, message passing, fenced store buffering and independent reads.

`--abi sce-app` selects the SCE application entry contract explicitly; `glibc` remains the default. The image descriptor records this choice and a mismatched launcher is refused before entry. `NativeAotGuest::StartSceApplication` calls the original entry with an argc/argv parameter block in RDI, a null optional teardown callback in RSI and an aligned guest stack. It requires separately qualified SCE providers; the glibc launcher is not a substitute. This adapter does not implement PRX loading or make the independently inventoried homebrew executable: VEX/cache semantics and the supplied libc module remain outstanding.

The concurrent profile defaults to `--ordered-access atomic` to use volatile sequentially consistent LLVM atomics for naturally aligned scalar accesses. The alignment check retains the fenced path for unaligned addresses; `--ordered-access fenced` remains available as the conservative reference. Version 5 also fences provider/callback transitions and CPUID when concurrency is enabled. This profile still requires the normal-memory and provider-buffer qualifications in AOT technical debt. It is not a general x86 TSO proof or a game-performance claim.

For a separately qualified zstd corpus, `core/aot/examples/zstd_benchmark.py` compares supplied ARM64 AOT/native and x86-64 Rosetta executables. Pass `--aot`, `--arm64`, `--x86`, `--decoder`, `--dataset` and a fresh `--output` JSON path; `--baseline-aot` adds another AOT implementation. It validates compressed outputs before alternating timed runs and records hashes, wall/CPU time and peak RSS. `--single-thread` also disables asynchronous I/O on every variant. Source and feature equivalence must be qualified separately. These are warm CLI measurements, not cold-cache, isolated kernel or game benchmarks.

The guest glibc bridge can also qualify an adapted jq CLI without Oniguruma. Build a source-equivalent ARM64 reference separately, then compare results, errors and exit codes with `python3 core/aot/examples/jq_transfer.py --aot /path/to/aot-jq --reference /path/to/arm64-jq --output /path/to/new-receipt.json`. Source archives, converted binaries and receipts stay outside the repository. This comparison does not establish arbitrary glibc libm bit equivalence or console compatibility.


### Independent bzip2 transfer

The `core/aot/examples/bzip2_transfer.py` checker accepts an AOT executable, a
source-equivalent ARM64 reference and a fresh output receipt (`--help` lists
the arguments). It covers levels, round trips, invalid/truncated streams,
concatenated members and file replacement with mode and timestamp preservation.
Python's independent `bz2` decoder checks compressed output. Pin bzip2 1.0.8
source SHA-256 `ab5a03176ee106d3f0fa90e381da478ddae405918153cca248e682cd0c4a2269`
and record both build configurations. The tested input is a whole-program
ELF with section metadata removed. This is an adapted consumer, not an unseen
transfer after these changes; it makes no performance claim.

`guest_emit.py --concurrent --memory-epochs` builds both private and ordered versions ahead of time, with checked boundary promotion and scalar provider bindings. `--seal-image` additionally requires mapping-stable providers and forbids remapping the image; it can specialize verified immutable dispatch tables. Both options require the glibc startup ABI and exclude tracing. Keep the ordinary `--concurrent` conversion as a differential reference; compare final executable hashes and output before timing. These options do not establish private ownership for worker buffers.

`--optimize-calls` applies the qualified scalar provider calls and sparse register writeback without enabling memory epochs. It also permits private REP copy/fill recognition in the explicitly single-thread profile. Tracing and non-glibc startup reject this option. The single-thread runtime still rejects guest worker creation; use `--concurrent` for workers.

### Original SCE package on Apple ARM64

The optional `original_sce` example converts the original application and supplied
`libc.prx` from the public [PPSA99999 release](https://github.com/blackbearreloaded/ps5-native-app-boilerplate/releases/tag/01.000.000).
Use `PPSA99999.zip` with SHA-256
`44dc91e346a6db7d1c5f60fb0931bfd3aa5d9a048478081d4994185796c0dc7c`.
Extract `eboot.bin` and `sce_module/libc.prx` with that project's
`ps5-native-tool self --extract --file INPUT --out OUTPUT`. The example checks
the resulting ELF hashes. Keep the package, tool and source checkout outside
this repository. The source checkout must contain tag commit
`c93771e0f9bf4f0993c3c317d7df4cc01888fb72` and its qualified import manifest.

First build `anyps5_native_graphics` using the native graphics configuration
above. Then generate the application objects and bindings, using fresh output
folders and absolute paths for the CMake cache option:

```sh
python3 core/aot/examples/original_sce/build.py --app /path/app.elf --module /path/libc.elf --source-root /path/ps5-native-app-boilerplate --native-library /path/build/core/libs/native/libanyps5_native_graphics.a --output /path/original-artifacts
cmake -S . -B /path/build -DANYPS5_NATIVE_SCE_ARTIFACTS=/path/original-artifacts
cmake --build /path/build --target native_sce_package
python3 core/aot/examples/original_sce/reference.py --source-root /path/ps5-native-app-boilerplate --output /path/reference
python3 core/aot/examples/original_sce/verify.py --binary /path/build/core/libs/native/native_sce_package --reference /path/reference/reference --asset-root /path/extracted-package --output /path/verification
python3 core/aot/examples/original_sce/verify.py --binary /path/build/core/libs/native/native_sce_package --reference /path/reference/reference --asset-root /path/extracted-package --output /path/verification-missing --missing-asset
```

Use the Vulkan loader and MoltenVK environment from the cube check. The asset
root contains `assets/banner.txt` and `sce_sys/param.json`. Both verifications
compare all 1920 by 1080 RGB pixels to the source-tag renderer compiled directly
for ARM64. The reference replaces presentation and file access, retaining the
original drawing, tiled addressing, font and asset parsing. It is an independent
pixel oracle, not proof of every system API.

The original application runs indefinitely. The verifier requests host shutdown
after a completed vblank and sleep boundary, checks module initialization and
finalization, and checks GPU teardown. This is not a claim that guest `main`
returns. Running without `ANYPS5_TEST_FRAME_LIMIT=1` retains the original loop.
The package objects and original runtime shim are converted; no host replacement
for the supplied PRX is linked. The shim's many exports are aliases and metadata,
not a complete third-party C library. System functions come from AnyPS5 providers.


### Original DOOM package on Apple ARM64

The `doom` consumer uses [lowbit/ps5-doom v1.1.1](https://github.com/lowbit/ps5-doom/releases/tag/v1.1.1),
PPSA99666, and its supplied libc module. Keep the release package, source and
reference captures outside this repository. Extract the original SELF files as
for `original_sce`; `doom/build.py` checks both ELF identities. It does not
substitute a source-built game for the original executable.

Use source commit `ba6e305bd315828c0980ff93eb54e35c8ebf397b` for the reference and capture-addressing header.
The manifest pins the shareware `doom1.wad`, six reference frames and the consumed
provider definitions. Changed inputs or provider sources require review; do not
update identities without requalifying their contracts.

```sh
cmake -S . -B /path/native-build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64 -DANYPS5_NATIVE_AOT=ON -DANYPS5_NATIVE_GRAPHICS=ON -DBUILD_TESTING=OFF
python3 core/aot/examples/doom/build.py --app /path/eboot.elf --module /path/libc.elf --build-root /path/native-build --output /path/doom-artifacts
cmake --build /path/native-build --target native_sce_crt_tests native_audio_shutdown_tests
ctest --test-dir /path/native-build -R 'native_(sce_crt|.*shutdown)$' --output-on-failure
```

For reference-only capture, replace the capture condition in the external
`src/host/host.c` function `plat_video_present` with the following. Leave the
engine, frame increment and all other behavior unchanged:

```c
extern int gametic;
int saved_frame = frame;
if (gametic == 79 || gametic == 859) {
    frame = gametic == 79 ? 120 : 900;
    capture(pixels, palette);
    frame = saved_frame;
}
```

Build that pinned source's `host` target. For each of `demo1`, `demo2` and
`demo3`, create `/path/references/DEMO` and run the host executable with
`DOOM_WADDIR=/path/PPSA99666/wads`, `DOOM_OUT=/path/references/DEMO` and arguments
`-timedemo DEMO`. The reference exits 1 at timedemo completion; check its log
and captures. The verifier requires the six frozen raw hashes, independently
associated with gametics 79 and 859, not only that exit code. Physical frame
numbers include a clock-dependent initial wipe and are not logical tic
identifiers. Do not enable reference audio or compare its timing with the full
runtime.

Set `SDL_VULKAN_LIBRARY`, `VK_ICD_FILENAMES` and the loader search path as for the
cube check. Then run:

```sh
python3 core/aot/examples/doom/verify.py --binary /path/doom-artifacts/doom --package /path/PPSA99666 --source-root /path/ps5-doom --references /path/references --output /path/doom-verification
```

The verifier copies the package into fresh run directories and selects its
existing CPU scaler and capture server. The example logs the guest gametic at
each capture and at demo completion without changing guest state. The manifest
qualifies its address only for this exact ELF. The verifier requests frames
119–121 and 899–901, selects the predeclared gametics 79 and 859 from that
metadata, and rejects missing, repeated or nonmonotonic evidence. It never
selects by pixel similarity. A target outside the capture window is a failed
qualification. The initial wipe is at tic 1 in these frozen replays; these
targets are outside it. The verifier receives captures over localhost,
checks 5,026/3,836/2,134 gametics, six exact 1920x1080 RGB images, native execution,
module finalization and Vulkan teardown. Alpha is excluded. The original PS5
exit path logs status 1 then requests system-service exit, yielding host status 0.
Each replay has a 180-second laboratory deadline; these are manual integration
checks, not a CTest job or a performance benchmark. The title's capture server
binds its selected port for the duration of each run.

This qualifies the recorded demos with the CPU scaler. AGC presentation, other
WADs, real controller input, AudioOut2 teardown and native-source performance
remain separate work. The runtime's ordered memory and guarded instruction
profile remain active; unknown callable ABIs and nonfinite scalar FMA reject.

### Reproduce standalone consumer builds and measurements

`LIBCAPSTONE_PATH=/path/build/core/aot/capstone python3 core/aot/examples/guest_build.py input.elf /path/fresh-output --name app` builds an ARM64-only Mach-O executable and a receipt with input, compiler/runtime and executable identities. The default profile is ordered; `--profile single` rejects worker creation, while `--profile epochs` enables checked monotonic promotion. Add `--optimize-calls` and optionally `--thin-lto` for the qualified call experiment. `--seal-image` additionally requires the epochs profile. This helper links the native TLS implementation required by descriptor v9. Conversion is offline; the distributed executable contains no x86 decoder, interpreter or JIT.

Use `jq_transfer.py` and the upstream jq core suite for correctness before timing. `jq_benchmark.py --aot APP --arm64 REFERENCE --x86 ROSETTA_REFERENCE --output FRESH_FOLDER` checks architectures and exact output, then alternates nine warm CLI rounds after two warmups. Optional `--baseline-aot` records the conservative compiler. The receipt includes CPU/wall time, peak RSS, executable/input hashes and variability. Source versions, configuration and toolchains of the supplied references require separate qualification. These measurements are not identical-ELF Rosetta comparisons, cold-start results, game compatibility or FPS. Use `zstd_benchmark.py` for the separate single-thread and worker cases.
