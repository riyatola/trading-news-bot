from datetime import datetime, timedelta

from app.processing.deduplicate import (
    ClusterCandidate,
    assign_cluster_id,
    jaccard_similarity,
)


class _FakeRawEvent:
    """Minimal stand-in for a RawEvent row -- assign_cluster_id only
    touches `.title`, so no DB/ORM needed to test it."""

    def __init__(self, title: str):
        self.title = title


def test_jaccard_similarity_identical_sets():
    a = {"apple", "earnings", "beat"}
    assert jaccard_similarity(a, a) == 1.0


def test_jaccard_similarity_disjoint_sets():
    assert jaccard_similarity({"apple"}, {"microsoft"}) == 0.0


def test_jaccard_similarity_both_empty():
    assert jaccard_similarity(set(), set()) == 0.0


def test_assign_cluster_id_reuses_similar_title():
    candidates = [
        ClusterCandidate(
            event_cluster_id="CLU-existing",
            title="Apple beats Q3 earnings estimates",
            published_at=datetime.utcnow() - timedelta(hours=1),
        )
    ]
    raw_event = _FakeRawEvent(title="Apple beats Q3 earnings estimates, shares rise")

    assert assign_cluster_id(raw_event, candidates) == "CLU-existing"


def test_assign_cluster_id_mints_new_id_for_unrelated_story():
    candidates = [
        ClusterCandidate(
            event_cluster_id="CLU-existing",
            title="Apple beats Q3 earnings estimates",
            published_at=datetime.utcnow() - timedelta(hours=1),
        )
    ]
    raw_event = _FakeRawEvent(title="Federal Reserve raises interest rates")

    cluster_id = assign_cluster_id(raw_event, candidates)

    assert cluster_id != "CLU-existing"
    assert cluster_id.startswith("CLU-")


def test_assign_cluster_id_no_candidates_mints_new_id():
    raw_event = _FakeRawEvent(title="Some brand new story")
    cluster_id = assign_cluster_id(raw_event, [])
    assert cluster_id.startswith("CLU-")


def test_assign_cluster_id_picks_best_match_among_several():
    candidates = [
        ClusterCandidate("CLU-weak", "Fed signals rate pause", datetime.utcnow()),
        ClusterCandidate("CLU-strong", "Apple beats Q3 earnings estimates", datetime.utcnow()),
    ]
    raw_event = _FakeRawEvent(title="Apple beats Q3 earnings estimates handily")

    assert assign_cluster_id(raw_event, candidates) == "CLU-strong"
