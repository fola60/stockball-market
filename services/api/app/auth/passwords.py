from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os

_N = 2**14
_R = 8
_P = 1
_DKLEN = 32


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN
    )
    return "$".join(
        (
            "scrypt",
            f"n={_N},r={_R},p={_P}",
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        )
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, parameters, salt_value, digest_value = encoded.split("$", 3)
        if algorithm != "scrypt":
            return False
        parsed = dict(item.split("=", 1) for item in parameters.split(","))
        salt = base64.urlsafe_b64decode(salt_value.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_value.encode("ascii"))
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(parsed["n"]),
            r=int(parsed["r"]),
            p=int(parsed["p"]),
            dklen=len(expected),
        )
    except (binascii.Error, ValueError, KeyError):
        return False
    return hmac.compare_digest(actual, expected)
