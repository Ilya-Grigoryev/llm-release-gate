from llm_release_gate.runner import read_records


def test_a_broken_line_is_skipped_with_a_warning(tmp_path, capsys):
    path = tmp_path / "runs.jsonl"
    path.write_text(
        '{"case": "a", "rep": 0}\n{"case": "a", "rep": 1\n[1]\n\n{"case": "b", "rep": 0}\n'
    )
    assert [r["case"] for r in read_records(path)] == ["a", "b"]
    assert "skipped 2 line(s)" in capsys.readouterr().err


def test_a_clean_file_says_nothing(tmp_path, capsys):
    path = tmp_path / "runs.jsonl"
    path.write_text('{"case": "a", "rep": 0}\n')
    assert len(read_records(path)) == 1
    assert capsys.readouterr().err == ""
