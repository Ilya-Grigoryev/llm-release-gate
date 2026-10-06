from llm_release_gate.pipelines.sroie import field_hits, parse_box


def test_parse_box_keeps_commas_in_text():
    box = (
        "72,25,326,25,326,64,72,64,TAN WOON YANN\n"
        "110,144,383,144,383,163,110,163,NO.53 55,57 & 59,\n"
        "\n"
    )
    assert parse_box(box) == "TAN WOON YANN\nNO.53 55,57 & 59,"


def test_field_hits_ignores_case_and_spacing():
    expected = {"company": "BOOK TA .K SDN BHD", "date": "25/12/2018", "total": "9.00"}
    got = {"company": "book ta .k  sdn bhd", "date": "25/12/2018", "address": "X"}
    assert field_hits(expected, got) == {
        "company": True,
        "date": True,
        "address": False,
        "total": False,
    }
