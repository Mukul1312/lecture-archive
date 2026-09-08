"""Own one loopback process and one live studio lifetime."""

from secrets import token_hex
from importlib.resources import files

from heritage_archive.platform.web.loopback import serve_loopback
from heritage_archive.contexts.narrator_voice.infrastructure.local_root import LocalNarrationRoot
from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.app import NarratorWebApplication
from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.generation import ProcessGenerationControl
from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.security import ProcessSecurity
from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.routes import AuthoringBindings, NarrationAuthoringRoutes
from heritage_archive.contexts.narrator_voice.domain.values import AuthorityScope, AuthorityOperation, Lane
from .narrator_voice_live import _Identifiers, build_live_narration


def build_authoring_bindings(policies, process_principal: str) -> AuthoringBindings:
    profiles = {Lane.B: policies.lane_b, Lane.C: policies.lane_c}

    def scope(lane, episode_id, valid_from, valid_until):
        policy = policies.resolve_lane_b_diary() if lane is Lane.B else policies.resolve_lane_c_intro(episode_id)
        contract = policy.contract
        return AuthorityScope(contract.speaker_binding, contract.voice_binding, contract.language,
                              contract.purpose, contract.intended_episode_id, frozenset(AuthorityOperation),
                              valid_from, valid_until)

    return AuthoringBindings(process_principal, lambda lane: profiles[lane].authorization_record_id,
                             scope, lambda lane: profiles[lane].dictionary_binding)


def serve_narration(root: LocalNarrationRoot) -> None:
    process_principal = token_hex(32)
    session_token = token_hex(32)
    while session_token == process_principal:
        session_token = token_hex(32)
    csrf_token = token_hex(32)
    while csrf_token in (process_principal, session_token):
        csrf_token = token_hex(32)
    security = ProcessSecurity(session_token, csrf_token)
    generation = ProcessGenerationControl(session_token)
    identifiers = _Identifiers()
    studio = build_live_narration(root, process_principal=process_principal, identifiers=identifiers)
    try:
        routes = NarrationAuthoringRoutes(
            studio.handlers,
            build_authoring_bindings(studio.policies, process_principal),
            identifiers,
            generation,
        )
        package = files("heritage_archive.contexts.narrator_voice.infrastructure.loopback_web")
        assets = {"/assets/studio.css": package.joinpath("assets", "studio.css").read_bytes(),
                  "/assets/studio.js": package.joinpath("assets", "studio.js").read_bytes()}
        application = NarratorWebApplication(security, dispatch=routes, render_root=routes.render_root, assets=assets)
        serve_loopback(application)
    finally:
        studio.close()
