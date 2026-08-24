"""Evidence-preserving decimal time conversion."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import re

from .errors import ValidationError


_DECIMAL_TOKEN = re.compile(
    r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$"
)
_MICROSECONDS_PER_SECOND = Decimal(1_000_000)


@dataclass(frozen=True, slots=True)
class DecimalTimeConversion:
    microseconds: int
    rounded: bool
    original_token: str


def decimal_seconds_to_microseconds(value: Decimal | str) -> DecimalTimeConversion:
    if isinstance(value, Decimal):
        seconds = value
        original_token = str(value)
    elif isinstance(value, str) and _DECIMAL_TOKEN.fullmatch(value) is not None:
        original_token = value
        try:
            seconds = Decimal(value)
        except InvalidOperation as error:
            raise ValidationError("invalid decimal seconds token") from error
    else:
        raise ValidationError("seconds must be a Decimal or decimal token string")

    if not seconds.is_finite():
        raise ValidationError("seconds must be finite")
    if seconds < 0:
        raise ValidationError("seconds must not be negative")

    scaled = seconds * _MICROSECONDS_PER_SECOND
    integral = scaled.to_integral_value(rounding=ROUND_HALF_EVEN)
    return DecimalTimeConversion(
        microseconds=int(integral),
        rounded=scaled != integral,
        original_token=original_token,
    )
