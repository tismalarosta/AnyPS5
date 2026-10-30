import argparse
import re
import subprocess
import sys
from pathlib import Path

AI_TRAILER = re.compile(r"^[ \t]*(Assisted-by|Generated-by)[ \t]*:[ \t]*\S", re.IGNORECASE | re.MULTILINE)
AUTHOR_TRAILER = re.compile(r"^[ \t]*(Co-authored-by|Co-developed-by|Signed-off-by)[ \t]*:(.*)$", re.IGNORECASE | re.MULTILINE)
AI_EMAILS = re.compile(r"(noreply@anthropic\.com|claude@anthropic\.com|noreply@openai\.com|cursoragent@cursor\.com"
                       r"|copilot@github\.com|@codeium\.com|@windsurf\.com|aider@aider\.chat|jules@google\.com"
                       r"|\[bot\]@users\.noreply\.github\.com|copilot[^\s<>@]*@users\.noreply\.github\.com)", re.IGNORECASE)
AI_NAMES = re.compile(r"\b(claude[\s-]+(code|opus|sonnet|haiku|fable)|claude[\s-]*\[bot\]|chatgpt|gpt-?\d|copilot"
                      r"|gemini[\s-]+(code[\s-]+assist|cli)|google[\s-]+jules|codex|cursor[\s-]+agent|windsurf|codeium"
                      r"|devin[\s-]+ai|amazon[\s-]+q|kiro|opencode)(?!\w)", re.IGNORECASE)
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
FENCE = re.compile(r"^[ \t]*(```|~~~).*?^[ \t]*\1[^\n]*$", re.DOTALL | re.MULTILINE)
DECLARATION = re.compile(r"^[ \t]*[-*][ \t]*\[([ xX])\][ \t]*AI-assisted[ \t]*:[ \t]*([A-Za-z]*)", re.IGNORECASE | re.MULTILINE)
FORMAT = "'- [x] AI-assisted: yes' or '- [x] AI-assisted: no'"


def names_ai_tool(who):
    name = who.split("<", 1)[0]
    if "<" not in who:
        name = " ".join(word for word in who.split() if "@" not in word)
    name = name.replace("\u00a0", " ")
    return bool(AI_EMAILS.search(who) or AI_NAMES.search(name))


def declared(body):
    found = DECLARATION.findall(FENCE.sub("", COMMENT.sub("", body.replace("\r\n", "\n"))))
    if len(found) != 1:
        return None, f"pull request description needs exactly one ticked line: {FORMAT}"
    tick, value = found[0]
    if tick == " ":
        return None, f"the AI-assisted box is not ticked; use {FORMAT}"
    if value.lower() not in ("yes", "no"):
        return None, f"AI-assisted must be yes or no; use {FORMAT}"
    return value.lower(), None


def check_authors(commits):
    errors = []
    for sha, message in commits:
        for kind, who in AUTHOR_TRAILER.findall(message):
            if names_ai_tool(who):
                errors.append(f"{sha[:12]}: {kind} names an AI tool ({who.strip()}); use Assisted-by or Generated-by")
    return errors


def check(commits, body):
    errors = check_authors(commits)
    assisted = [sha for sha, message in commits if AI_TRAILER.search(message)]
    value, problem = declared(body)
    if problem:
        errors.append(problem)
    elif value == "no" and assisted:
        errors.append("AI-assisted is 'no' but these commits carry Assisted-by or Generated-by: "
                      + ", ".join(sha[:12] for sha in assisted))
    return errors


def commits_between(base, head):
    output = subprocess.run(["git", "log", "--no-merges", "--format=%H%x00%B%x1e", f"{base}..{head}"],
                            capture_output=True, text=True, encoding="utf-8", check=True).stdout
    entries = []
    for record in output.split("\x1e"):
        record = record.strip("\n")
        if record:
            sha, _, message = record.partition("\x00")
            entries.append((sha, message))
    return entries


def main():
    parser = argparse.ArgumentParser(description="check that AI trailers and the AI-assisted line agree")
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--body", type=Path, help="file holding the pull request description")
    parser.add_argument("--authors-only", action="store_true", help="check only Co-authored-by and Signed-off-by")
    arguments = parser.parse_args()
    commits = commits_between(arguments.base, arguments.head)
    if arguments.authors_only:
        errors = check_authors(commits)
    elif arguments.body is None:
        parser.error("--body is required unless --authors-only is given")
    else:
        errors = check(commits, arguments.body.read_text(encoding="utf-8"))
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
