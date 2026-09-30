from app.security import LoginThrottle, hash_password, verify_password


def test_password_hash_uses_salted_scrypt():
    encoded = hash_password("correct horse battery staple")
    assert encoded.startswith("scrypt$")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("incorrect", encoded)


def test_login_throttle_expires_and_resets_attempts():
    throttle = LoginThrottle(max_attempts=2, window_seconds=60)
    throttle.record_failure("user")
    assert not throttle.is_blocked("user")
    throttle.record_failure("user")
    assert throttle.is_blocked("user")
    throttle.reset("user")
    assert not throttle.is_blocked("user")
