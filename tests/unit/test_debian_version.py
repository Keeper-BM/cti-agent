import pytest

from backend.assessment.debian_version import compare_versions


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ("2.4.52-1ubuntu4.3", "2.4.52-1ubuntu4.4", -1),
        ("2.4.52-1ubuntu4.4", "2.4.52-1ubuntu4.4", 0),
        ("2.4.52-1ubuntu4.10", "2.4.52-1ubuntu4.4", 1),
        ("1.0~rc1", "1.0", -1),
        ("1.0~~", "1.0~", -1),
        ("1.0~", "1.0", -1),
        ("1.0", "1.0a", -1),
        ("1.0a", "1.0+", -1),
        ("1.0-1", "1.0-01", 0),
        ("1.0", "1.0-0", 0),
        ("2:1.0-1", "1:99.0-1", 1),
        ("1.0-1ubuntu1~22.04.1", "1.0-1ubuntu1", -1),
        ("1.0-1ubuntu1.1", "1.0-1ubuntu1.2", -1),
    ],
)
def test_debian_order(left, right, expected):
    assert compare_versions(left, right) == expected
    assert compare_versions(right, left) == -expected


@pytest.mark.parametrize("value", ["", "abc", "1:", "x:1.0", "1.0-", "1.0/evil", "1.0 한글"])
def test_invalid_version_is_not_compared(value):
    with pytest.raises(ValueError):
        compare_versions(value, "1.0")
