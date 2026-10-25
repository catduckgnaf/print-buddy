"""The Discord timing gate fails on slowdowns, missing runs and unexplained baseline raises."""
from tests.corpus.timing_gate import check, record

BASE = {"tolerance": 0.25, "slack_s": 1.0,
        "cases": {"single-part/hermes": {"wall_s": 4.0, "first_prompt_s": 2.0}}}


def row(wall, prompt=2.0, result="PASS"):
    return {"case": "single-part", "transport": "hermes", "result": result,
            "wall_s": wall, "first_prompt_s": prompt}


def test_within_tolerance_passes():
    assert check([row(5.9)], BASE) == []  # limit 4 * 1.25 + 1 = 6.0


def test_slower_than_baseline_fails():
    problems = check([row(6.1)], BASE)
    assert len(problems) == 1 and "wall_s 6.10s > limit 6.00s" in problems[0]


def test_slow_first_prompt_fails_even_if_total_is_fine():
    assert any("first_prompt_s" in p for p in check([row(4.0, prompt=3.6)], BASE))


def test_failed_flow_and_missing_case_are_reported():
    assert "flow result FAIL" in check([row(1.0, result="FAIL")], BASE)[0]
    assert "was not run" in check([], BASE)[0]


def test_new_case_needs_a_baseline():
    other = dict(row(1.0), case="new-case")
    assert any("no baseline" in p for p in check([row(4.0), other], BASE))


def test_raise_without_reason_is_refused_and_reason_accepts_it():
    proposed = record([row(8.0)], BASE)
    entry = proposed["cases"]["single-part/hermes"]
    assert entry["raised_from"] == {"wall_s": 4.0, "first_prompt_s": 2.0}
    assert any("without a reason" in p for p in check([row(8.0)], proposed))
    entry["reason"] = "full mesh validation added, accepted"
    assert check([row(8.0)], proposed) == []


def test_median_of_repeats_ignores_one_noisy_sample():
    from tests.corpus.timing_gate import median_rows
    merged = median_rows([[row(4.0)], [row(30.0)], [row(4.2)]])
    assert merged[0]["wall_s"] == 4.2 and check(merged, BASE) == []
    assert median_rows([[row(4.0)], [row(4.0, result="FAIL")]])[0]["result"] == "FAIL"
