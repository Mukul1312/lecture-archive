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

Cartesia documents supported TTS markup and request-level controls; the first Odia
compiler will freeze only its separately verified allowlist. Its rendered markup is
an exact billable transcript. Pricing is therefore used only for a preflight estimate:
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

- [SSE TTS API reference](https://docs.cartesia.ai/api-reference/tts/sse)
- [API conventions](https://docs.cartesia.ai/use-the-api/api-conventions)
- [Latest Sonic model](https://docs.cartesia.ai/build-with-cartesia/tts-models/latest)
- [TTS output audio format](https://docs.cartesia.ai/build-with-cartesia/capability-guides/tts-output-audio-format)
- [SSML tags](https://docs.cartesia.ai/build-with-cartesia/capability-guides/ssml-tags)
- [Custom pronunciations](https://docs.cartesia.ai/build-with-cartesia/capability-guides/custom-pronunciations)
- [Text normalization](https://docs.cartesia.ai/build-with-cartesia/capability-guides/text-normalization)
- [Pricing](https://docs.cartesia.ai/pricing)
- [Concurrency limits and timeouts](https://docs.cartesia.ai/use-the-api/concurrency-limits-and-timeouts)
