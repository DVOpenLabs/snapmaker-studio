"""Unit tests for the request-input validators, added alongside
optional_positive_float_list (the confirmed_nozzle_diameters input)."""
import pytest

from snapstudio_api.request_validation import ValidationError, optional_positive_float_list


def test_optional_positive_float_list_absent_key_returns_none():
    assert optional_positive_float_list({}, "confirmed_nozzle_diameters") is None


def test_optional_positive_float_list_null_returns_none():
    assert optional_positive_float_list({"confirmed_nozzle_diameters": None},
                                        "confirmed_nozzle_diameters") is None


def test_optional_positive_float_list_accepts_real_values():
    out = optional_positive_float_list({"confirmed_nozzle_diameters": [0.4, 0.6]},
                                       "confirmed_nozzle_diameters")
    assert out == [0.4, 0.6]


def test_optional_positive_float_list_rejects_empty_list():
    with pytest.raises(ValidationError):
        optional_positive_float_list({"confirmed_nozzle_diameters": []},
                                     "confirmed_nozzle_diameters")


def test_optional_positive_float_list_rejects_non_list():
    with pytest.raises(ValidationError):
        optional_positive_float_list({"confirmed_nozzle_diameters": "0.4"},
                                     "confirmed_nozzle_diameters")


def test_optional_positive_float_list_rejects_zero_and_negative():
    with pytest.raises(ValidationError):
        optional_positive_float_list({"confirmed_nozzle_diameters": [0.4, 0]},
                                     "confirmed_nozzle_diameters")
    with pytest.raises(ValidationError):
        optional_positive_float_list({"confirmed_nozzle_diameters": [-0.4]},
                                     "confirmed_nozzle_diameters")


def test_optional_positive_float_list_rejects_non_numeric_items():
    with pytest.raises(ValidationError):
        optional_positive_float_list({"confirmed_nozzle_diameters": [0.4, "big"]},
                                     "confirmed_nozzle_diameters")


def test_optional_positive_float_list_rejects_bool_items():
    """bool is an int subclass in Python — must be rejected explicitly, matching
    _as_number's own existing bool guard elsewhere in this module."""
    with pytest.raises(ValidationError):
        optional_positive_float_list({"confirmed_nozzle_diameters": [True]},
                                     "confirmed_nozzle_diameters")


def test_optional_positive_float_list_is_length_bounded():
    """A malformed/hostile body can't make Studio allocate an unbounded list —
    this is a loopback API, but bounding cost-of-input is cheap and correct
    regardless of who can reach it."""
    with pytest.raises(ValidationError):
        optional_positive_float_list({"confirmed_nozzle_diameters": [0.4] * 100},
                                     "confirmed_nozzle_diameters", max_len=8)
