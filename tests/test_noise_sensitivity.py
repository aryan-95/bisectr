import pytest

from eval.noise_sensitivity import simulate


def test_zero_flip_rate_finds_every_culprit():
    rows = simulate([0.0], trials=50, seed=13)

    assert rows[0]["exact"] == 50
    assert rows[0]["wrong"] == 0
    assert rows[0]["safe_undecided_rate"] == 0


def test_noise_simulation_is_reproducible():
    assert simulate([0.0, 0.1], trials=25, seed=7) == simulate(
        [0.0, 0.1], trials=25, seed=7
    )


@pytest.mark.parametrize("rate", [-0.1, 1.1])
def test_noise_simulation_rejects_invalid_flip_rates(rate):
    with pytest.raises(ValueError, match="between zero and one"):
        simulate([rate], trials=2)
