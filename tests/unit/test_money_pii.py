"""PII scrubber + money formatting (Rules §1.8, §7.2)."""

import pytest
from reflex.core.money import format_inr
from reflex.core.pii import assert_no_pii, scrub, scrub_payload


def test_indian_grouping():
    assert format_inr(24_100_000) == "₹2,41,000"
    assert format_inr(299_00) == "₹299"
    assert format_inr(150) == "₹1.50"
    assert format_inr(0) == "₹0"
    assert format_inr(-150) == "-₹1.50"


def test_scrub_patterns():
    assert "[REDACTED]" in scrub("mail me at foo.bar@x.com now")
    assert "[REDACTED]" in scrub("vpa arjun99@ybl")
    assert "[REDACTED]" in scrub("call 9876543210")
    assert "[REDACTED]" in scrub("card 4242 4242 4242 4242")
    assert scrub("no sensitive data here") == "no sensitive data here"


def test_assert_no_pii_raises():
    assert_no_pii("clean text")
    with pytest.raises(ValueError):
        assert_no_pii("email a@b.com inside")
    with pytest.raises(ValueError):
        assert_no_pii("vpa user@oksbi")


def test_scrub_payload_recursive():
    out = scrub_payload({"a": "x@y.com", "b": ["9876500000", {"c": "ok"}]})
    assert out["a"] == "[REDACTED]"
    assert out["b"][0] == "[REDACTED]"
    assert out["b"][1]["c"] == "ok"
