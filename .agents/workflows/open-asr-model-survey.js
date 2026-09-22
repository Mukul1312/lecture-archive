export const meta = {
  name: 'open-asr-model-survey',
  description: 'Survey open-source ASR models beyond Whisper for the SSGGSM lecture corpus, then verify the claims against primary sources',
  phases: [
    { title: 'Research', detail: 'five independent sweeps: English ASR, Indic and Sanskrit ASR, alignment and runtimes, 2026 releases, evidence on our conditions' },
    { title: 'Verify', detail: 'adversarial check of licence, timestamps, CPU feasibility and accuracy claims for the most promising candidates' },
  ],
}

const CONTEXT = `
CONTEXT. You are researching for a volunteer (the "steward") who is transcribing an archive of about 3,766 unique lectures by Srila Gour Govinda Swami, recorded on cassette tapes between 1985 and 1996, digitised as mp3 and hosted on archive.org. The speaker is a native Odia speaker lecturing in Indian-accented English at about 94 words a minute. His English is interleaved with Sanskrit verse recitation (often chanted), Sanskrit and Bengali terms and names inside English sentences (Krsna, Mahaprabhu, bhakti, Markandeya), and occasional Bengali songs. Transcripts will be published on a read-while-listening website that highlights each word as the audio plays, so WORD-LEVEL TIMESTAMPS are required.

SO FAR ONLY WHISPER HAS BEEN TESTED, which is the gap you are filling. On a human-verified 69.8-minute reference lecture, scored with our own harness:
- faster-whisper medium (int8, CPU, beam 1): English 19.5% of words wrong or missing, Sanskrit 58.7% unrecognisable, WER 27.7%, 2.04x faster than real time on the laptop below.
- faster-whisper large-v3-turbo: English 19.1% but Sanskrit 70.1% - WORSE at Sanskrit than the small model (67.8%). The model that ranks better on public leaderboards was the wrong model here.
- faster-whisper small: English 24.9%, Sanskrit 67.8%, 4x real time.
- A glossary initial_prompt of Sanskrit terms had NO effect.
- The largest error class is DROPPED WORDS: 41% of all errors. Whisper's long-form decoding silently skips stretches of speech (it once skipped 30 s outright); re-decoding the gaps helps but does not fix it.
- Correcting a Whisper transcript means about 690 fixes per 69-minute lecture. Reducing that number is what matters most.
Leaderboards measured on clean American or European English say little about 1990 cassette audio of an Odia-accented speaker; that is why the goal is a SHORTLIST FOR A BAKE-OFF on our own reference, not a winner chosen by reading. Any model that outputs words with start times can be scored the same way.

HARD CONSTRAINTS.
- Open-source or open-weights models only. The steward has no budget for paid APIs (Sarvam, Deepgram, AssemblyAI, OpenAI API etc. are out of scope).
- The laptop: AMD Ryzen 5 5625U (6 cores / 12 threads, Zen 3), integrated AMD Radeon graphics with no NVIDIA GPU and therefore NO CUDA, 15.3 GB RAM, Windows 11, only 44 GB of free disk. A model must either run on this CPU (ONNX Runtime, CTranslate2, whisper.cpp, sherpa-onnx, OpenVINO, PyTorch CPU, possibly Vulkan/DirectML on the Radeon iGPU) or be cheap to run on a rented GPU (he has used RunPod before) - state costs honestly in that case.
- Licence must allow publishing the transcripts on a free devotional archive site. Flag non-commercial (NC) licences and anything with unclear terms.
- Word-level timestamps: say for each model whether they are native (CTC/TDT frame timings, or DTW on attention) or need a separate forced-alignment pass.

RESEARCH RULES.
- Today is 2026-09-22. Your training knowledge may be months out of date; SEARCH for current information and newer releases rather than relying on memory.
- Every factual claim needs a source URL. Prefer primary sources: official model cards, papers (arXiv), official GitHub repos, the Hugging Face Open ASR Leaderboard. Mark anything you could not verify as UNVERIFIED rather than guessing.
- Tools: WebSearch and WebFetch (load them with ToolSearch if they are not already available). You may also use the Firecrawl CLI through Bash: npx -y firecrawl-cli search "query" or npx -y firecrawl-cli scrape URL. PDFs cost about one credit per page with Firecrawl, so prefer arXiv HTML/abstract pages over PDFs.
- Do NOT install packages, download models, or run anything heavy. Do NOT modify any existing file in the repository at C:\\Users\\Mukul\\code\\personal-projects\\lecture-archive. Do NOT commit.
- DURABILITY: this project has lost work to usage limits. As you go, write your findings as markdown to C:\\Users\\Mukul\\code\\personal-projects\\lecture-archive\\data\\research\\asr-model-survey-2026-09\\<your-key>.md (create the directory; it is gitignored). Update it as you learn things, so a cut-off run still leaves your work on disk.
`

const RESEARCH_SCHEMA = {
  type: 'object',
  properties: {
    candidates: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          name: { type: 'string', description: 'Exact model or tool name and version, as published.' },
          org: { type: 'string' },
          released: { type: 'string', description: 'Release date or month.' },
          size: { type: 'string', description: 'Parameters, and download size if known.' },
          licence: { type: 'string' },
          languages: { type: 'string', description: 'Especially: English, Indian English, Sanskrit, Odia, Bengali, Hindi.' },
          word_timestamps: { type: 'string', description: 'Native, via alignment, or none - and how.' },
          long_form: { type: 'string', description: 'How it handles hour-long audio; chunking; known skipping or hallucination behaviour.' },
          runs_on_this_laptop: { type: 'string', description: 'Yes / no / how, on a Ryzen CPU with no CUDA and 15 GB RAM, with which runtime and expected speed.' },
          accuracy_evidence: { type: 'string', description: 'Published numbers with benchmark names, especially accented, Indian, noisy, long-form or archival speech.' },
          fit_for_this_corpus: { type: 'string', description: 'Why it could beat Whisper here, or why it would not.' },
          risks: { type: 'string' },
          sources: { type: 'array', items: { type: 'string' } },
        },
        required: ['name', 'licence', 'word_timestamps', 'runs_on_this_laptop', 'accuracy_evidence', 'fit_for_this_corpus', 'sources'],
      },
    },
    findings: { type: 'array', items: { type: 'string' }, description: 'The decision-relevant things you learned, each with its source.' },
    ideas: { type: 'array', items: { type: 'string' }, description: 'Pipeline ideas this research suggests, e.g. routing chanted verses to a different model.' },
    unverified: { type: 'array', items: { type: 'string' }, description: 'Claims you saw but could not confirm from a primary source.' },
    file_written: { type: 'string' },
  },
  required: ['candidates', 'findings', 'ideas', 'unverified'],
}

const SWEEPS = [
  {
    key: 'english-asr',
    title: 'open English and accented-English ASR',
    prompt: `${CONTEXT}
YOUR ANGLE: open ASR models for ENGLISH, especially accented, noisy and long-form English, that are NOT Whisper.
Cover at least these, confirming each is real and current and finding its latest version: NVIDIA Parakeet (TDT and CTC, including parakeet-tdt-0.6b-v2 and v3); NVIDIA Canary (canary-1b, canary-1b-flash, canary-1b-v2, canary-qwen-2.5b); IBM Granite Speech; Mistral Voxtral (Mini and Small); Kyutai STT; Microsoft Phi-4-multimodal; CMU OWSM / OWSM-CTC; Useful Sensors Moonshine; and, for completeness inside the Whisper family, full whisper-large-v3 (never tested here, only turbo), distil-whisper and CrisperWhisper. Add any strong model you find that is missing from this list.
For each, find: its Open ASR Leaderboard WER and RTFx; anything published on ACCENTED English (the Svarah Indian-English benchmark, L2-ARCTIC, CommonVoice accents, AfriSpeech), NOISY or FAR-FIELD speech (CHiME, AMI), and LONG-FORM audio (Earnings-21/22, TED-LIUM long-form, Rev16); whether a CPU build exists (ONNX exports on Hugging Face, sherpa-onnx, onnx-asr, NeMo on CPU) and how fast it is on a laptop CPU; how word timestamps are produced; and whether its architecture (CTC or transducer rather than an autoregressive decoder) should avoid Whisper's habit of silently dropping stretches of speech.
The single most important question: which of these could plausibly produce FEWER DROPPED WORDS and fewer fixes than faster-whisper medium on Indian-accented archival speech, while running on this laptop?`,
  },
  {
    key: 'indic-sanskrit',
    title: 'Indic, Sanskrit and Indian-English ASR',
    prompt: `${CONTEXT}
YOUR ANGLE: models and resources for the Indian side of the problem - Sanskrit verse recitation, Sanskrit/Bengali/Odia words inside English, and Indian-accented English. Sanskrit is where Whisper fails worst (58.7% of Sanskrit words unrecognisable at best).
Investigate and confirm: AI4Bharat IndicConformer (does its multilingual model really cover Sanskrit, Odia and Bengali? output script? licence? CPU inference?); AI4Bharat IndicWhisper / Vistaar; Meta MMS (which of san, ory, ben are covered, CTC with timestamps); Meta Omnilingual ASR (released late 2025: sizes, languages, Sanskrit?); any open-weights Sarvam speech models (e.g. Shuka) - only open weights count; any Sanskrit-specific ASR model on Hugging Face or in papers (search "Sanskrit ASR", "Sanskrit speech recognition", the Vaksancayah corpus, IIT Bombay and IIT Kharagpur Sanskrit speech work) and whether any handles CHANTED or metrical recitation; Indian-English ASR fine-tunes or datasets, especially NPTEL (Indian lecture speech - very close to our domain), Svarah, IndicVoices English.
Also: spoken LANGUAGE IDENTIFICATION that could find the chanted-Sanskrit and Bengali spans inside an English lecture (SpeechBrain VoxLingua107 ECAPA, MMS-LID - does either include Sanskrit?), and TRANSLITERATION from Devanagari to IAST (indic_transliteration, Aksharamukha), because the archive writes Sanskrit in IAST.
The key question: is a HYBRID pipeline realistic - an English model for the lecture, with detected verse spans routed to a Sanskrit-capable model and transliterated to IAST? What is the evidence that any open model recognises recited Sanskrit verse well enough to beat 58.7% unrecognisable?`,
  },
  {
    key: 'alignment-runtimes',
    title: 'forced alignment and CPU runtimes',
    prompt: `${CONTEXT}
YOUR ANGLE: the tooling around recognition, which the measurements showed matters as much as the model.
1. FORCED ALIGNMENT. After the steward corrects a transcript, the corrected text has no timestamps, yet the website must highlight words - so the pipeline needs forced alignment of corrected text back to the audio, and this stage has never been costed. Compare WhisperX (its VAD cut-and-merge, batched decoding and wav2vec2 alignment), ctc-forced-aligner (MMS-based, many languages, romanised input), torchaudio MMS_FA, the NeMo Forced Aligner, the Montreal Forced Aligner and any other serious option. For each: word-level accuracy published (e.g. on TIMIT/Buckeye boundaries), CPU speed on hour-long audio, memory use, whether it can align romanised Sanskrit and Bengali words inside English, licence, Windows support.
2. DROPPED SPEECH. Can alignment or VAD tooling DETECT speech that the recogniser skipped (41% of our errors are dropped words)? E.g. VAD-segmented decoding (WhisperX-style) versus Whisper's sequential long-form decoding - is there published evidence it reduces deletions?
3. CPU RUNTIMES on an AMD Ryzen with integrated Radeon and no CUDA, on Windows: sherpa-onnx, onnx-asr, whisper.cpp (does its Vulkan backend accelerate on AMD integrated graphics?), CTranslate2 (our current runtime), ONNX Runtime with DirectML, OpenVINO on AMD CPUs, ROCm on Windows for integrated Radeon. Which models each supports, measured speeds you can find for comparable laptop CPUs, and install friction on Windows.
The key question: what is the cheapest way on THIS laptop to (a) run a non-Whisper model, (b) get trustworthy word timestamps for corrected text, and (c) catch dropped speech?`,
  },
  {
    key: 'recent-2026',
    title: 'what is new in 2026',
    prompt: `${CONTEXT}
YOUR ANGLE: RECENCY. Assume every list of models in anyone's memory is out of date. Find what has been released or substantially updated between roughly January and September 2026 in open speech recognition.
Do all of this:
- Fetch the current Hugging Face Open ASR Leaderboard (the hf-audio/open_asr_leaderboard space, and its GitHub repo huggingface/open_asr_leaderboard) and record the current top 15 open models with WER, RTFx and licence. Note whether it now has multilingual, long-form or accented tracks.
- Search for 2026 releases from NVIDIA (Parakeet, Canary, Nemotron speech), Meta (Omnilingual ASR updates), Mistral (Voxtral), IBM (Granite Speech), Microsoft, Google (Gemma audio models), Alibaba/Qwen (Qwen3-ASR or Qwen omni models - open weights only), Kyutai, OpenAI (any new open-weights Whisper successor), AI4Bharat, Sarvam (open weights only), and any new Indian-language or Sanskrit ASR releases.
- For every new model, record the same facts as the other researchers: licence, size, word timestamps, whether it can run on a CPU without CUDA in 15 GB RAM, and any accented or Indian-English results.
- Also note anything newly published about Whisper's long-form deletion problem or fixes for it.
The key question: is there anything released in 2026 that changes which models belong in a bake-off?`,
  },
  {
    key: 'evidence-and-cost',
    title: 'evidence on our conditions, and GPU cost',
    prompt: `${CONTEXT}
YOUR ANGLE: evidence about how open ASR models behave under OUR conditions, and what the alternative to the laptop would cost.
1. ARCHIVAL AND DEGRADED AUDIO. Find studies or practitioner reports on ASR for oral-history archives, old cassette or tape recordings, and degraded or band-limited audio. Which model families hold up, and does audio enhancement before ASR help or hurt?
2. ACCENTED AND CODE-SWITCHED SPEECH. Find the results table of the Svarah paper (AI4Bharat, Indian-accented English) and any later evaluations of open models on Indian English; code-switching benchmarks involving Indian languages and English (e.g. MUCS). Which families did best?
3. LONG-FORM DELETIONS AND HALLUCINATIONS. Find published comparisons of Whisper against CTC/transducer models (Parakeet, Canary, wav2vec2-style) on long recordings: deletion rates, hallucinated text, skipped segments. Is there solid evidence that non-autoregressive models do not drop stretches of speech the way Whisper does?
4. RELIGIOUS AND LECTURE ARCHIVES. Has anyone transcribed a similar archive - ISKCON or Srila Prabhupada lecture recordings, other Vaishnava or Hindu discourse archives, Indian academic lecture archives such as NPTEL - and what did they use and learn?
5. RENTED-GPU COST. If a model is too slow on the laptop CPU, what would a rented GPU cost? Find current (2026) RunPod or similar community-cloud prices for common GPUs (e.g. RTX 3090, RTX 4090, A5000, L4), and published throughput (RTFx) of Parakeet, Canary and Whisper large-v3/turbo on GPU. Compute the cost to transcribe about 3,450 hours of audio with each, stating every assumption. Compare with the laptop, which needs roughly 70 days of continuous running for faster-whisper medium.
The key question: what does the evidence say about which model FAMILY suits old, accented, code-switched lecture recordings, and is renting a GPU for the whole corpus cheap enough to change the choice?`,
  },
]

phase('Research')
log('Five independent research sweeps: English ASR, Indic and Sanskrit ASR, alignment and runtimes, 2026 releases, evidence and GPU cost')

const researched = await parallel(SWEEPS.map(sweep => () =>
  agent(sweep.prompt, { label: `research:${sweep.key}`, phase: 'Research', schema: RESEARCH_SCHEMA })
    .then(result => (result ? { ...result, key: sweep.key, title: sweep.title } : null))))

const done = researched.filter(Boolean)
const failed = SWEEPS.filter((s, i) => !researched[i]).map(s => s.key)
if (failed.length) log(`Research sweeps with no result: ${failed.join(', ')}`)
log(`${done.length} of ${SWEEPS.length} sweeps returned ${done.reduce((n, r) => n + r.candidates.length, 0)} candidate entries; verifying`)

phase('Verify')

const dossier = done.map(r => [
  `### Sweep: ${r.key} (${r.title})`,
  ...r.candidates.map(c => [
    `- ${c.name}${c.org ? ` [${c.org}]` : ''}${c.released ? `, ${c.released}` : ''}${c.size ? `, ${c.size}` : ''}`,
    `    licence: ${c.licence}`,
    `    languages: ${c.languages || '-'}`,
    `    word timestamps: ${c.word_timestamps}`,
    `    long-form: ${c.long_form || '-'}`,
    `    on this laptop: ${c.runs_on_this_laptop}`,
    `    accuracy: ${c.accuracy_evidence}`,
    `    fit: ${c.fit_for_this_corpus}`,
    `    risks: ${c.risks || '-'}`,
    `    sources: ${c.sources.join(' ')}`,
  ].join('\n')),
  `FINDINGS:\n${r.findings.map(f => `  * ${f}`).join('\n')}`,
  `IDEAS:\n${r.ideas.map(f => `  * ${f}`).join('\n')}`,
].join('\n')).join('\n\n')

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    checked: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          candidate: { type: 'string' },
          licence_ok_for_publishing: { type: 'string', description: 'Verified licence and whether it permits publishing transcripts on a free archive site.' },
          word_timestamps_verified: { type: 'string' },
          runs_on_this_laptop_verified: { type: 'string', description: 'Confirmed CPU path on Windows without CUDA, with the actual artefact (e.g. the ONNX export repo) and realistic speed, or why not.' },
          accuracy_claims_verified: { type: 'string', description: 'Which quoted numbers you confirmed at source, which were wrong, and what they actually measure.' },
          errors_found: { type: 'string', description: 'Anything the researchers got wrong.' },
          bakeoff_priority: { type: 'string', description: 'high / medium / low / exclude, with the reason.' },
          sources: { type: 'array', items: { type: 'string' } },
        },
        required: ['candidate', 'licence_ok_for_publishing', 'word_timestamps_verified', 'runs_on_this_laptop_verified', 'accuracy_claims_verified', 'errors_found', 'bakeoff_priority', 'sources'],
      },
    },
    contradictions_between_sweeps: { type: 'array', items: { type: 'string' } },
    overclaims: { type: 'array', items: { type: 'string' }, description: 'Conclusions or recommendations that go beyond their evidence.' },
    missed: { type: 'array', items: { type: 'string' }, description: 'Models, tools or questions all five sweeps missed.' },
  },
  required: ['checked', 'contradictions_between_sweeps', 'overclaims', 'missed'],
}

const verification = await agent(`${CONTEXT}
YOUR TASK: adversarially verify five research sweeps that other agents just produced. REFUTE rather than agree. This project has a history of confident claims that were wrong, and the steward will spend disk space, days of machine time and his own correction time on whatever reaches the shortlist.

1. From everything below, pick the 8-10 candidates (models or tools) that look most promising for a bake-off on this corpus and this laptop, plus any candidate the sweeps DISAGREE about.
2. For each one, go to the PRIMARY source yourself (model card, licence file, paper, official repo) and verify: the licence and whether it allows publishing transcripts on a free archive site; whether word timestamps really exist and how; whether a CPU path on Windows without CUDA really exists (name the actual artefact, e.g. a specific ONNX export repository, and check that it is maintained), and how fast it would plausibly run on a 6-core Ryzen laptop; and whether the quoted accuracy numbers are real and what exactly they measure. Leaderboard numbers on clean read speech are weak evidence for this corpus - say so where it applies.
3. Report errors, contradictions between sweeps, and recommendations that outrun their evidence.
4. Say what all five sweeps missed.
Assign each candidate a bake-off priority: high, medium, low, or exclude, with the reason. Write your findings to C:\\Users\\Mukul\\code\\personal-projects\\lecture-archive\\data\\research\\asr-model-survey-2026-09\\verification.md as you go.

THE FIVE SWEEPS:

${dossier}`, { label: 'verify:shortlist', phase: 'Verify', schema: VERDICT_SCHEMA, effort: 'high' })

return { research: done, verification, failed }
