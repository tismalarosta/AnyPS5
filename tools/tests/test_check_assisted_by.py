import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_assisted_by

SCRIPT = Path(__file__).resolve().parents[1] / "check_assisted_by.py"

YES = "- [x] AI-assisted: yes\n"
NO = "- [x] AI-assisted: no\n"


def commit(message, sha="a" * 40):
    return [(sha, message)]


class DeclarationTest(unittest.TestCase):
    def test_disclosed_commit_with_yes_passes(self):
        self.assertEqual(check_assisted_by.check(commit("fix(aot): x\n\nAssisted-by: Claude Code\n"), YES), [])

    def test_plain_commit_with_no_passes(self):
        self.assertEqual(check_assisted_by.check(commit("fix(aot): x\n"), NO), [])

    def test_trailer_with_no_fails(self):
        errors = check_assisted_by.check(commit("feat(aot): x\n\nGenerated-by: Claude Code\n", "b" * 40), NO)
        self.assertEqual(len(errors), 1)
        self.assertIn("bbbbbbbbbbbb", errors[0])

    def test_trailer_variants_with_no_fail(self):
        for trailer in ("assisted-by: Claude Code", "  Assisted-by: Claude Code", "Assisted-by : Claude Code"):
            self.assertEqual(len(check_assisted_by.check(commit("fix: x\n\n" + trailer + "\n"), NO)), 1, trailer)

    def test_unticked_box_fails(self):
        errors = check_assisted_by.check([], "- [ ] AI-assisted: yes\n")
        self.assertEqual(len(errors), 1)
        self.assertIn("not ticked", errors[0])

    def test_missing_template_or_invalid_declaration_fails(self):
        for body in ("", "- [ ] AI-assisted: <!-- yes / no -->\n", "- [x] AI-assisted: maybe\n", YES + NO):
            self.assertEqual(len(check_assisted_by.check([], body)), 1, body)

    def test_accepted_declaration_forms(self):
        for body in ("- [X] AI-assisted: Yes.\n", "* [x] AI-assisted: yes\n", "- [x] AI-assisted:yes\r\n"):
            self.assertEqual(check_assisted_by.check([], body), [], body)

    def test_declaration_inside_code_fence_is_ignored(self):
        body = "```\n- [x] AI-assisted: yes\n```\n" + NO
        self.assertEqual(check_assisted_by.check([], body), [])

    def test_long_trailer_line_stays_fast(self):
        import time
        started = time.monotonic()
        check_assisted_by.check(commit("fix: x\n\nCo-authored-by: " + "<" * 200000 + "\n"), NO)
        self.assertLess(time.monotonic() - started, 2)

    def test_declaration_inside_comment_is_ignored(self):
        self.assertEqual(check_assisted_by.check([], "<!-- - [x] AI-assisted: yes -->\n" + NO), [])


class AuthorTest(unittest.TestCase):
    def test_ai_tools_as_authors_fail(self):
        for trailer in ("Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>",
                        "Signed-off-by: GitHub Copilot <copilot@github.com>",
                        "Co-authored-by: Windsurf <bot@codeium.com>",
                        "Co-authored-by: helper <49699333+dependabot[bot]@users.noreply.github.com>",
                        "  Co-authored-by: Claude Code <claude@example.com>",
                        "Co-authored-by : ChatGPT <bot@example.com>",
                        "Co-authored-by: noreply@anthropic.com",
                        "Co-authored-by: Claude-Code <x@example.com>",
                        "Co-authored-by: Claude  Code <x@example.com>",
                        "Co-authored-by: Claude [bot] <claude@users.noreply.github.com>",
                        "Co-developed-by: Claude Code <noreply@anthropic.com>",
                        "Co-authored-by: helper <noreply@anthropic.com"):
            self.assertEqual(len(check_assisted_by.check(commit("fix: x\n\n" + trailer + "\n"), YES)), 1, trailer)

    def test_people_with_tool_like_names_pass(self):
        for trailer in ("Co-authored-by: Claude Dupont <claude.dupont@example.fr>",
                        "Co-authored-by: Devin Smith <devin@example.com>",
                        "Signed-off-by: Ann Lee <cursor@example.com>",
                        "Co-authored-by: Ada Lovelace <ada@example.com>",
                        "Co-authored-by: Jules Verne <jules@example.fr>",
                        "Co-authored-by: Gemini Rossi <gemini@example.it>",
                        "Co-authored-by: Aider Khan <aider@example.com>"):
            self.assertEqual(check_assisted_by.check(commit("fix: x\n\n" + trailer + "\n"), NO), [], trailer)


class GitTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com", GIT_CONFIG_GLOBAL=os.devnull)
        self.git("init", "-q", "-b", "arm64")
        self.git("commit", "-q", "--allow-empty", "-m", "base")
        self.base = self.git("rev-parse", "HEAD")

    def tearDown(self):
        self.directory.cleanup()

    def git(self, *args):
        return subprocess.run(["git", "-C", self.directory.name, *args], env=self.env, check=True,
                              capture_output=True, text=True).stdout.strip()

    def run_script(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.directory.name, env=self.env,
                              capture_output=True, text=True)

    def body(self, text):
        path = Path(self.directory.name) / "body.md"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_reads_commits_between_refs(self):
        self.git("commit", "-q", "--allow-empty", "-m", "fix: one\n\nAssisted-by: Claude Code")
        self.git("commit", "-q", "--allow-empty", "-m", "fix: two")
        result = self.run_script("--base", self.base, "--body", self.body(NO))
        self.assertEqual(result.returncode, 1)
        self.assertIn("Assisted-by", result.stderr)
        result = self.run_script("--base", self.base, "--body", self.body(YES))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_commits_on_the_base_branch_are_not_blamed(self):
        self.git("switch", "-q", "-c", "topic")
        self.git("commit", "-q", "--allow-empty", "-m", "fix: human only")
        topic = self.git("rev-parse", "HEAD")
        self.git("switch", "-q", "arm64")
        self.git("commit", "-q", "--allow-empty", "-m", "fix: other\n\nAssisted-by: Claude Code")
        self.git("merge", "-q", "--no-ff", "-m", "merge topic", "topic")
        result = self.run_script("--base", "arm64~1", "--head", topic, "--body", self.body(NO))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_authors_only_ignores_the_description(self):
        self.git("commit", "-q", "--allow-empty", "-m", "fix: one\n\nAssisted-by: Claude Code")
        self.assertEqual(self.run_script("--base", self.base, "--authors-only").returncode, 0)
        self.git("commit", "-q", "--allow-empty", "-m", "fix: two\n\nCo-authored-by: Claude Code <noreply@anthropic.com>")
        result = self.run_script("--base", self.base, "--authors-only")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Co-authored-by", result.stderr)


if __name__ == "__main__":
    unittest.main()
