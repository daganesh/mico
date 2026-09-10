"""RFC 9562 UUIDv7 generation.

Not available in the stdlib `uuid` module until Python 3.14; `mico` targets
3.11 (pyproject `requires-python`), and AD-14's dependency-minimization
policy rules out pulling a third-party `uuid7`/`uuid_utils` package for one
function. Hand-rolled per the RFC layout instead.
"""

from __future__ import annotations

import os
import time
import uuid

_VERSION = 0x7
_VARIANT = 0b10

_RAND_A_BITS = 12
_RAND_A_MASK = (1 << _RAND_A_BITS) - 1
_RAND_B_BITS = 62
_RAND_B_MASK = (1 << _RAND_B_BITS) - 1


def uuid7() -> uuid.UUID:
    """Generate a UUIDv7: 48-bit unix-ms timestamp + version + random bits.

    Layout (MSB to LSB): unix_ts_ms(48) | version(4) | rand_a(12) |
    variant(2) | rand_b(62).
    """
    unix_ts_ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF
    rand_bytes = os.urandom(10)
    rand_a = int.from_bytes(rand_bytes[0:2], "big") & _RAND_A_MASK
    rand_b = int.from_bytes(rand_bytes[2:10], "big") & _RAND_B_MASK

    uuid_int = (
        (unix_ts_ms << 80)
        | (_VERSION << 76)
        | (rand_a << 64)
        | (_VARIANT << 62)
        | rand_b
    )
    return uuid.UUID(int=uuid_int)
