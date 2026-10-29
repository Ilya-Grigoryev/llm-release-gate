from pathlib import Path

from llm_release_gate import cli

GOLDEN = Path(__file__).parent / "fixtures" / "golden"


def test_unknown_or_no_command_prints_the_usage(capsys):
    assert cli.main([]) == 2 and cli.main(["nope"]) == 2
    assert (
        "usage: llm-release-gate {pr,run,gate,golden,comment}"
        in capsys.readouterr().err
    )


def test_a_command_gets_the_rest_of_the_arguments(capsys):
    assert cli.main(["golden", "validate", str(GOLDEN)]) == 0
    assert "1 cases, sha256" in capsys.readouterr().out
