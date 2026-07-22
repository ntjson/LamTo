import pytest
from lamto.gate.calibration import CalibrationScores, error_rates, sweep

def scores(): return CalibrationScores([.9, .85, .8, .55, .35], [.1, .12, .2, .42])
def test_error_rates(): assert error_rates(scores(), .5) == pytest.approx((0, .2))
def test_low_threshold_admits_impostor(): assert error_rates(scores(), .4)[0] == pytest.approx(.25)
def test_sweep_is_inclusive():
    rows = sweep(scores(), .3, .6, .01)
    assert len(rows) == 31 and rows[0].threshold == .3 and rows[-1].threshold == .6
def test_empty_scores_are_safe(): assert error_rates(CalibrationScores(), .5) == (0, 0)
