from biaoshu_gen.state import BidState, run_dir


def test_default_state():
    s = BidState(run_id="run-x")
    assert s.metadata is None and s.body_review_rounds == 0
    assert s.draft_version == 0 and s.revision_round == 0


def test_run_dir():
    s = BidState(run_id="run-x")
    assert run_dir(s).name == "run-x"
    assert run_dir(s).parent.name == "runs"
