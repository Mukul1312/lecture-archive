"""Process-scoped authority for the one configured local operator."""
from dataclasses import dataclass, field
from secrets import compare_digest

from heritage_archive.kernel import ActorId, ValidationError

from ..application.ports import PrincipalAuthority
from ..domain.errors import AuthorizationDenied
from ..domain.evidence import ReviewAuthority


@dataclass(frozen=True, slots=True)
class SingleOperatorActorResolver:
    process_principal: str = field(repr=False)
    actor_id: ActorId

    def __post_init__(self) -> None:
        if (
            type(self.process_principal) is not str
            or not self.process_principal
            or not self.process_principal.isascii()
            or type(self.actor_id) is not ActorId
        ):
            raise ValidationError("invalid_single_operator_configuration")

    def resolve_principal(self, principal: str) -> PrincipalAuthority:
        if (
            type(principal) is not str
            or not principal
            or not principal.isascii()
            or not compare_digest(principal, self.process_principal)
        ):
            raise AuthorizationDenied("principal_not_authorized")
        return PrincipalAuthority(self.actor_id, True, ReviewAuthority.OPERATIONAL, None)
