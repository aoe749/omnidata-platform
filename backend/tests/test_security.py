import time

import pytest

from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

SECRET = "x" * 40


def test_password_roundtrip_and_salting():
    first, second = hash_password("correct horse"), hash_password("correct horse")
    assert first != second  # unique salts
    assert verify_password("correct horse", first)
    assert not verify_password("wrong", first)


@pytest.mark.parametrize("stored", ["", "plain", "scrypt$1$2", "bcrypt$a$b$c$d$e"])
def test_verify_rejects_malformed_hashes(stored):
    assert verify_password("anything", stored) is False


def test_token_roundtrip():
    token = create_access_token(subject="42", secret=SECRET, algorithm="HS256", minutes=5)
    assert decode_access_token(token, secret=SECRET, algorithm="HS256") == "42"


def test_token_rejects_wrong_secret_and_garbage():
    token = create_access_token(subject="42", secret=SECRET, algorithm="HS256", minutes=5)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, secret="y" * 40, algorithm="HS256")
    with pytest.raises(InvalidTokenError):
        decode_access_token("not-a-token", secret=SECRET, algorithm="HS256")


def test_expired_token_is_rejected():
    token = create_access_token(subject="1", secret=SECRET, algorithm="HS256", minutes=-1)
    time.sleep(0.01)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, secret=SECRET, algorithm="HS256")
