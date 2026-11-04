"""docs/agents.md and ADR 0019 are true about the fences (Phase 10 part 4a).

Every claim of ``docs/agents.md`` between "The fences" and "Tests" ends with the test that checks it,
``(test: tests/file.py::name)``, or says ``(not tested)``. This file fails if a named test does not exist, if a claim
has neither, if the hook line in the document is not the line of ``.claude/settings.json``, if the table of spellings
disagrees with the rules, or if a sentence about the hook is no longer true of its source. The expected values are the
literals of the document; the hook line and the rules are read from the files they describe.
"""

import ast
import re
import sys
from pathlib import Path

import pytest

from restrict_writes_helpers import HOOK, settings_command
from test_agent_deny_rules import Matcher, rules_of

ROOT = Path(__file__).resolve().parents[1]


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8").replace("\r\n", "\n")


AGENTS = read("docs", "agents.md")
ADR19 = read("docs", "adr", "0019-agents-and-their-guardrails.md")
ADR18 = read("docs", "adr", "0018-coded-signals-and-approval-gate.md")
CLI = read("docs", "cli.md")
CODED = read("docs", "coded-signals.md")
CLAUDE = read("CLAUDE.md")
HOOK_SOURCE = HOOK.read_text(encoding="utf-8")


def flat(text: str) -> str:
    return " ".join(text.split())


# --- every claim names a test, or says that it is not tested ---

NAMED_TEST = re.compile(r"`(tests/[A-Za-z0-9_]+\.py)::([A-Za-z0-9_]+)`")
NOT_TESTED = re.compile(r"\(not tested|not tested\)")
FENCE = re.compile(r"^```.*?^```[^\n]*$", re.DOTALL | re.MULTILINE)


def missing_tests(text: str, root: Path) -> list[str]:
    """``file::name`` for every named test whose file or ``def`` does not exist."""
    missing = []
    for file, name in NAMED_TEST.findall(text):
        path = root / file
        if (
            not path.is_file()
            or re.search(rf"^(async )?def {re.escape(name)}\(", path.read_text(encoding="utf-8"), re.M) is None
        ):
            missing.append(f"{file}::{name}")
    return missing


def claims(section: str) -> list[str]:
    """The prose claims of a section: paragraphs and list items, without headings, tables and code fences."""
    found = []
    for block in re.split(r"\n\s*\n", FENCE.sub("", section)):
        block = block.strip()
        if not block or block.startswith(("#", "|")):
            continue
        if block.startswith("- "):
            found += [item.strip() for item in re.split(r"(?m)^- ", block) if item.strip()]
        else:
            found.append(block)
    return found


def has_tag(claim: str) -> bool:
    """A claim says ``(not tested)``, or has a ``(test:`` that is followed by at least one named test."""
    claim = flat(claim)  # a tag may be broken over two lines
    if NOT_TESTED.search(claim):
        return True
    start = claim.find("(test:")
    return start >= 0 and NAMED_TEST.search(claim, start) is not None


def untagged(text: str) -> list[str]:
    section = text[text.index("## The fences") : text.index("\n## Tests\n")]
    return [flat(claim)[:70] for claim in claims(section) if not has_tag(claim)]


def test_every_test_named_in_the_document_exists() -> None:
    assert len(NAMED_TEST.findall(AGENTS)) >= 40  # the document really is tied to tests
    assert missing_tests(AGENTS, ROOT) == []


def test_the_checker_finds_a_test_that_does_not_exist(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_there():\n    pass\n", encoding="utf-8")
    text = "`tests/test_x.py::test_there` `tests/test_x.py::test_gone` `tests/test_y.py::test_there`"
    assert missing_tests(text, tmp_path) == ["tests/test_x.py::test_gone", "tests/test_y.py::test_there"]


def test_every_claim_has_a_test_or_says_that_it_is_not_tested() -> None:
    assert untagged(AGENTS) == []


def test_the_checker_finds_a_claim_without_a_tag() -> None:
    text = "## The fences\n\n- tagged. (test: `tests/a.py::b`)\n- loose claim\n- also loose (not tested)\n\n## Tests\n"
    assert untagged(text) == ["loose claim"]
    empty = (
        "## The fences\n\n- names nothing. (test: )\n- names a word. (test: see the tests)\n"
        "- ok (test: `tests/a.py::b`)\n\n## Tests\n"
    )
    assert untagged(empty) == ["names nothing. (test: )", "names a word. (test: see the tests)"]
    assert has_tag("x (test: `tests/a.py::b`, `tests/c.py::d`)") and has_tag("x (not tested)") and not has_tag("x")
    assert claims("- one\n- two\n\nparagraph\n\n| a | b |\n\n```text\ncode\n```\n\n### heading") == [
        "one",
        "two",
        "paragraph",
    ]


# --- the hook line and the spellings are the files' ---


def test_the_hook_line_in_this_document_is_the_line_of_settings_json() -> None:
    blocks = re.findall(r"^```text\n(.*?)\n```$", AGENTS, flags=re.MULTILINE | re.DOTALL)
    assert blocks == [settings_command()]


ROW = re.compile(r"^\| `([^`]+)`[^|]*\| (yes|no) \|$", re.MULTILINE)


def test_the_table_of_spellings_agrees_with_the_deny_rules() -> None:
    rows = ROW.findall(AGENTS)
    assert len(rows) == 17 and {answer for _, answer in rows} == {"yes", "no"}
    deny = rules_of("deny")
    wrong = [
        (command, answer) for command, answer in rows if Matcher.blocked_by(deny, "Bash", command) != (answer == "yes")
    ]
    assert wrong == []


def test_the_table_checker_would_notice_a_flipped_row() -> None:
    deny = rules_of("deny")
    assert Matcher.blocked_by(deny, "Bash", "sh -c 'bt approve spec.yaml --idea'") is False
    assert Matcher.blocked_by(deny, "Bash", "bt approve spec.yaml --idea") is True


# --- sentences that are about the code of the hook ---


def test_the_details_paragraphs_are_true_of_the_hook_source() -> None:
    details = AGENTS[AGENTS.index("## Details of the hook") : AGENTS.index("## Known gaps")]
    text = flat(details)
    assert "allowed only when `permission_mode` of the call is `default`" in text
    assert 'payload.get("permission_mode", MISSING)' in HOOK_SOURCE and 'mode != "default"' in HOOK_SOURCE
    assert "reads the bytes of stdin and decodes them as UTF-8 itself" in text
    assert "sys.stdin.buffer.read()" in HOOK_SOURCE and "reconfigure" not in HOOK_SOURCE
    assert "`RSIPUL~1.py`" in details and r"~[0-9]" in HOOK_SOURCE and "below_project" in HOOK_SOURCE
    assert "Write, Edit, MultiEdit, NotebookEdit, Bash and PowerShell" in text
    assert 'READ_TOOLS = ("Read", "Glob", "Grep")' in HOOK_SOURCE and "allows Read, Glob and Grep" in text
    assert len([p for p in details.split("\n\n") if p.strip()]) == 6  # the heading, the intro and four details


def test_the_hook_imports_only_the_standard_library() -> None:
    modules = set()
    for node in ast.walk(ast.parse(HOOK_SOURCE)):
        if isinstance(node, ast.Import):
            modules |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "a relative import"
            modules.add((node.module or "").split(".")[0])
    assert {"json", "os", "re", "sys", "pathlib"} <= modules
    assert modules <= sys.stdlib_module_names, sorted(modules - sys.stdlib_module_names)


def test_the_hook_source_never_prints_a_decision() -> None:
    code = re.sub(r'""".*?"""', "", HOOK_SOURCE, flags=re.DOTALL)
    assert "permissionDecision" not in code and "print(" not in code


def test_the_agent_files_do_not_exist_yet_and_the_document_says_so() -> None:
    assert not (ROOT / ".claude" / "agents").exists()
    assert "the agent files in `.claude/agents/`" in flat(AGENTS) and "(planned, files not built yet)" in AGENTS


# --- what the documents must say, and what they must not ---


WORDING_HEAD = (
    "The signal coder may run `bt signal check` only in the default permission mode; "
    "the hook refuses it otherwise (enforced)."
)


def test_the_binding_sentences_of_the_adr_are_kept() -> None:
    text = flat(AGENTS)
    assert "the only limit of an agent run is the timeout of its own tool" in text
    assert "The subprocess hardening, a wall-clock limit and a memory limit, is NOT built" in text
    assert "An agent that runs the command runs its own code with its own permissions" in text
    assert "**" + WORDING_HEAD + "**" in flat(AGENTS)
    assert "**The strategy-architect may not; the signal-coder may.**" in AGENTS
    for name, document in (("agents", AGENTS), ("adr19", ADR19)):
        assert "precondition" not in document.lower(), name
    assert "NOT built" in flat(ADR19)


def test_the_documents_state_the_version_the_schema_and_bypass_permissions() -> None:
    text = flat(AGENTS)
    assert "`onFailure` needs Claude Code 2.1.295 or later" in text and "not in the SchemaStore schema" in text
    assert "editor that validates against the schema may warn" in text
    assert "Do not run these agents with `bypassPermissions`" in text and "was not tested" in text
    assert "Deny and ask rules also apply to Claude Code's own session" in text
    assert "`git add` a signal file only after you have read the code" in text
    for needle in ("fence", "workspace trust", "working interpreter", 'delete the `"hooks"` key'):
        assert needle in text, needle
    assert "2.1.295" in ADR19 and "SchemaStore" in ADR19 and "bypassPermissions" in ADR19


def test_no_document_says_any_more_that_the_deny_rule_does_not_exist() -> None:
    for name, document in (("cli", CLI), ("coded", CODED), ("claude", CLAUDE)):
        text = flat(document)
        assert "does not exist yet" not in text.replace("code that does not exist yet", ""), name
        assert "no rule denies the command to an agent yet" not in text, name
    assert "[ADR 0019](0019-agents-and-their-guardrails.md)" in ADR18
    assert "is decided in the agents part (pull request 4), which must state it in `docs/agents.md`" in flat(ADR18)


def test_adr_0019_is_in_the_index_and_has_its_sections() -> None:
    index = read("docs", "adr", "README.md")
    assert "| [0019](0019-agents-and-their-guardrails.md) | The agents and their guardrails" in index
    headings = re.findall(r"^## (.+)$", ADR19, flags=re.MULTILINE)
    assert headings == ["Context", "Decision", "Known gaps", "Consequences"]
    assert "- **Status:** Accepted." in ADR19


def test_claude_md_describes_the_guardrails_and_their_tests() -> None:
    text = flat(CLAUDE)
    assert "Agent guardrails (`docs/agents.md`, ADR 0019)" in text
    assert "**only when `permission_mode` of the call is `default`**" in text
    assert "unless the entry has `onFailure` `block`" in text and "fenced from it" in text
    assert "**It never prints a `permissionDecision`**" in text and '`"onFailure": "block"`' in text
    assert "`tests/test_agent_deny_rules.py`, `tests/test_restrict_writes*.py`" in text
    assert "`strategies/drafts/` is git-ignored" in text and "`(not tested)` (`tests/test_agents_docs.py`)" in text


# --- the permission mode, the layer count, the observations and the links, in every document that says them ---

WORDING = (
    "The signal coder may run `bt signal check` only in the default permission mode; "
    "the hook refuses it otherwise (enforced). "
    "The hook cannot see whether an agent runs in the background; "
    "whether Claude Code shows the ask prompt to a person for a background agent in the default mode was not tested. "
    "The ask rule is a second layer."
)
ROADMAP = read("docs", "ROADMAP.md")
ENTRY_START = "- Phase 10 part 4a (`feature/agents-guardrails`)"
ENTRY = ROADMAP[ROADMAP.index(ENTRY_START) : ROADMAP.index("\n---\n\n## Phase 0")]


def say(document: str) -> str:
    """The text of a document as a reader sees it: one line, bold marks dropped."""
    return flat(document).replace("**", "")


def test_the_same_wording_says_who_may_run_signal_check_in_every_place() -> None:
    places = {"agents": AGENTS, "adr19": ADR19, "cli": CLI, "coded": CODED, "roadmap entry": ENTRY}
    for name, document in places.items():
        assert WORDING in say(document), name


def test_no_place_guarantees_that_agents_cannot_run_it_unattended() -> None:
    places = {"agents": AGENTS, "adr19": ADR19, "cli": CLI, "coded": CODED, "roadmap entry": ENTRY, "claude": CLAUDE}
    for name, document in places.items():
        text = say(document).lower()
        assert "may not run it unattended" not in text and "not unattended" not in text, name
        assert "agents may not run" not in text, name
        assert "attended-only" not in text and "because of the ask rule" not in text, name
    assert "Whether agents may run the command unattended is decided" in flat(ADR18)  # the binding wording of ADR 0018


def test_the_background_case_is_said_not_to_be_covered() -> None:
    assert "The background case is not covered by the mode check" in say(AGENTS)
    adr = say(ADR19)
    assert "The background case is NOT covered by the mode check" in adr
    assert "(the background case is NOT covered by the mode check)" in adr
    assert "background agent was not tested, which is why" not in adr + say(AGENTS)
    assert "and it cannot see whether an agent runs in the background" in say(AGENTS)
    assert "only when `permission_mode` of the call is `default`" in adr


def test_the_gaps_bullet_says_that_the_claim_about_substitutions_is_not_tested() -> None:
    text = say(AGENTS)
    assert "which our matcher does not (that Claude Code's documentation says this is not tested)." in text


def test_the_tools_paragraph_says_that_the_frontmatter_copy_will_have_no_matcher() -> None:
    text = say(AGENTS)
    assert "for the frontmatter copy, which will have no matcher (part 4b), by the hook" in text
    assert "which has no matcher" not in text


def test_one_layer_count_everywhere() -> None:
    for name, document in (("agents", AGENTS), ("adr19", ADR19), ("cli", CLI), ("coded", CODED), ("claude", CLAUDE)):
        text = flat(document)
        assert "Three layers" not in text and "Two layers" not in text, name
    assert "Two fences, the rules and the hook, and the person who reads the code" in flat(AGENTS)
    assert "**Two fences, and a person.**" in ADR19
    assert "Two fences stand in the way of an agent" in flat(CLI) and "Two fences stand in the way of an agent" in flat(
        CODED
    )


def test_the_observations_are_stated_as_seen_once_and_not_with_this_script() -> None:
    section = flat(AGENTS[AGENTS.index("## Observations") : AGENTS.index("## Details of the hook")])
    assert "Claude Code 2.1.318, on one machine" in section and "a logging hook and a user-level probe agent" in section
    assert "They were not seen with this script on a call of one of the two agents" in section
    assert "`agent_id` and `agent_type`" in section and "A main-session call has neither" in section
    assert "Every call carries `permission_mode`" in section
    assert '`"onFailure": "block"` blocked a Write when the hook exited 1' in section
    assert "without the key only gave a warning and the write went through" in section


def test_the_status_says_which_part_and_not_this_pull_request() -> None:
    status = AGENTS[AGENTS.index("## Status") : AGENTS.index("## The two agents")]
    assert "Phase 10 part 4a" in status and "this pull request" not in status


def test_the_hook_source_does_not_look_at_background_or_sandbox_flags() -> None:
    assert "run_in_background" not in HOOK_SOURCE and "dangerouslyDisableSandbox" not in HOOK_SOURCE
    assert "ignores `run_in_background` and `dangerouslyDisableSandbox`" in flat(AGENTS)


def test_every_row_of_the_refusal_table_names_a_test() -> None:
    table = AGENTS[AGENTS.index("| Refusal | Test |") : AGENTS.index("### Drafts and public files")]
    rows = [line for line in table.splitlines() if line.startswith("| ") and not line.startswith(("| Refusal", "|---"))]
    assert len(rows) == 13
    for row in rows:
        assert len(NAMED_TEST.findall(row)) == 1, row
    assert missing_tests(table, ROOT) == []


def paragraph(document: str, start: str) -> str:
    begin = document.index(start)
    end = document.find("\n\n", begin)
    return document[begin : end if end >= 0 else len(document)]


LINKS = [
    ("cli", "**Who runs `bt approve`.**"),
    ("cli", "**Who runs `bt signal check`.**"),
    ("coded", "**Who may run `bt approve`.**"),
    ("coded", "**In process, not in a subprocess.**"),
]


@pytest.mark.parametrize(
    ("name", "start"), LINKS, ids=[f"{name}-{start.strip('*.').replace(' ', '-')}" for name, start in LINKS]
)
def test_each_paragraph_that_sends_the_reader_to_the_agents_document_has_its_own_link(name: str, start: str) -> None:
    document = {"cli": CLI, "coded": CODED}[name]
    assert "[agents.md](agents.md)" in paragraph(document, start)


def test_the_table_header_and_the_gaps_bullet_say_only_what_they_can_prove() -> None:
    text = flat(AGENTS)
    assert "| Command (Bash tool) | Matched by the rules (our reading of the syntax) |" in text
    assert "Denied by the rules" not in text
    assert "A spelling that is not in the table above is not denied" not in text
    assert (
        "A spelling that the rules do not match is not denied." in text
        and "`GAPS` in `tests/test_agent_deny_rules.py`" in text
    )
