# Native ARM64 port

Rules for the native Apple ARM64 compiler and runtime (`core/aot/`, `core/libs/native/`, and the shared files they change) on the `arm64` branch. They add to [CONTRIBUTING.md](../../CONTRIBUTING.md) and [conventions](CONVENTIONS.md); where both apply, the stricter rule wins. Build steps are in [BUILD.md](BUILD.md#experimental-native-apple-arm64-compiler).

## What goes in

- A change to the compiler, the runtime or a consumer keeps every existing test passing on an Apple ARM64 host. A change that needs a test changed or removed says why in the pull request.
- Every fix adds a test that fails before the change and passes after it. Every new behaviour adds a test that exercises it, including the path that throws. Name the test on the pull request's checklist line.
- Hash-pinned inputs (`bindings.json`, `contract-recipe.json`, reference frames) change only together with the requalification that produced the new hashes. A pull request that changes a pin states what was rerun and on which machine.
- A title enters only through a reviewed bindings manifest. The manifest describes the inputs it was qualified for; it is never widened to other versions without requalifying.
- An instruction, ABI rule or PS5 behaviour the compiler implements cites its source: a measurement (title, machine, what was compared), the Intel or AMD manual section, or the exact SDK or open-source file. Behaviour no source settles throws and is recorded in [debt/aot.md](debt/aot.md).
- The DOOM consumer stays green: three timedemos at 5026, 3836 and 2134 final tics. A change that moves these numbers is a regression until shown otherwise. CI does not run DOOM; a change to the compiler, the runtime or the DOOM bindings reports this run in its pull request.
- Fixtures pinned to `clang-2100.3.34.2` are built with that exact compiler: Xcode 27.1 (27A9275) or Command Line Tools that report that build. Check `clang --version` before regenerating anything. The `xcode-27` CI job selects Xcode 27.1 and fails if the build string differs. If that compiler is no longer available, the pinned inputs are requalified with the new compiler under the rule above, never regenerated in place.
- A flaky test gets an issue labelled `flaky` and the ctest property `DISABLED` with the issue number in the pull request that disables it. It is not retried until it passes.

## AI use

AI tools may help write, read and test code. The person who opens the pull request is its author and answers for every line.

- Every commit written with AI help ends with an `Assisted-by: <tool>` trailer, or `Generated-by: <tool>` when nearly all of it is generated. AI tools are never listed in `Co-authored-by` or `Signed-off-by`. With Claude Code, set `"attribution": {"commit": "Assisted-by: Claude Code"}` in your settings, since its default adds `Co-Authored-By`. The pull request's `AI-assisted` line is ticked and `yes` whenever one of its commits has such a trailer.
- AI may draft commit messages, pull request text and replies. The author rewrites them, checks every claim in them and answers review questions personally. Logs and command output are pasted, not summarised by a tool.
- The pull request says which parts were AI-generated and what the author tested by hand, on which machine, macOS version and compiler build. It also says what could not be built, tested or reproduced.
- No fact about the PS5, its SDK, its file formats or its system libraries enters the project because an AI tool stated it. Each such fact has a primary source the author has checked; AI may help read that source.
- AI output that reproduces code under another licence is treated as that code: it does not go in unless that code could go in by hand under GPL-2.0-only with its notice.
- No agent opens, comments on, approves or merges a pull request, or pushes, unless the author starts that one action and reads its result. Scheduled or event-triggered agents only read and report.
- AI review is advice. A merge follows a maintainer's own reading of the change.
- Tests written with AI help are read as closely as the code: each assertion checks the documented or measured result, not whatever the code returns now.
- Issues labelled `good first issue` are for people learning the code and are solved without AI tools.
- A pull request with hidden AI use, or with a test run, measurement or source that did not happen, is closed without review. A second one ends the author's contributions to the port.

## Review

- The CI gate on Apple ARM64 (`.github/workflows/native-aot.yml`) and the [conventions check](../../tools/check_conventions.py) pass before review starts. A red run is fixed or reverted, never merged over.
- The disclosure check (`.github/workflows/ai-disclosure.yml`, `tools/check_assisted_by.py`) passes: trailers and the ticked `AI-assisted` line agree, and no AI tool is credited as an author. It runs the checker from the base branch, rechecks when the description is edited and checks direct pushes for AI authors. Its list of AI tools and addresses is never complete; a missed one is still a violation.
- The `arm64` branch has a ruleset that requires the Conventions and AI disclosure checks, blocks force pushes and deletion, and requires no approving review while the port has one maintainer. A second maintainer adds a required review. Native ARM64 AOT runs only when its files change, so it is not a required check; a red run still blocks the merge.
- The disclosure check on a direct push covers the commits since the previous push. It relies on the ruleset: a force push or a new branch is checked from its merge base with `main`.
- Prefer reverting a change that broke `arm64` over fixing forward.
