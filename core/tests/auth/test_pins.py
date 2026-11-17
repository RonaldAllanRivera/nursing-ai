import pytest
from nursing_core.auth.pins import (
    MAX_PIN_TRIES,
    PinRefused,
    check_new_pin,
    hash_pin,
    verify_pin,
)
from nursing_core.demo import DEMO_PIN


def test_max_pin_tries_is_five() -> None:
    assert MAX_PIN_TRIES == 5


@pytest.mark.parametrize(
    "pin", ["12345", "1234567", "12a456", "\uff11\uff12\uff13\uff14\uff15\uff16", "135790\n", ""]
)
def test_pin_must_be_six_ascii_digits(pin: str) -> None:
    with pytest.raises(PinRefused) as refused:
        check_new_pin(pin)
    assert refused.value.reason == "format"
    assert refused.value.args == ("A PIN is six digits.",)


@pytest.mark.parametrize("pin", ["000000", "111111", "123456", "654321", "345678"])
def test_weak_pins_refused(pin: str) -> None:
    with pytest.raises(PinRefused) as refused:
        check_new_pin(pin)
    assert refused.value.reason == "weak"
    assert pin not in str(refused.value)


@pytest.mark.parametrize("pin", ["890123", "012346", "135791", "987012"])
def test_runs_do_not_wrap_around(pin: str) -> None:
    check_new_pin(pin)


def test_demo_pin_is_accepted() -> None:
    check_new_pin(DEMO_PIN)


def test_hash_is_argon2id_and_salted() -> None:
    first = hash_pin(DEMO_PIN)
    assert first.startswith("$argon2id$")
    assert first != hash_pin(DEMO_PIN)


def test_verify_pin_right_wrong_and_garbage_hash() -> None:
    pin_hash = hash_pin(DEMO_PIN)
    assert verify_pin(pin_hash, DEMO_PIN) is True
    assert verify_pin(pin_hash, "135791") is False
    assert verify_pin("not-a-hash", DEMO_PIN) is False
    assert verify_pin("", DEMO_PIN) is False
    assert verify_pin("\u00e9" + pin_hash, DEMO_PIN) is False
    assert verify_pin(pin_hash, "\ud800") is False
