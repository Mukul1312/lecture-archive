# Cartesia Odia TTS contract snapshot

**Accessed:** 2026-09-03
**Scope:** documentation-only verification for the Narrator Voice Cartesia adapter.
No Cartesia request, synthesis, credential, private voice reference, or private
dictionary reference was used.

## Accepted public provider facts

| Fact | Accepted value |
| --- | --- |
| TTS streaming route | `POST https://api.cartesia.ai/tts/sse` |
| Authentication | `Authorization: Bearer <API key>` |
| API version header | `Cartesia-Version: 2026-08-14` |
| Immutable model policy input | `sonic-3.6-2026-08-27` |
| Language policy input | `or` |
| Audio envelope | raw `pcm_s16le`, mono, 44,100 Hz |
| Timestamp request flags | `add_timestamps=true`, `add_phoneme_timestamps=false`, `use_normalized_timestamps=false` |
| Text normalization | `normalization="off"` |
| Dictionary request field | `pronunciation_dict_id` |

The model, language, lanes, voice binding, dictionary binding, and narrator delivery
defaults are Narrator Voice policy. They do not belong to the context-neutral
`CartesiaTransportContract`.

## Markup capability and initial Odia allowlist

The dated [SSML tag guide](https://docs.cartesia.ai/build-with-cartesia/capability-guides/ssml-tags)
records the following provider syntax:

| Provider syntax | Verified semantics | Initial Odia compiler disposition |
| --- | --- | --- |
| `<speed ratio="…">…</speed>` | Ratio from 0.6 through 1.5 | Allowed in Task 3. |
| `<volume ratio="…">…</volume>` | Ratio from 0.5 through 2.0 | Allowed in Task 3. |
| `<emotion value="…">…</emotion>` | Experimental/beta emotion control | Request-level policy only; inline emotion is rejected for the initial Odia workflow. |
| `<break time="…" />` | Time accepts `s` or `ms` values | Allowed in Task 3, subject to the tighter domain/compiler range of 10–5,000 ms. |
| Paired `<spell>…</spell>` content | Preserves the enclosed canonical lexical text while directing spelling | Allowed in Task 3. |

Task 3 implements only break, speed, volume, and paired spell controls. It rejects
inline emotion even though the provider syntax exists; no parser/compiler will
silently promote experimental provider support into a Narrator Voice release policy.
The rendered markup is an exact billable transcript. Pricing is therefore used only
for a preflight estimate:
the SSE documentation does not establish authoritative per-request usage for this
adapter contract. The documentation also supplies neither an SSE TTS idempotency
mechanism nor a guarantee that `429` or `5xx` means unprocessed work, so the transport
must not replay either outcome.

## Local client-safety policy

Cartesia documentation does not prescribe SSE HTTP client timeouts, payload limits,
or a retry envelope. The following are deliberately local safety policy, not provider
guarantees, and must fail closed when exceeded:

| Setting | Value |
| --- | --- |
| Connect/write/read/operation timeout | 10 / 10 / 30 / 180 seconds |
| Maximum submissions | 3 |
| Pre-send retry backoff | 1, then 3 seconds |
| Maximum honored `Retry-After` | 30 seconds |
| Maximum SSE event | 1 MiB |
| Maximum total response | 32 MiB |
| Maximum decoded PCM | 16 MiB |
| Redirects / environment proxies | disabled (`follow_redirects=False`, `trust_env=False`) |

At PCM16 mono 44.1 kHz, 180 seconds is 15,876,000 bytes, below the 16 MiB decoded
PCM limit. The 32 MiB response limit leaves room for base64 audio expansion and SSE
framing.

## Official sources

| Facts | Official source |
| --- | --- |
| SSE endpoint, request fields, authentication and API version | [SSE TTS API reference](https://docs.cartesia.ai/api-reference/tts/sse) and [API conventions](https://docs.cartesia.ai/use-the-api/api-conventions) |
| Dated Sonic model and Odia language support | [Latest Sonic model](https://docs.cartesia.ai/build-with-cartesia/tts-models/latest) |
| Raw PCM format and sample rate | [TTS output audio format](https://docs.cartesia.ai/build-with-cartesia/capability-guides/tts-output-audio-format) |
| Speed, volume, emotion, break and spell markup | [SSML tags](https://docs.cartesia.ai/build-with-cartesia/capability-guides/ssml-tags) |
| Dictionary field | [Custom pronunciations](https://docs.cartesia.ai/build-with-cartesia/capability-guides/custom-pronunciations) |
| Normalization request value | [Text normalization](https://docs.cartesia.ai/build-with-cartesia/capability-guides/text-normalization) |
| Preflight estimate semantics | [Pricing](https://docs.cartesia.ai/pricing) |
| Concurrency/429 behavior and timeout documentation scope | [Concurrency limits and timeouts](https://docs.cartesia.ai/use-the-api/concurrency-limits-and-timeouts) |
