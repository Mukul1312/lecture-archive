"""Safe, context-neutral parsing for the supported Cartesia markup fragment."""

from __future__ import annotations

from dataclasses import dataclass
import re
from xml.etree.ElementTree import ParseError

from defusedxml import ElementTree as DefusedElementTree
from defusedxml.common import DefusedXmlException

from heritage_archive.kernel import ValidationError, require_canonical_text


_MAXIMUM_SOURCE_BYTES = 16_384
_MAXIMUM_CONTROLS = 64
_MAXIMUM_CONTROLS_PER_FAMILY = 16
_MAXIMUM_TOTAL_BREAK_MS = 20_000
_MAXIMUM_SPELLING_SCALARS = 64
_INTERNAL_ROOT = "_cartesia_safe_fragment"
_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")
_UNSIGNED_DECIMAL = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_DURATION = re.compile(r"^((?:0|[1-9][0-9]*)(?:\.[0-9]+)?)(ms|s)$")
_EXPECTED_ATTRIBUTES = {
    "break": ("time",),
    "speed": ("ratio",),
    "volume": ("ratio",),
    "spell": (),
}


@dataclass(frozen=True, slots=True)
class ParsedMarkupAnnotation:
    kind: str
    start_scalar: int
    end_scalar: int
    value: str

    def __post_init__(self) -> None:
        require_canonical_text(self.kind, field="markup annotation kind", nonempty=True)
        require_canonical_text(self.value, field="markup annotation value", nonempty=True)
        if (
            type(self.start_scalar) is not int
            or type(self.end_scalar) is not int
            or self.start_scalar < 0
            or self.end_scalar < self.start_scalar
        ):
            raise ValidationError("markup annotation offsets must be nonnegative scalar boundaries")


@dataclass(frozen=True, slots=True)
class MarkupTagCapability:
    tag: str
    attributes: tuple[str, ...]
    may_contain_text: bool
    may_contain_children: bool

    def __post_init__(self) -> None:
        tag = require_canonical_text(self.tag, field="markup capability tag", nonempty=True)
        if _NAME.fullmatch(tag) is None:
            raise ValidationError("markup capability tag must be a lowercase XML name")
        if type(self.attributes) is not tuple or any(
            type(attribute) is not str or _NAME.fullmatch(attribute) is None
            for attribute in self.attributes
        ):
            raise ValidationError("markup capability attributes must be lowercase XML names")
        if len(set(self.attributes)) != len(self.attributes):
            raise ValidationError("markup capability attributes must be unique")
        if type(self.may_contain_text) is not bool or type(self.may_contain_children) is not bool:
            raise ValidationError("markup capability content flags must be boolean")


@dataclass(frozen=True, slots=True)
class CartesiaMarkupCapability:
    identity: str
    tags: tuple[MarkupTagCapability, ...]

    def __post_init__(self) -> None:
        require_canonical_text(self.identity, field="markup capability identity", nonempty=True)
        if type(self.tags) is not tuple or any(
            type(tag) is not MarkupTagCapability for tag in self.tags
        ):
            raise ValidationError("markup capability tags must be an immutable tuple")
        if len({tag.tag for tag in self.tags}) != len(self.tags):
            raise ValidationError("markup capability tags must be unique")


@dataclass(frozen=True, slots=True)
class ParsedMarkupFragment:
    canonical_projection: str
    annotations: tuple[ParsedMarkupAnnotation, ...]

    def __post_init__(self) -> None:
        require_canonical_text(
            self.canonical_projection,
            field="markup canonical projection",
        )
        if type(self.annotations) is not tuple or any(
            type(annotation) is not ParsedMarkupAnnotation for annotation in self.annotations
        ):
            raise ValidationError("markup annotations must be an immutable tuple")


def _scaled_unsigned_decimal(
    raw: str,
    *,
    fractional_digits: int,
    syntax_error: str,
    precision_error: str,
) -> str:
    if _UNSIGNED_DECIMAL.fullmatch(raw) is None:
        raise ValidationError(syntax_error)
    whole, _, fraction = raw.partition(".")
    if len(fraction.rstrip("0")) > fractional_digits:
        raise ValidationError(precision_error)
    padded_fraction = (fraction + ("0" * fractional_digits))[:fractional_digits]
    return (whole + padded_fraction).lstrip("0") or "0"


def _scaled_is_between(value: str, minimum: int, maximum: int) -> bool:
    minimum_text = str(minimum)
    maximum_text = str(maximum)
    return (
        (len(value), value) >= (len(minimum_text), minimum_text)
        and (len(value), value) <= (len(maximum_text), maximum_text)
    )


def _canonical_ratio(
    raw: str,
    *,
    minimum_hundredths: int,
    maximum_hundredths: int,
    field: str,
) -> str:
    hundredths_text = _scaled_unsigned_decimal(
        raw,
        fractional_digits=2,
        syntax_error=f"{field} must be an unsigned decimal ratio",
        precision_error=f"{field} supports at most two fractional decimal places",
    )
    if not _scaled_is_between(
        hundredths_text,
        minimum_hundredths,
        maximum_hundredths,
    ):
        raise ValidationError(f"{field} is outside the verified Cartesia range")
    hundredths = int(hundredths_text)
    return f"{hundredths // 100}.{hundredths % 100:02d}"


def _canonical_break_ms(raw: str) -> str:
    match = _DURATION.fullmatch(raw)
    if match is None:
        raise ValidationError("break time must be an unsigned s or ms duration")
    milliseconds_text = _scaled_unsigned_decimal(
        match.group(1),
        fractional_digits=0 if match.group(2) == "ms" else 3,
        syntax_error="break time must be an unsigned s or ms duration",
        precision_error="break time must resolve to a whole millisecond",
    )
    if not _scaled_is_between(milliseconds_text, 10, 5_000):
        raise ValidationError("break time must be from 10 through 5,000 ms")
    return milliseconds_text


def _annotation_value(tag: str, attributes: dict[str, str]) -> str:
    if tag == "break":
        return _canonical_break_ms(attributes["time"])
    if tag == "speed":
        return _canonical_ratio(
            attributes["ratio"],
            minimum_hundredths=60,
            maximum_hundredths=150,
            field="speed ratio",
        )
    if tag == "volume":
        return _canonical_ratio(
            attributes["ratio"],
            minimum_hundredths=50,
            maximum_hundredths=200,
            field="volume ratio",
        )
    raise ValidationError("inline markup tag is not supported by the Odia compiler")


def _validate_annotation_limits(annotations: tuple[ParsedMarkupAnnotation, ...]) -> None:
    if len(annotations) > _MAXIMUM_CONTROLS:
        raise ValidationError("advanced markup may contain at most 64 controls")
    for family in ("break", "speed", "volume", "spelling"):
        if sum(annotation.kind == family for annotation in annotations) > _MAXIMUM_CONTROLS_PER_FAMILY:
            raise ValidationError(f"advanced markup may contain at most 16 {family} controls")
    if sum(int(annotation.value) for annotation in annotations if annotation.kind == "break") > _MAXIMUM_TOTAL_BREAK_MS:
        raise ValidationError("total inserted break duration may not exceed 20,000 ms")
    spelling = sorted(
        (annotation for annotation in annotations if annotation.kind == "spelling"),
        key=lambda annotation: (annotation.start_scalar, annotation.end_scalar),
    )
    if any(annotation.end_scalar - annotation.start_scalar > _MAXIMUM_SPELLING_SCALARS for annotation in spelling):
        raise ValidationError("spelling spans may contain at most 64 Unicode scalars")
    for left, right in zip(spelling, spelling[1:]):
        if right.start_scalar < left.end_scalar:
            raise ValidationError("spelling markup may not be nested or overlap")


def parse_safe_markup_fragment(
    source: str,
    capability: CartesiaMarkupCapability,
) -> ParsedMarkupFragment:
    """Parse one allowlisted markup fragment and project its exact lexical text."""
    source = require_canonical_text(source, field="advanced markup source")
    if type(capability) is not CartesiaMarkupCapability:
        raise ValidationError("markup parsing requires a CartesiaMarkupCapability")
    if len(source.encode("utf-8")) > _MAXIMUM_SOURCE_BYTES:
        raise ValidationError("advanced markup source exceeds 16,384 UTF-8 bytes")

    # The wrapped parse is authoritative. These constructs are rejected explicitly
    # because ElementTree may otherwise discard comments/PIs or resolve predefined
    # entities before the lexical projection is built.
    if "<?" in source:
        raise ValidationError("XML declarations and processing instructions are forbidden")
    if "<!" in source:
        raise ValidationError("DTD, entity declarations, comments and CDATA are forbidden")
    if "&" in source:
        raise ValidationError("XML entity references are forbidden")

    try:
        root = DefusedElementTree.fromstring(
            f"<{_INTERNAL_ROOT}>{source}</{_INTERNAL_ROOT}>",
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )
    except (DefusedXmlException, ParseError, ValueError) as error:
        raise ValidationError("advanced markup must be a well-formed safe XML fragment") from error

    capabilities = {tag.tag: tag for tag in capability.tags}
    projection_parts: list[str] = []
    annotations: list[ParsedMarkupAnnotation] = []
    scalar_offset = 0

    def append_text(value: str | None) -> None:
        nonlocal scalar_offset
        if value:
            projection_parts.append(value)
            scalar_offset += len(value)

    def visit(element: object) -> None:
        nonlocal scalar_offset
        tag = getattr(element, "tag", None)
        if type(tag) is not str or tag not in capabilities or tag not in _EXPECTED_ATTRIBUTES:
            raise ValidationError("advanced markup contains an unknown or unsupported tag")
        allowed = capabilities[tag]
        expected_attributes = _EXPECTED_ATTRIBUTES[tag]
        if allowed.attributes != expected_attributes:
            raise ValidationError("markup capability does not match the verified tag contract")
        attributes = getattr(element, "attrib", None)
        if type(attributes) is not dict or set(attributes) != set(expected_attributes):
            raise ValidationError("advanced markup tag has missing or unknown attributes")
        children = tuple(element)
        if children and not allowed.may_contain_children:
            raise ValidationError("advanced markup uses unsupported tag nesting")
        own_text = getattr(element, "text", None)
        if not allowed.may_contain_text and (
            bool(own_text) or any(bool(getattr(child, "tail", None)) for child in children)
        ):
            raise ValidationError("advanced markup tag may not contain text")

        start = scalar_offset
        if tag == "break":
            if children:
                raise ValidationError("break markup may not contain children")
            annotations.append(
                ParsedMarkupAnnotation("break", start, start, _annotation_value(tag, attributes))
            )
            return

        value = None if tag == "spell" else _annotation_value(tag, attributes)
        append_text(own_text)
        for child in children:
            visit(child)
            append_text(getattr(child, "tail", None))
        end = scalar_offset
        if end == start:
            raise ValidationError("inline markup spans must contain canonical text")
        if tag == "spell":
            value = "".join(projection_parts)[start:end]
        annotations.append(
            ParsedMarkupAnnotation(
                "spelling" if tag == "spell" else tag,
                start,
                end,
                value,
            )
        )

    append_text(root.text)
    for child in root:
        visit(child)
        append_text(child.tail)

    normalized_annotations = tuple(
        sorted(
            annotations,
            key=lambda annotation: (
                annotation.start_scalar,
                {"break": 0, "volume": 1, "speed": 2, "spelling": 3}[annotation.kind],
                annotation.end_scalar,
                annotation.value,
            ),
        )
    )
    _validate_annotation_limits(normalized_annotations)
    return ParsedMarkupFragment("".join(projection_parts), normalized_annotations)


__all__ = (
    "CartesiaMarkupCapability",
    "MarkupTagCapability",
    "ParsedMarkupAnnotation",
    "ParsedMarkupFragment",
    "parse_safe_markup_fragment",
)
