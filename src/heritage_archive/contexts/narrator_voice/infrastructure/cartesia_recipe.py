"""Cartesia-specific recipe authoring and deterministic preview compilation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from heritage_archive.kernel import ValidationError
from heritage_archive.platform.cartesia.contract import CARTESIA_TRANSPORT_CONTRACT
from heritage_archive.platform.cartesia.markup import (
    CartesiaMarkupCapability,
    MarkupTagCapability,
    ParsedMarkupAnnotation,
    parse_safe_markup_fragment,
)

from ..application.ports import (
    PreviewCompilerResult,
    RecipeAuthoringRequest,
    RecipeAuthoringResult,
    RecipeCompileRequest,
)
from ..domain.evidence import AuthoritySnapshot
from ..domain.ids import NarrationJobId, PassageId, PassageRenderRecipeId
from ..domain.values import (
    BreakControl,
    EffectiveTakeSettings,
    FixedTwoDecimal,
    NonNegativeDecimal,
    PassageRenderRecipe,
    PassageText,
    ReleaseSynthesisContract,
    RenderControl,
    SpeedControl,
    SpellingControl,
    TextSpan,
    VolumeControl,
)


CARTESIA_RECIPE_COMPILER_VERSION = "cartesia-odia-recipe-compiler-v1"
CARTESIA_BILLABLE_RULE = "cartesia-rendered-unicode-scalars-2026-09-03"
CARTESIA_ODIA_MARKUP_CAPABILITY = CartesiaMarkupCapability(
    identity="cartesia-ssml-2026-09-03-or-v1",
    tags=(
        MarkupTagCapability("break", ("time",), False, False),
        MarkupTagCapability("speed", ("ratio",), True, False),
        MarkupTagCapability("volume", ("ratio",), True, False),
        MarkupTagCapability("spell", (), True, False),
    ),
)

_CONTROL_TAG = {
    BreakControl: "break",
    SpeedControl: "speed",
    VolumeControl: "volume",
    SpellingControl: "spell",
}
_CONTROL_RANK = {
    VolumeControl: 0,
    BreakControl: 1,
    SpeedControl: 2,
    SpellingControl: 3,
}
_TAG_CONTRACT = {
    "break": (("time",), False),
    "speed": (("ratio",), True),
    "volume": (("ratio",), True),
    "spell": ((), True),
}


def _validate_contract(
    contract: object,
    capability: CartesiaMarkupCapability,
) -> ReleaseSynthesisContract:
    if type(contract) is not ReleaseSynthesisContract:
        raise ValidationError("Cartesia compilation requires a ReleaseSynthesisContract")
    if contract.provider.casefold() != "cartesia":
        raise ValidationError("Cartesia compiler cannot compile another provider's contract")
    if contract.api_schema != CARTESIA_TRANSPORT_CONTRACT.api_version:
        raise ValidationError("release contract API schema does not match the Cartesia transport contract")
    if contract.capability_snapshot != capability.identity:
        raise ValidationError("release contract capability snapshot does not match the compiler capability")
    return contract


def _require_capability_tag(
    capability: CartesiaMarkupCapability,
    tag: str,
) -> None:
    found = next((item for item in capability.tags if item.tag == tag), None)
    if found is None:
        raise ValidationError(f"the frozen markup capability does not permit {tag}")
    expected_attributes, expected_text = _TAG_CONTRACT[tag]
    if (
        found.attributes != expected_attributes
        or found.may_contain_text is not expected_text
        or found.may_contain_children
    ):
        raise ValidationError("the frozen markup capability does not match the v1 tag contract")


def _control_sort_key(control: RenderControl) -> tuple[int, int, int, str]:
    if type(control) is BreakControl:
        return control.boundary, _CONTROL_RANK[BreakControl], control.boundary, str(control.duration_ms)
    value = control.spelling if type(control) is SpellingControl else control.value.value
    return control.span.start, _CONTROL_RANK[type(control)], control.span.end, value


def _validate_and_sort_controls(
    controls: object,
    text: PassageText,
    capability: CartesiaMarkupCapability,
) -> tuple[RenderControl, ...]:
    allowed_types = {BreakControl, SpeedControl, VolumeControl, SpellingControl}
    if type(controls) is not tuple or any(type(control) not in allowed_types for control in controls):
        raise ValidationError("Cartesia recipe controls must be an immutable tuple of supported controls")
    if len(controls) > 64:
        raise ValidationError("a recipe may contain at most 64 controls")
    if len(set(controls)) != len(controls):
        raise ValidationError("a Cartesia recipe may not contain duplicate controls")

    for family in allowed_types:
        if sum(type(control) is family for control in controls) > 16:
            raise ValidationError(f"a recipe may contain at most 16 {family.__name__} values")

    breaks = tuple(control for control in controls if type(control) is BreakControl)
    if sum(control.duration_ms for control in breaks) > 20_000:
        raise ValidationError("total inserted break duration may not exceed 20,000 ms")
    if len({control.boundary for control in breaks}) != len(breaks):
        raise ValidationError("only one break is permitted at a scalar boundary")

    spans = []
    for control in controls:
        tag = _CONTROL_TAG[type(control)]
        _require_capability_tag(capability, tag)
        if type(control) is BreakControl:
            if control.boundary > text.scalar_length:
                raise ValidationError("break boundary is outside passage text")
            continue
        if control.span.end > text.scalar_length:
            raise ValidationError("render-control span is outside passage text")
        if type(control) is SpeedControl and not Decimal("0.60") <= Decimal(control.value.value) <= Decimal("1.50"):
            raise ValidationError("speed ratio is outside the verified Cartesia range")
        if type(control) is VolumeControl and not Decimal("0.50") <= Decimal(control.value.value) <= Decimal("2.00"):
            raise ValidationError("volume ratio is outside the verified Cartesia range")
        if type(control) is SpellingControl and control.spelling != text.value[control.span.start:control.span.end]:
            raise ValidationError("spelling intent must map to the exact canonical display span")
        spans.append((control.span.start, control.span.end, control))

    spans.sort(key=lambda item: (item[0], item[1], _CONTROL_RANK[type(item[2])]))
    for left, right in zip(spans, spans[1:]):
        if right[0] < left[1]:
            raise ValidationError("inline Cartesia spans may not cross, nest or overlap")
    if any(start < control.boundary < end for start, end, _ in spans for control in breaks):
        raise ValidationError("a break may not occur inside an inline Cartesia span")

    return tuple(sorted(controls, key=_control_sort_key))


def _controls_from_annotations(
    annotations: tuple[ParsedMarkupAnnotation, ...],
) -> tuple[RenderControl, ...]:
    controls: list[RenderControl] = []
    for annotation in annotations:
        if annotation.kind == "break":
            controls.append(BreakControl(annotation.start_scalar, int(annotation.value)))
        elif annotation.kind == "speed":
            controls.append(
                SpeedControl(
                    TextSpan(annotation.start_scalar, annotation.end_scalar),
                    FixedTwoDecimal(annotation.value),
                )
            )
        elif annotation.kind == "volume":
            controls.append(
                VolumeControl(
                    TextSpan(annotation.start_scalar, annotation.end_scalar),
                    FixedTwoDecimal(annotation.value),
                )
            )
        elif annotation.kind == "spelling":
            controls.append(
                SpellingControl(
                    TextSpan(annotation.start_scalar, annotation.end_scalar),
                    annotation.value,
                )
            )
        else:
            raise ValidationError("parsed markup contains an unsupported annotation")
    return tuple(controls)


def _escape_text(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _opening_tag(control: RenderControl) -> str:
    if type(control) is SpeedControl:
        return f'<speed ratio="{control.value.value}">'
    if type(control) is VolumeControl:
        return f'<volume ratio="{control.value.value}">'
    if type(control) is SpellingControl:
        return "<spell>"
    raise ValidationError("break controls do not have an opening tag")


def _closing_tag(control: RenderControl) -> str:
    if type(control) is SpeedControl:
        return "</speed>"
    if type(control) is VolumeControl:
        return "</volume>"
    if type(control) is SpellingControl:
        return "</spell>"
    raise ValidationError("break controls do not have a closing tag")


def _render_transcript(text: PassageText, controls: tuple[RenderControl, ...]) -> str:
    openings = {
        control.span.start: control
        for control in controls
        if type(control) is not BreakControl
    }
    closings = {
        control.span.end: control
        for control in controls
        if type(control) is not BreakControl
    }
    breaks = {
        control.boundary: control
        for control in controls
        if type(control) is BreakControl
    }
    rendered: list[str] = []
    for boundary in range(text.scalar_length + 1):
        closing = closings.get(boundary)
        if closing is not None:
            rendered.append(_closing_tag(closing))
        pause = breaks.get(boundary)
        if pause is not None:
            rendered.append(f'<break time="{pause.duration_ms}ms"/>')
        opening = openings.get(boundary)
        if opening is not None:
            rendered.append(_opening_tag(opening))
        if boundary < text.scalar_length:
            rendered.append(_escape_text(text.value[boundary]))
    return "".join(rendered)


@dataclass(frozen=True, slots=True)
class CartesiaRecipeCompiler:
    capability: CartesiaMarkupCapability = CARTESIA_ODIA_MARKUP_CAPABILITY

    def __post_init__(self) -> None:
        if type(self.capability) is not CartesiaMarkupCapability:
            raise ValidationError("Cartesia recipe compiler requires a frozen markup capability")

    def compile_recipe(self, request: RecipeAuthoringRequest) -> RecipeAuthoringResult:
        if type(request) is not RecipeAuthoringRequest:
            raise ValidationError("recipe authoring requires a RecipeAuthoringRequest")
        if (
            type(request.job_id) is not NarrationJobId
            or type(request.passage_id) is not PassageId
            or type(request.recipe_id) is not PassageRenderRecipeId
            or type(request.text) is not PassageText
            or type(request.text_revision) is not int
            or request.text_revision < 1
            or type(request.recipe_revision) is not int
            or request.recipe_revision < 1
        ):
            raise ValidationError("recipe authoring request has invalid identity or revision facts")
        _validate_contract(request.contract, self.capability)

        if request.advanced_source is None:
            controls = request.structured_controls
            projection = request.text.value
        else:
            if type(request.advanced_source) is not str or not request.advanced_source:
                raise ValidationError("Advanced recipe authoring requires a nonempty source")
            if request.structured_controls != ():
                raise ValidationError("Advanced recipe authoring cannot include structured controls")
            parsed = parse_safe_markup_fragment(request.advanced_source, self.capability)
            projection = parsed.canonical_projection
            if projection != request.text.value:
                raise ValidationError("advanced markup must project to the exact canonical passage text")
            controls = _controls_from_annotations(parsed.annotations)

        normalized = _validate_and_sort_controls(controls, request.text, self.capability)
        recipe = PassageRenderRecipe(
            request.recipe_id,
            request.recipe_revision,
            request.text_revision,
            request.text.digest,
            CARTESIA_RECIPE_COMPILER_VERSION,
            normalized,
        )
        recipe.validate_for(request.text)
        return RecipeAuthoringResult(recipe, projection, ())

    def compile(self, request: RecipeCompileRequest) -> PreviewCompilerResult:
        if type(request) is not RecipeCompileRequest:
            raise ValidationError("recipe preview requires a RecipeCompileRequest")
        if (
            type(request.job_id) is not NarrationJobId
            or type(request.text) is not PassageText
            or type(request.recipe) is not PassageRenderRecipe
            or type(request.settings) is not EffectiveTakeSettings
            or type(request.authority_snapshot) is not AuthoritySnapshot
            or type(request.text_revision) is not int
            or request.text_revision < 1
        ):
            raise ValidationError("recipe preview request does not contain exact frozen facts")
        _validate_contract(request.contract, self.capability)
        if request.recipe.text_revision != request.text_revision:
            raise ValidationError("recipe text revision does not match the preview text revision")
        if request.recipe.compiler_version != CARTESIA_RECIPE_COMPILER_VERSION:
            raise ValidationError("recipe compiler version does not match this Cartesia compiler")
        controls = _validate_and_sort_controls(request.recipe.controls, request.text, self.capability)
        if controls != request.recipe.controls:
            raise ValidationError("recipe controls are not in canonical deterministic order")
        request.recipe.validate_for(request.text)

        rendered = _render_transcript(request.text, controls)
        if len(rendered.encode("utf-8")) > 16_384:
            raise ValidationError("advanced compiler output must not exceed 16,384 UTF-8 bytes")
        billable_characters = len(rendered)
        return PreviewCompilerResult(
            CARTESIA_RECIPE_COMPILER_VERSION,
            f"{CARTESIA_TRANSPORT_CONTRACT.origin}{CARTESIA_TRANSPORT_CONTRACT.sse_path}",
            rendered,
            request.text.value,
            True,
            "off",
            CARTESIA_BILLABLE_RULE,
            billable_characters,
            NonNegativeDecimal(str(billable_characters)),
        )


__all__ = (
    "CARTESIA_BILLABLE_RULE",
    "CARTESIA_ODIA_MARKUP_CAPABILITY",
    "CARTESIA_RECIPE_COMPILER_VERSION",
    "CartesiaRecipeCompiler",
)
