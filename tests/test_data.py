from aei import data


def test_counts(ds):
    x = ds.isolates
    assert len(x) == 24571 and len(ds.cultures) == 46792
    assert int(x.first_year.sum()) == 21387 and int(x.first_30d.sum()) == 23769


def test_window_is_strictly_as_of(ds):
    w = data.window(ds.isolates, "2026-03-08", 28)
    assert w.sample_date.max() <= __import__("pandas").Timestamp("2026-03-08")
    assert w.sample_date.min() > __import__("pandas").Timestamp("2026-02-08")


def test_week_helpers():
    assert str(data.week_end(0).date()) == "2023-10-08" and data.week_of("2026-03-08") == 126
