from llm_release_gate import pr


def test_runs_the_packaged_script(monkeypatch):
    calls = []
    monkeypatch.setattr(pr.os, "execvp", lambda file, args: calls.append((file, args)))
    pr.main(["FETCH_HEAD", ".", "a.yaml", "golden", "out"])
    assert pr.SCRIPT.is_file()
    assert calls == [
        ("bash", ["bash", str(pr.SCRIPT), "FETCH_HEAD", ".", "a.yaml", "golden", "out"])
    ]
