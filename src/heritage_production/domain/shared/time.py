"""Evidence-preserving decimal time conversion."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

from .errors import ValidationError


_DECIMAL_TOKEN = re.compile(
    r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$"
)


@dataclass(frozen=True, slots=True)
class DecimalTimeConversion:
    microseconds: int
    rounded: bool
    original_token: str

    def __post_init__(self) -> None:
        if type(self.microseconds) is not int:
            raise ValidationError("microseconds must be an integer")
        if type(self.rounded) is not bool:
            raise ValidationError("rounded must be a boolean")
        if type(self.original_token) is not str:
            raise ValidationError("original_token must be a string")


def decimal_seconds_to_microseconds(value: Decimal | str) -> DecimalTimeConversion:
    if type(value) is Decimal:
        seconds = value
        original_token = str(value)
    elif type(value) is str and _DECIMAL_TOKEN.fullmatch(value) is not None:
        original_token = value
        try:
            seconds = Decimal(value)
        except InvalidOperation as error:
            raise ValidationError("invalid decimal seconds token") from error
    else:
        raise ValidationError("seconds must be a Decimal or decimal token string")

    if not seconds.is_finite():
        raise ValidationError("seconds must be finite")
    decimal_tuple = seconds.as_tuple()
    coefficient = 0
    for digit in decimal_tuple.digits:
        coefficient = coefficient * 10 + digit
    if decimal_tuple.sign and coefficient:
        raise ValidationError("seconds must not be negative")

    exponent = decimal_tuple.exponent
    if type(exponent) is not int:
        raise ValidationError("seconds must be finite")
    microsecond_exponent = exponent + 6
    if microsecond_exponent >= 0:
        microseconds = coefficient * 10**microsecond_exponent
        rounded = False
    else:
        divisor = 10 ** -microsecond_exponent
        microseconds, remainder = divmod(coefficient, divisor)
        rounded = remainder != 0
        doubled_remainder = remainder * 2
        if doubled_remainder > divisor or (
            doubled_remainder == divisor and microseconds % 2
        ):
            microseconds += 1

    return DecimalTimeConversion(
        microseconds=microseconds,
        rounded=rounded,
        original_token=original_token,
    )
