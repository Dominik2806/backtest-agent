"""The permission rules of ``.claude/settings.json`` that keep ``bt approve`` a person's command (ADR 0019).

``deny`` holds ``bt approve`` in every spelling that is listed in ``COVERED``; ``ask`` makes every ``bt signal check``
by Claude Code a decision of a person. Pytest cannot start Claude Code, so the rules are checked against ``Matcher``
below. **That matcher is our reading of the documented semantics** (code.claude.com/docs/en/permissions.md, "Wildcard
patterns" and "Compound commands"), not Claude Code's matcher: a table that passes here shows that the rules say what
we meant, not that Claude Code blocks the call. The spellings in ``GAPS`` are the ones the rules do not match (the docs
name full paths, ``sh -c`` and quoted words as not caught); they are asserted so that no document can claim more.

A rule that is removed from the file makes ``test_every_covered_spelling_is_matched`` fail; a rule that no covered
spelling needs (a redundant or an extra one, apart from the four that stay on purpose) makes
``test_removing_any_one_rule_leaves_a_covered_spelling_unmatched`` fail. The rules are read from the file, never
compared with a copy of themselves. The matcher has tests with literal expectations of its own.
"""

import json
import re
from pathlib import Path

import pytest

SETTINGS = Path(__file__).resolve().parents[1] / ".claude" / "settings.json"
TOOLS = ("Bash", "PowerShell")
VERBS = {"deny": "approve", "ask": "signal check"}
RULE = re.compile(r"^(?P<tool>[A-Za-z]+)\((?P<pattern>.*)\)$")
SEPARATORS = re.compile(r"&&|\|\||\|&|;|\||&|\n")
WRAPPERS = {"time", "nice", "nohup", "stdbuf", "command", "builtin"}  # ``timeout`` takes an argument: not modelled
ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S*$")
FIRST_WORD = re.compile(r"(\S+)\s+(.*)", re.DOTALL)


class Matcher:
    """Our reading of the permission rules for a shell tool: a rule ``Tool(pattern)`` against one command line."""

    @staticmethod
    def subcommands(command: str) -> list[str]:
        """Split on ``&& || ; | |& &`` and newlines, then drop leading ``VAR=x`` words and wrapper words.

        The spacing inside a command is kept as it is: two spaces or a tab are not turned into one space.
        """
        found = []
        for part in SEPARATORS.split(command):
            rest = part.strip()
            while (first := FIRST_WORD.match(rest)) and (ENV_ASSIGNMENT.match(first[1]) or first[1] in WRAPPERS):
                rest = first[2]
            if rest:
                found.append(rest)
        return found

    @staticmethod
    def pattern_matches(pattern: str, text: str, *, ignore_case: bool) -> bool:
        """``*`` matches any text, spaces included; a trailing `` *`` also matches the bare command."""
        flags = re.IGNORECASE if ignore_case else 0
        if pattern.endswith(" *"):
            expression = re.escape(pattern[:-2]).replace(r"\*", ".*") + "(?: .*)?"
        else:
            expression = re.escape(pattern).replace(r"\*", ".*")
        return re.fullmatch(expression, text, flags) is not None

    @classmethod
    def blocked_by(cls, rules: list[str], tool: str, command: str) -> bool:
        patterns = []
        for rule in rules:
            parsed = RULE.match(rule)
            assert parsed, f"not a rule of the form Tool(pattern): {rule!r}"
            if parsed["tool"] == tool:
                patterns.append(parsed["pattern"])
        ignore_case = tool == "PowerShell"  # documented: PowerShell rules are case-insensitive
        return any(
            cls.pattern_matches(pattern, sub, ignore_case=ignore_case)
            for sub in cls.subcommands(command)
            for pattern in patterns
        )


def rules_of(kind: str) -> list[str]:
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    return list(settings["permissions"][kind])


# Spellings that each kind of rule must match. VERB is "approve" for deny and "signal check" for ask.
# The comment names the rule that is the only one to match it (the witness of that rule in the mutation loop).
COVERED = [
    "bt VERB spec.yaml",  # bt VERB *
    "bt VERB",  # bt VERB * (a trailing space-star also matches the bare command)
    "uv run bt VERB spec.yaml",  # * bt VERB *
    "uv run --quiet bt VERB spec.yaml",  # * bt VERB *
    "timeout 5 bt VERB spec.yaml",  # * bt VERB *
    ".venv/Scripts/bt VERB spec.yaml",  # */bt VERB *
    "bt.exe VERB spec.yaml",  # bt.exe VERB *
    ".venv/Scripts/bt.exe VERB spec.yaml",  # */bt.exe VERB *
    "python -m backtest_agent VERB spec.yaml",  # * backtest_agent VERB *
    "py -m backtest_agent VERB spec.yaml",  # * backtest_agent VERB *
    "python3 -m backtest_agent VERB spec.yaml",  # * backtest_agent VERB *
    "uv run python -m backtest_agent VERB spec.yaml",  # * backtest_agent VERB *
    "cd work && bt VERB spec.yaml",  # bt VERB * (a compound command is split)
    "echo done; bt VERB spec.yaml",  # bt VERB *
    "echo spec | bt VERB spec.yaml",  # bt VERB *
    "FOO=1 bt VERB spec.yaml",  # bt VERB * (a leading assignment is skipped)
    "time bt VERB spec.yaml",  # bt VERB * (a wrapper word is skipped)
]
# The PowerShell tool has the same rules, case-insensitive.
COVERED_POWERSHELL_ONLY = ["BT VERB spec.yaml", "Uv Run Bt VERB spec.yaml", "BT.EXE VERB spec.yaml"]

# Explicit rules that are redundant ON PURPOSE (deny only): the semantics of a leading ``*`` are not documented, so the
# plain forms stay even though the wide rules match the same spellings in our reading. They are exempt from the "needed"
# test below; each must exist for both tools and match its own spelling on its own.
REDUNDANT_ON_PURPOSE = {
    "uv run bt approve *": "uv run bt approve spec.yaml",
    "python -m backtest_agent approve *": "python -m backtest_agent approve spec.yaml",
    "py -m backtest_agent approve *": "py -m backtest_agent approve spec.yaml",
    "python3 -m backtest_agent approve *": "python3 -m backtest_agent approve spec.yaml",
}

# Spellings that the rules do NOT match. They are known gaps (docs/agents.md); the hook of the agents and the reading of
# the person are the other layers. Asserted so that a document cannot claim that these are blocked.
GAPS = [
    "sh -c 'bt VERB spec.yaml'",  # documented as not caught: sh -c
    'bash -c "bt VERB spec.yaml"',  # documented as not caught: bash -c
    "bt  VERB spec.yaml",  # two spaces: not documented, not matched by our reading
    "bt\tVERB spec.yaml",  # a tab: likewise
    "QUOTED",  # documented as not caught: a quoted word
    "python -c \"from backtest_agent.cli import main; main(['VERBWORDS'])\"",  # no command word at all
    "$(bt VERB spec.yaml)",  # our matcher does not look into a substitution (the Claude Code docs say theirs does)
    "`bt VERB spec.yaml`",  # a backtick substitution: likewise
    "(bt VERB spec.yaml)",  # a subshell: likewise
    'eval "bt VERB spec.yaml"',  # eval of a string
]
# Backslash paths (PowerShell users write them): the rules have "/" in their path forms, so these are not matched.
GAPS_POWERSHELL = [
    ".\\.venv\\Scripts\\bt.exe VERB spec.yaml",
    ".venv\\Scripts\\bt VERB spec.yaml",
]
GAPS_BASH = [
    "BT VERB spec.yaml",  # Bash rules are case-sensitive (PowerShell ones are not)
    "BT.EXE VERB spec.yaml",
]
# Spellings of other commands that must not be matched (no over-blocking of the commands agents may run).
NOT_THE_VERB = [
    "bt run spec.yaml",
    "bt validate spec.yaml",
    "bt journal list",
    "bt approved spec.yaml",
    "uv run bt validate spec.yaml",
    "uv run bt run spec.yaml",
    "git status",
]


def spell(template: str, kind: str) -> str:
    verb = VERBS[kind]
    return template.replace("VERBWORDS", "', '".join(verb.split())).replace("VERB", verb)


def quoted_last_word(kind: str) -> str:
    words = VERBS[kind].split()
    return "bt " + " ".join([*words[:-1], f"'{words[-1]}'"]) + " spec.yaml"


def covered_spellings(kind: str) -> list[tuple[str, str]]:
    found = [(tool, spell(template, kind)) for tool in TOOLS for template in COVERED]
    found += [(tool, spell(template, kind)) for tool in ("PowerShell",) for template in COVERED_POWERSHELL_ONLY]
    return found


def gap_spellings(kind: str) -> list[tuple[str, str]]:
    found = []
    for tool in TOOLS:
        for template in GAPS:
            command = quoted_last_word(kind) if template == "QUOTED" else spell(template, kind)
            found.append((tool, command))
    found += [("PowerShell", spell(template, kind)) for template in GAPS_POWERSHELL]
    found += [("Bash", spell(template, kind)) for template in GAPS_BASH]
    return found


# --- the settings file ---------------------------------------------------------------------------------------------


def test_settings_is_valid_json_with_rules_of_the_form_tool_and_pattern() -> None:
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    for kind in ("deny", "ask"):
        rules = settings["permissions"][kind]
        assert rules and len(rules) == len(set(rules)), f"{kind} is empty or has a rule twice"
        for rule in rules:
            parsed = RULE.match(rule)
            assert parsed and parsed["tool"] in TOOLS, rule


def test_no_allow_rule_names_the_approval() -> None:
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    allow = settings["permissions"].get("allow", [])
    assert not [rule for rule in allow if "approve" in rule or "backtest_agent" in rule], allow


# --- the spelling tables against the rules --------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["deny", "ask"])
def test_every_covered_spelling_is_matched(kind: str) -> None:
    rules = rules_of(kind)
    missed = [
        (tool, command) for tool, command in covered_spellings(kind) if not Matcher.blocked_by(rules, tool, command)
    ]
    assert missed == []


@pytest.mark.parametrize("kind", ["deny", "ask"])
def test_the_known_gaps_are_not_matched(kind: str) -> None:
    rules = rules_of(kind)
    matched = [(tool, command) for tool, command in gap_spellings(kind) if Matcher.blocked_by(rules, tool, command)]
    assert matched == [], "a gap is matched now: move it to COVERED and fix the documents"


@pytest.mark.parametrize("kind", ["deny", "ask"])
def test_other_commands_are_not_matched(kind: str) -> None:
    rules = rules_of(kind)
    other = "approve" if kind == "ask" else "signal check"
    commands = [*NOT_THE_VERB, f"bt {other} spec.yaml", f"uv run bt {other} spec.yaml"]
    matched = [(tool, c) for tool in TOOLS for c in commands if Matcher.blocked_by(rules, tool, c)]
    assert matched == []


@pytest.mark.parametrize("kind", ["deny", "ask"])
def test_removing_any_one_rule_leaves_a_covered_spelling_unmatched(kind: str) -> None:
    """Every rule, the four redundant on purpose apart, is the only one to match some covered spelling.

    This fails on a redundant or an extra rule. A rule that is removed or incomplete is seen by
    ``test_every_covered_spelling_is_matched``, not by this test."""
    rules = rules_of(kind)
    spellings = covered_spellings(kind)
    exempt = {f"{tool}({pattern})" for tool in TOOLS for pattern in REDUNDANT_ON_PURPOSE} if kind == "deny" else set()
    for index, rule in enumerate(rules):
        if rule in exempt:
            continue
        without = rules[:index] + rules[index + 1 :]
        lost = [(tool, command) for tool, command in spellings if not Matcher.blocked_by(without, tool, command)]
        assert lost, f"{kind} rule {rule!r} is not needed by any covered spelling: remove it or add its spelling"


@pytest.mark.parametrize("tool", TOOLS)
@pytest.mark.parametrize("pattern", sorted(REDUNDANT_ON_PURPOSE))
def test_each_redundant_rule_exists_and_matches_its_own_spelling(tool: str, pattern: str) -> None:
    rule = f"{tool}({pattern})"
    assert rule in rules_of("deny"), f"{rule} was removed; the plain forms stay on purpose"
    assert Matcher.blocked_by([rule], tool, REDUNDANT_ON_PURPOSE[pattern])


# --- the matcher itself, with literal expectations ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "text", "expected"),
    [
        ("bt approve *", "bt approve", True),  # documented: a trailing space-star also matches the bare command
        ("bt approve *", "bt approve spec.yaml --idea", True),  # * matches spaces
        ("bt approve *", "bt approved spec.yaml", False),  # documented: not bt approved
        ("bt approve *", "uv run bt approve x", False),  # a rule is anchored at both ends
        ("* bt approve *", "uv run bt approve x", True),
        ("* bt approve *", "bt approve x", False),  # the leading star needs a word before bt in our reading
        ("*/bt approve *", ".venv/Scripts/bt approve x", True),
        ("bt.exe approve *", "bt approve x", False),
    ],
)
def test_pattern_matches_follows_the_documented_wildcards(pattern: str, text: str, expected: bool) -> None:
    assert Matcher.pattern_matches(pattern, text, ignore_case=False) is expected


def test_pattern_matches_is_case_sensitive_unless_asked() -> None:
    assert Matcher.pattern_matches("bt approve *", "BT approve x", ignore_case=False) is False
    assert Matcher.pattern_matches("bt approve *", "BT APPROVE x", ignore_case=True) is True


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("bt approve x", ["bt approve x"]),
        ("cd a && bt approve x", ["cd a", "bt approve x"]),
        ("a || b; c | d |& e & f", ["a", "b", "c", "d", "e", "f"]),
        ("first\nsecond", ["first", "second"]),
        ("FOO=1 BAR=2 bt approve x", ["bt approve x"]),
        ("nohup time bt approve x", ["bt approve x"]),
        ("  ", []),
    ],
)
def test_subcommands_split_and_strip(command: str, expected: list[str]) -> None:
    assert Matcher.subcommands(command) == expected


def test_bt_has_no_global_options_so_no_flag_can_stand_between_bt_and_the_command() -> None:
    """``bt --flag approve`` is no spelling: the top-level parser has only --help and --version (both exit)."""
    from backtest_agent.cli.parser import build_parser

    parser = build_parser()
    assert {option for action in parser._actions for option in action.option_strings} == {"-h", "--help", "--version"}
