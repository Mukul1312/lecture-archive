export const meta = {
  name: 'commercial-asr-free-credit-survey',
  description: 'Research Deepgram and comparable commercial speech-to-text services with free allowances for the SSGGSM corpus, then verify pricing, terms and features at source',
  phases: [
    { title: 'Research', detail: 'Deepgram product facts, independent accuracy evidence, comparable commercial services with free allowances' },
    { title: 'Verify', detail: 'check prices, free credits, terms and features at primary sources' },
  ],
}

const CONTEXT = `
CONTEXT. A volunteer (the "steward") is transcribing an archive of about 3,766 unique lectures by Srila Gour Govinda Swami: 1985-1996 cassette recordings, digitised as mp3 and publicly hosted on archive.org (so each file already has a public download URL). The speaker is a native Odia speaker lecturing in Indian-accented English at about 94 words a minute, with chanted Sanskrit verse, Sanskrit/Bengali names and terms inside English sentences (Krsna, Mahaprabhu, bhakti, Markandeya), and occasional Bengali songs. Total audio is roughly 3,450 hours (an unmeasured estimate: 3,766 lectures x ~55 minutes). Transcripts will be published free on a read-while-listening website that highlights each word, so WORD-LEVEL TIMESTAMPS are required, and per-word confidence is valuable (it is the one error signal we have calibrated).

WHAT WE ALREADY KNOW from our own human-verified 69.8-minute reference lecture: local faster-whisper medium scores English 19.5% of words wrong or missing, Sanskrit 58.7% unrecognisable, WER 27.7%. The largest error class is dropped words (41% of errors). A glossary initial_prompt did nothing for Whisper. Open-model research has shortlisted NVIDIA Parakeet TDT 0.6B v2 and Qwen3-ASR 1.7B to test locally.

THE STEWARD'S MONEY CONSTRAINT. He has no budget for recurring paid APIs. What IS in scope: free sign-up credits and free monthly tiers, used honestly; and knowing the real price of the whole corpus so he can decide whether a one-time spend is ever worth it. Never suggest opening multiple accounts to multiply free credits - that breaks terms of service; say so if a vendor's terms forbid it. Scoring one 70-minute reference lecture per service is a tiny amount of audio, so the first practical question for every service is simply: can it be tested on our reference for free?

RESEARCH RULES.
- Today is 2026-09-22. Pricing, free credits and model names change often; your memory is likely out of date. Get CURRENT figures from the vendor's own pricing, docs and terms pages, and record the date you read them.
- Every factual claim needs a source URL. Distinguish vendor claims from independent measurements explicitly. Mark anything unverified as UNVERIFIED.
- Tools: WebSearch and WebFetch (load them with ToolSearch if not already available). The Firecrawl CLI also works through Bash: npx -y firecrawl-cli search "query" and npx -y firecrawl-cli scrape URL - use it for JavaScript-rendered pricing pages that WebFetch cannot read. Firecrawl credits are limited (about 690 left for the whole team): spend at most 40 credits yourself, NEVER scrape PDFs with Firecrawl, and prefer WebFetch where it works.
- Do NOT sign up for anything, create accounts, call any paid API, install packages, or modify files in the repository at C:\\Users\\Mukul\\code\\personal-projects\\lecture-archive except your own notes file below. Do NOT commit.
- DURABILITY: write your findings as you go to C:\\Users\\Mukul\\code\\personal-projects\\lecture-archive\\data\\research\\commercial-asr-2026-09\\<your-key>.md (create the directory; it is gitignored).
`

const SERVICE_SCHEMA = {
  type: 'object',
  properties: {
    services: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          service: { type: 'string', description: 'Vendor and the specific model(s), e.g. "Deepgram Nova-3".' },
          free_allowance: { type: 'string', description: 'Exact free credit or free tier, expiry, whether a card is required, date read.' },
          price_per_audio_hour: { type: 'string', description: 'Pay-as-you-go price for pre-recorded batch transcription with the features we need, per audio hour.' },
          corpus_cost_3450h: { type: 'string', description: 'Cost for ~3,450 audio hours, with the arithmetic, and how many hours the free allowance covers.' },
          word_timestamps_and_confidence: { type: 'string' },
          languages_relevant: { type: 'string', description: 'Indian English, Hindi, Bengali, Odia, Sanskrit; code-switching support.' },
          custom_vocabulary: { type: 'string', description: 'Keyterm prompting, custom vocabulary or boosting: limits, which models and languages, extra cost.' },
          url_ingestion_and_limits: { type: 'string', description: 'Can it fetch audio from a public URL (archive.org), file size and duration limits, concurrency and rate limits.' },
          data_terms: { type: 'string', description: 'Data retention, whether customer audio is used for training by default and how to opt out, who owns the transcripts, any restriction on publishing them.' },
          accuracy_evidence: { type: 'string', description: 'Numbers with sources, marked vendor or independent; especially accented, Indian, noisy or long-form speech.' },
          fit_for_this_corpus: { type: 'string' },
          sources: { type: 'array', items: { type: 'string' } },
        },
        required: ['service', 'free_allowance', 'price_per_audio_hour', 'word_timestamps_and_confidence', 'data_terms', 'accuracy_evidence', 'fit_for_this_corpus', 'sources'],
      },
    },
    findings: { type: 'array', items: { type: 'string' } },
    unverified: { type: 'array', items: { type: 'string' } },
  },
  required: ['services', 'findings', 'unverified'],
}

const SWEEPS = [
  {
    key: 'deepgram',
    title: 'Deepgram, from its own documentation',
    prompt: `${CONTEXT}
YOUR ANGLE: DEEPGRAM, in depth, from its own pricing page, documentation, changelog and terms.
Establish: the current speech-to-text models for pre-recorded audio (Nova-3 and any successor released in 2026, Nova-3 multilingual, "Flux" if relevant, any hosted Whisper) and which is recommended for accented English; the exact free sign-up credit (amount, expiry, card required?) and the current pay-as-you-go price per minute for pre-recorded Nova-3 with the add-ons we would use; English variants (is there en-IN?), Hindi, Bengali, Odia, Sanskrit, and multilingual code-switching - which languages the code-switching model covers; KEYTERM PROMPTING (limits on number of terms, which models and languages, extra cost, any published accuracy effect) - this matters because Whisper's glossary prompt did nothing for us and keyterm prompting is a different mechanism; word timestamps and per-word confidence in the response; how it handles hour-long files (limits, timeouts, callbacks) and whether it can fetch audio straight from a public URL; rate and concurrency limits on the free tier; data terms - retention, whether audio is used to train models by default (the Model Improvement Program) and how to opt out, ownership of the transcript, anything restricting publication; and whether any self-hosted or on-premise option exists and at what scale.
Then answer directly: how much of our reference and of the ~3,450-hour corpus would the free credit cover, what would the whole corpus cost, and what exactly would a fair test on our 69.8-minute reference look like (which model, which options, which keyterms)?`,
  },
  {
    key: 'evidence',
    title: 'independent evidence on Deepgram and its peers',
    prompt: `${CONTEXT}
YOUR ANGLE: INDEPENDENT accuracy evidence for Deepgram and the other commercial services, as distinct from vendor marketing.
Find third-party measurements that include Deepgram (Nova-3 or Nova-2) alongside Whisper, Parakeet, AssemblyAI, Speechmatics, ElevenLabs Scribe, Google, Azure, Soniox or Gladia: for example the Artificial Analysis speech-to-text leaderboard, academic papers (e.g. the 2026 AppTek call-centre dialogue benchmark with an en_IN accent set, Voice of India, Svarah or other Indian-English evaluations, AfriSpeech or other accented-English studies), and credible practitioner benchmarks. Record the test conditions for every number (read vs conversational, clean vs noisy, short vs long-form, which accent), because leaderboards on clean speech have already misled us once: a model ranked higher on leaderboards was far worse on our Sanskrit.
Specifically look for: accuracy on INDIAN-ACCENTED English; behaviour on long recordings (does it drop stretches of speech?); noisy or archival audio; code-switching between English and Indian languages; any evidence about keyterm or custom-vocabulary features actually improving rare-word accuracy; and any evidence at all on Sanskrit or chanted material.
Also note any vendor benchmark claims, clearly labelled as vendor claims, and whether independent results contradict them.`,
  },
  {
    key: 'peers',
    title: 'comparable commercial services with free allowances',
    prompt: `${CONTEXT}
YOUR ANGLE: the COMMERCIAL ALTERNATIVES to Deepgram that offer free credits or free tiers, so Deepgram is judged against its real peers.
Cover at least: AssemblyAI (current Universal model), Speechmatics (it markets accent robustness and has a free tier), ElevenLabs Scribe, Soniox, Gladia, Google Cloud Speech-to-Text (Chirp models), Microsoft Azure AI Speech (it has a free monthly tier; note Azure previously looked good on price and word timestamps for this steward's Odia work), Rev.ai, and OpenAI's hosted transcription models. Add any other serious service you find with a meaningful free allowance.
For each: current free allowance (one-off credit or monthly hours, expiry, card required); pay-as-you-go price per audio hour for pre-recorded audio with word timestamps; cost for ~3,450 hours; word timestamps and per-word confidence; Indian English, Hindi, Bengali, Odia and Sanskrit support and code-switching; custom vocabulary or keyterm features; URL ingestion and file-length limits; and data terms (training on customer audio by default, opt-out, ownership and publication of transcripts).
Then answer directly: which services could each be tested on our 69.8-minute reference entirely within their free allowance, and does any free MONTHLY tier make meaningful corpus-scale transcription possible over time without spending money (state the hours per month and how many months the corpus would take)?`,
  },
]

phase('Research')
log('Three research angles: Deepgram in depth, independent evidence, commercial peers with free allowances')

const researched = await parallel(SWEEPS.map(sweep => () =>
  agent(sweep.prompt, { label: `research:${sweep.key}`, phase: 'Research', schema: SERVICE_SCHEMA })
    .then(result => (result ? { ...result, key: sweep.key, title: sweep.title } : null))))

const done = researched.filter(Boolean)
const failed = SWEEPS.filter((s, i) => !researched[i]).map(s => s.key)
if (failed.length) log(`Sweeps with no result: ${failed.join(', ')}`)

phase('Verify')

const dossier = done.map(r => [
  `### Sweep: ${r.key} (${r.title})`,
  ...r.services.map(s => [
    `- ${s.service}`,
    `    free allowance: ${s.free_allowance}`,
    `    price per audio hour: ${s.price_per_audio_hour}`,
    `    corpus cost: ${s.corpus_cost_3450h || '-'}`,
    `    timestamps/confidence: ${s.word_timestamps_and_confidence}`,
    `    languages: ${s.languages_relevant || '-'}`,
    `    custom vocabulary: ${s.custom_vocabulary || '-'}`,
    `    URL ingestion/limits: ${s.url_ingestion_and_limits || '-'}`,
    `    data terms: ${s.data_terms}`,
    `    accuracy: ${s.accuracy_evidence}`,
    `    fit: ${s.fit_for_this_corpus}`,
    `    sources: ${s.sources.join(' ')}`,
  ].join('\n')),
  `FINDINGS:\n${r.findings.map(f => `  * ${f}`).join('\n')}`,
].join('\n')).join('\n\n')

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    checked: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          service: { type: 'string' },
          free_allowance_verified: { type: 'string', description: 'What the vendor page says today, with the date read.' },
          price_verified: { type: 'string' },
          terms_verified: { type: 'string', description: 'Training on customer data by default, opt-out, output ownership, publication - quoted from the terms.' },
          features_verified: { type: 'string', description: 'Word timestamps, per-word confidence, custom vocabulary, relevant languages.' },
          errors_found: { type: 'string' },
          testable_free_on_reference: { type: 'string', description: 'yes / no / unclear, with the reason.' },
          bakeoff_priority: { type: 'string', description: 'high / medium / low / exclude, with the reason.' },
          sources: { type: 'array', items: { type: 'string' } },
        },
        required: ['service', 'free_allowance_verified', 'price_verified', 'terms_verified', 'features_verified', 'errors_found', 'testable_free_on_reference', 'bakeoff_priority', 'sources'],
      },
    },
    vendor_claims_presented_as_evidence: { type: 'array', items: { type: 'string' } },
    contradictions: { type: 'array', items: { type: 'string' } },
    missed: { type: 'array', items: { type: 'string' } },
  },
  required: ['checked', 'vendor_claims_presented_as_evidence', 'contradictions', 'missed'],
}

const verification = await agent(`${CONTEXT}
YOUR TASK: adversarially verify three research sweeps on commercial speech-to-text services. REFUTE rather than agree: pricing and free-credit figures go stale quickly, vendors blur marketing and measurement, and this project has a history of confident claims that turned out wrong.
For Deepgram and every other service that looks worth testing, go to the vendor's OWN current pricing page, documentation and terms (use Firecrawl for JavaScript-rendered pages; never scrape PDFs) and verify: the free allowance and whether a card is required; the price per audio hour for pre-recorded transcription with word timestamps; the terms on training with customer audio, opt-out, and ownership and publication of transcripts (quote them); and the features we need. Flag every place a vendor's own benchmark was presented as independent evidence. Say whether each service can be tested on our 69.8-minute reference entirely for free, and give each a bake-off priority. Say what the sweeps missed. Write your notes to C:\\Users\\Mukul\\code\\personal-projects\\lecture-archive\\data\\research\\commercial-asr-2026-09\\verification.md as you go.

THE THREE SWEEPS:

${dossier}`, { label: 'verify:commercial', phase: 'Verify', schema: VERDICT_SCHEMA, effort: 'high' })

return { research: done, verification, failed }
