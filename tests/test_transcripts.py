from pathlib import Path

import pytest

from secondbrain.transcripts import (
    RateLimited,
    Segment,
    Transcript,
    TranscriptError,
    TranscriptUnavailable,
    _default_fetcher,
    chunk,
    get_transcript,
    to_text,
)

VID = "aaaaaaaaaaa"


def make_transcript(video_id=VID) -> Transcript:
    return Transcript(video_id=video_id, language="en", segments=[Segment(0.0, "hello"), Segment(65.0, "world")])


class CountingFetcher:
    def __init__(self, result=None, errors=()):
        self.calls = 0
        self.result = result
        self.errors = list(errors)

    def __call__(self, video_id: str) -> Transcript:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return self.result


def test_returns_none_when_unavailable(tmp_path: Path):
    f = CountingFetcher(errors=[TranscriptUnavailable()])
    assert get_transcript(VID, tmp_path, fetcher=f) is None


def test_unavailable_is_cached_so_not_refetched(tmp_path: Path):
    f = CountingFetcher(errors=[TranscriptUnavailable()])
    get_transcript(VID, tmp_path, fetcher=f)
    assert get_transcript(VID, tmp_path, fetcher=f) is None
    assert f.calls == 1


def test_cache_hit_skips_fetch(tmp_path: Path):
    f = CountingFetcher(result=make_transcript())
    first = get_transcript(VID, tmp_path, fetcher=f)
    second = get_transcript(VID, tmp_path, fetcher=f)
    assert f.calls == 1
    assert first == second
    assert (tmp_path / "transcripts" / f"{VID}.json").is_file()


def test_rate_limit_retries_then_gives_up(tmp_path: Path):
    f = CountingFetcher(errors=[RateLimited(), RateLimited(), RateLimited()])
    sleeps: list[float] = []
    with pytest.raises(RateLimited):
        get_transcript(VID, tmp_path, fetcher=f, max_retries=2, sleep=sleeps.append)
    assert f.calls == 3
    assert sleeps == [1, 2]


def test_rate_limit_failure_is_not_cached_and_is_distinguishable_from_no_transcript(tmp_path: Path):
    f = CountingFetcher(errors=[RateLimited()], result=make_transcript())
    with pytest.raises(RateLimited):
        get_transcript(VID, tmp_path, fetcher=f, max_retries=0, sleep=lambda s: None)
    assert get_transcript(VID, tmp_path, fetcher=f, max_retries=0, sleep=lambda s: None) is not None


def test_other_fetch_errors_propagate_and_are_not_cached(tmp_path: Path):
    f = CountingFetcher(errors=[TranscriptError("bad page")], result=make_transcript())
    with pytest.raises(TranscriptError):
        get_transcript(VID, tmp_path, fetcher=f)
    assert not (tmp_path / "transcripts" / f"{VID}.json").exists()
    assert get_transcript(VID, tmp_path, fetcher=f) is not None


def test_default_fetcher_maps_every_library_error_to_one_of_our_three(monkeypatch):
    import requests
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api import _errors as err

    cases = [
        (err.TranscriptsDisabled, TranscriptUnavailable), (err.NoTranscriptFound, TranscriptUnavailable),
        (err.VideoUnavailable, TranscriptUnavailable), (err.VideoUnplayable, TranscriptUnavailable),
        (err.AgeRestricted, TranscriptUnavailable), (err.InvalidVideoId, TranscriptUnavailable),
        (err.IpBlocked, RateLimited), (err.RequestBlocked, RateLimited), (err.PoTokenRequired, RateLimited),
        (requests.ConnectionError, RateLimited), (requests.Timeout, RateLimited),
        (err.YouTubeDataUnparsable, TranscriptError), (err.YouTubeRequestFailed, TranscriptError),
        (err.FailedToCreateConsentCookie, TranscriptError), (err.NotTranslatable, TranscriptError),
        (requests.HTTPError, TranscriptError),
    ]
    for exc_cls, expected in cases:
        def boom(self, *a, _cls=exc_cls, **k):
            raise _cls.__new__(_cls)

        monkeypatch.setattr(YouTubeTranscriptApi, "fetch", boom)
        with pytest.raises(expected) as info:
            _default_fetcher(VID)
        assert type(info.value) is expected, f"{exc_cls.__name__} -> {type(info.value).__name__}"


def test_recovers_after_one_rate_limit(tmp_path: Path):
    f = CountingFetcher(errors=[RateLimited()], result=make_transcript())
    t = get_transcript(VID, tmp_path, fetcher=f, max_retries=2, sleep=lambda s: None)
    assert t is not None and f.calls == 2


def test_corrupt_cache_file_is_refetched(tmp_path: Path):
    (tmp_path / "transcripts").mkdir()
    (tmp_path / "transcripts" / f"{VID}.json").write_text("{broken", encoding="utf-8")
    f = CountingFetcher(result=make_transcript())
    assert get_transcript(VID, tmp_path, fetcher=f) is not None
    assert f.calls == 1


@pytest.mark.parametrize("bad", ["../x", "a/b", "short", "x" * 40, ""])
def test_bad_video_id_rejected_before_touching_disk(tmp_path: Path, bad):
    with pytest.raises(ValueError):
        get_transcript(bad, tmp_path, fetcher=CountingFetcher(result=make_transcript()))
    assert not (tmp_path / "transcripts").exists()


def test_to_text_with_times_format():
    t = make_transcript()
    assert to_text(t, with_times=True) == "[00:00] hello\n[01:05] world"
    assert to_text(t) == "hello world"


def test_to_text_hours_format():
    t = Transcript(video_id=VID, language="en", segments=[Segment(3725.0, "late")])
    assert to_text(t, with_times=True) == "[1:02:05] late"


def test_chunk_never_splits_segment_and_respects_limit():
    segs = [Segment(float(i), "x" * 10) for i in range(10)]
    t = Transcript(video_id=VID, language="en", segments=segs)
    chunks = chunk(t, max_chars=35, with_times=False)
    assert all(len(c) <= 35 for c in chunks)
    joined = " ".join(chunks)
    assert joined.count("x" * 10) == 10 and "x" * 11 not in joined
    assert len(chunks) > 1


def test_chunk_keeps_timestamps_by_default():
    t = Transcript(video_id=VID, language="en", segments=[Segment(0.0, "a"), Segment(65.0, "b")])
    assert chunk(t) == ["[00:00] a\n[01:05] b"]


def test_chunk_single_oversized_segment_is_kept_whole():
    t = Transcript(video_id=VID, language="en", segments=[Segment(0.0, "y" * 100)])
    assert chunk(t, max_chars=30, with_times=False) == ["y" * 100]


def test_chunk_empty_transcript_returns_empty_list():
    assert chunk(Transcript(video_id=VID, language="en", segments=[])) == []
