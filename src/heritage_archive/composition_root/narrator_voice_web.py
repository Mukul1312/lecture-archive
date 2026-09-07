"""Own one loopback process and one live studio lifetime."""

from secrets import token_hex

from heritage_archive.platform.web.loopback import serve_loopback
from heritage_archive.contexts.narrator_voice.infrastructure.local_root import LocalNarrationRoot
from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.app import NarratorWebApplication
from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.security import ProcessSecurity
from .narrator_voice_live import build_live_narration


def serve_narration(root: LocalNarrationRoot) -> None:
    process_principal = token_hex(32)
    security = ProcessSecurity(token_hex(32), token_hex(32))
    studio = build_live_narration(root, process_principal=process_principal)
    try:
        application = NarratorWebApplication(security)
        serve_loopback(application)
    finally:
        studio.close()
