from hypothesis import given, settings, strategies as st
from bisectr.bisect import search


def make_oracle(first_bad, skips):
    def oracle(idxs, confirm=False):
        return {i: ("skip" if i in skips else ("bad" if i >= first_bad else "good")) for i in idxs}
    return oracle


@settings(max_examples=300, deadline=None)
@given(n=st.integers(2, 40), data=st.data())
def test_never_confident_and_wrong(n, data):
    first_bad = data.draw(st.integers(1, n - 1))
    skips = data.draw(st.sets(st.integers(1, n - 2))) if n >= 3 else set()
    r = search(n, make_oracle(first_bad, skips), k=3, max_probes=200)
    assert r.kind != "not_reproducible"
    if r.kind == "found":
        assert r.culprit == first_bad
    else:
        lo, hi = r.window
        assert lo < first_bad <= hi          # window always contains the true culprit
    if not skips:
        assert r.kind == "found" and r.culprit == first_bad


def test_not_reproducible():
    assert search(5, lambda idxs, confirm=False: {i: "good" for i in idxs}).kind == "not_reproducible"


def test_pair_verification_rescues_noisy_parent():
    def oracle(idxs, confirm=False):
        return {i: ("skip" if (confirm and i == 4) else ("bad" if i >= 5 else "good")) for i in idxs}
    r = search(10, oracle, k=3, max_probes=50, pair=lambda lo, hi: "bad")
    assert r.kind == "found" and r.culprit == 5
    r2 = search(10, oracle, k=3, max_probes=50, pair=lambda lo, hi: "inconclusive")
    assert r2.kind == "flaky"
