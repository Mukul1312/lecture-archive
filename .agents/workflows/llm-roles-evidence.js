export const meta = {
  name: 'llm-roles-evidence',
  description: 'Evidence for what open language models can do for the SSGGSM and Odia projects when GPU rental and licences are not constraints',
  phases: [
    { title: 'Research', detail: 'LLM error correction of ASR output; per-model Indic and Sanskrit capability; practical run plan on a rented GPU' },
    { title: 'Verify', detail: 'adversarial check of the evidence and the plan' },
  ],
}

const CONTEXT = `
CONTEXT. A volunteer (the "steward") is transcribing about 3,766 English lectures by Srila Gour Govinda Swami (1985-1996 cassettes; an Odia speaker, Indian-accented English, with chanted Sanskrit verse, Sanskrit/Bengali names and phrases inside English sentences, and Bengali songs). Transcripts are published on a read-while-listening website with Sanskrit written in IAST. A second project translates Odia lectures into English.

MEASURED SO FAR on a human-verified 69.8-minute reference, best Whisper setup (medium, no-speech skip rule off): English 19.3% of words wrong or missing, Sanskrit 55.8% unrecognisable, WER 27.2%. About 690 places to fix per lecture. Dropped words are the largest error class (~40% of errors). Code-switching concentrates errors: cues containing Sanskrit hold 35% of the words but 54% of the errors, and English words directly next to a Sanskrit word are wrong 49.8% of the time against 14.7% far from any. A dictionary/glossary post-correction pass gained only ~2 points on Sanskrit and produced confident wrong words (baba -> bhava). A second benchmark is being prepared: Prabhupadavani (94 h of Srila Prabhupada's English lectures with romanised Sanskrit and Bengali; Bengali and Sanskrit NOT tagged separately in the released text).

THE STEWARD'S POSITION. He can rent GPUs (RunPod, roughly $0.2-2 an hour depending on the card) and can obtain licences or permissions, so model SIZE and LICENCE are NOT reasons to exclude a model. Judge models on CAPABILITY for concrete jobs, and state costs rather than using them as vetoes.

THE CANDIDATE JOBS for a language model (text in, text out):
1. Post-ASR error correction of the English transcript, including Sanskrit names inside English (generative error correction), from the single best transcript or from several systems' outputs (e.g. Whisper plus another recogniser), which is the only way a text model could restore DROPPED words.
2. Verse identification: from a garbled romanised hypothesis of a chanted verse, name the verse (e.g. Bhagavad-gita 18.66) so the canonical IAST text can be retrieved and aligned.
3. Language tagging: mark each word of a romanised transcript as English, Sanskrit or Bengali (needed to score Bengali separately, and to route spans).
4. Formatting: punctuation, sentences and paragraphs for readability.
5. Odia to English translation for the Odia seva.

THE MODELS THE STEWARD FOUND (verified facts already known): Sarvam-1 (2.5B base model, not instruction-tuned, no Sanskrit; Odia/Bengali yes); Sarvam-30B (32B mixture-of-experts, 2.4B active, reasoning model, Apache-2.0, claims 22 Indian languages incl. Sanskrit, one independent Sanskrit MCQ score of 33.5%; a larger Sarvam-105B also exists); Param-1-7B-MoE (BharatGen base model, trained on Sanskrit/Odia/Bengali, no published evaluations; related Param2-17B scored Sanskrit 27.8% and Odia 34.0% on the AGI Quest IndicParam MCQ); Param-1-2.9B-Instruct (English and Hindi only); the Qwen3 family (0.6B to 235B, Apache-2.0, 119 languages incl. Odia and Bengali but NOT Sanskrit); dhee-nxtgen-qwen3-sanskrit-v2 (a Qwen3-1.7B Sanskrit chat fine-tune, no data or evaluation published); encoders IndicBERT-v3 (270M/1B/4B), MuRIL, XLMIndic-uniscript (11M, trained on ISO-15919 romanised Indo-Aryan text, which is close to IAST); Paramanu small monolingual models (Sanskrit 139M, Odia 87M).

RESEARCH RULES. Today is 2026-09-22; search for current information rather than relying on memory. Every claim needs a source URL; separate authors' claims from independent results; mark anything unconfirmed as UNVERIFIED. Tools: WebSearch/WebFetch, the Exa tools (load via ToolSearch: mcp__plugin_exa_exa__web_search_exa, mcp__plugin_exa_exa__web_fetch_exa), and the Firecrawl CLI via Bash (npx -y firecrawl-cli search "..." / scrape URL). Firecrawl credits are shared and limited: at most 20 per agent, and NEVER scrape a PDF with Firecrawl - use arXiv abs/html pages. Do NOT download models, install anything, or modify files in C:\\Users\\Mukul\\code\\personal-projects\\lecture-archive except your notes file. Do NOT commit. Write notes as you go to C:\\Users\\Mukul\\code\\personal-projects\\lecture-archive\\data\\research\\llm-roles-2026-09\\<your-key>.md (create the directory).
`

const SCHEMA = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          claim: { type: 'string' },
          evidence: { type: 'string', description: 'Numbers, conditions (language, accent, audio type, n), and whether independent or the authors own.' },
          implication: { type: 'string', description: 'What this means for the jobs above.' },
          sources: { type: 'array', items: { type: 'string' } },
        },
        required: ['claim', 'evidence', 'implication', 'sources'],
      },
    },
    model_assessments: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          model: { type: 'string' },
          best_job: { type: 'string', description: 'Which of jobs 1-5 it could plausibly do, or none.' },
          evidence_for: { type: 'string' },
          evidence_against: { type: 'string' },
          cost_to_test: { type: 'string', description: 'GPU needed, rough hourly price, time for the 69.8-min reference.' },
          test_design: { type: 'string', description: 'How to measure it on our references so both fixes and newly introduced errors are counted.' },
        },
        required: ['model', 'best_job', 'evidence_for', 'evidence_against', 'test_design'],
      },
    },
    unverified: { type: 'array', items: { type: 'string' } },
  },
  required: ['findings', 'model_assessments', 'unverified'],
}

const SWEEPS = [
  {
    key: 'asr-error-correction',
    prompt: `YOUR ANGLE: does LLM post-correction of speech-recognition output actually work, and when does it make things worse? Cover generative error correction (GER) research: HyPoradise and its N-best benchmark, GenSEC, "Whispering LLaMA", LLM-based multi-system fusion (ROVER-style with an LLM), confidence-aware or constrained correction, and any work on ACCENTED, CODE-SWITCHED or INDIAN-language ASR correction (e.g. Hindi-English). Report measured gains AND failure modes: over-correction, hallucinated fluent text, rewriting correct words, loss of verbatim fidelity (the archive must record what the speaker actually said, including his idiosyncratic English), and whether gains hold for strong or only weak base recognisers. Specifically: can a text-only model restore dropped words from one transcript (it cannot hear the audio), or only with multiple hypotheses? What model sizes were needed? Also assess jobs 2 (verse identification) and 4 (formatting) from any evidence you find. For model_assessments, cover the general approach with the strongest open LLMs you find evidence for, not only the steward's list.`,
  },
  {
    key: 'indic-capability',
    prompt: `YOUR ANGLE: what do the steward's models (and the strongest comparable open models) actually know about SANSKRIT, BENGALI, ODIA and IAST? Find independent evaluations: the AGI Quest IndicParam benchmark tables (Sanskrit and Odia per model), IndicGenBench, MILU, Sanskrit-specific LLM benchmarks (search "Sanskrit LLM benchmark", "Sanskrit shloka identification LLM", verse memorisation of Bhagavad-gita or Bhagavatam), transliteration benchmarks (Devanagari to IAST), and Odia-to-English translation evaluations that include LLMs as well as IndicTrans2. Give each of the steward's models a fair assessment on capability alone (size and licence are not constraints): Sarvam-30B and Sarvam-105B, Sarvam-1, Param-1-7B (and Param2-17B if relevant), Qwen3 at several sizes (does it handle Sanskrit despite not listing it?), dhee-nxtgen-qwen3-sanskrit-v2, and the encoders (IndicBERT-v3, MuRIL, XLMIndic-uniscript) for job 3, language tagging - note that XLMIndic was trained on ISO-15919 romanised text, close to our IAST transcripts. Also name any strong open model NOT in the list that the evidence says is better at Sanskrit or Odia (e.g. Gemma 3, Llama, Aya, IndicTrans-style models).`,
  },
  {
    key: 'run-plan',
    prompt: `YOUR ANGLE: a practical, costed plan to MEASURE these models on the steward's references using a rented GPU. For each candidate model (Sarvam-30B, Sarvam-105B, Param-1-7B, Qwen3-32B and Qwen3-235B-A22B, dhee-nxtgen-qwen3-sanskrit-v2, plus the encoder route for language tagging), state: the GPU and VRAM needed at a sensible precision, the serving stack (vLLM, SGLang, llama.cpp, transformers) and whether it supports the model's architecture today (Sarvam-30B uses bailingmoe2 / sarvam-moe; Param-1 uses custom code), current RunPod prices for suitable cards (community and secure cloud), and the estimated time and cost to process the 69.8-minute reference (about 6,700 words of transcript, ~690 correction sites) and, if promising, the full ~3,450-hour corpus. Then design the evaluation so it is honest: correction must be scored with the same scorer against the human-verified reference, counting words fixed AND correct words broken; use the no-audio constraint explicitly (a text model cannot know what was said where the recogniser dropped words); keep a held-out part so prompts are not tuned on the test; and include a do-nothing baseline. Also design job 3 (language tagging) for Prabhupadavani, where Bengali and Sanskrit are untagged: how to get labels cheaply (a small hand-labelled sample, a Bengali lexicon, script clues) and how to score the tagger.`,
  },
]

phase('Research')
const results = await parallel(SWEEPS.map(s => () =>
  agent(`${CONTEXT}\n${s.prompt}`, { label: `research:${s.key}`, phase: 'Research', schema: SCHEMA })
    .then(r => (r ? { ...r, key: s.key } : null))))
const done = results.filter(Boolean)
const failed = SWEEPS.filter((s, i) => !results[i]).map(s => s.key)
if (failed.length) log(`Sweeps with no result: ${failed.join(', ')}`)

phase('Verify')
const dossier = done.map(r => [
  `### ${r.key}`,
  'FINDINGS:', ...r.findings.map(f => `- ${f.claim}\n    evidence: ${f.evidence}\n    implication: ${f.implication}\n    sources: ${f.sources.join(' ')}`),
  'MODELS:', ...r.model_assessments.map(m => `- ${m.model}: job ${m.best_job}\n    for: ${m.evidence_for}\n    against: ${m.evidence_against}\n    cost: ${m.cost_to_test || '-'}\n    test: ${m.test_design}`),
].join('\n')).join('\n\n')

const VERDICT = {
  type: 'object',
  properties: {
    corrections: { type: 'array', items: { type: 'string' }, description: 'Claims that are wrong, stale, or misattributed, with the correct version and source.' },
    overclaims: { type: 'array', items: { type: 'string' } },
    per_model_verdict: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          model: { type: 'string' },
          verdict: { type: 'string', description: 'worth measuring / measure only as a control / not worth measuring - with the capability reason, never size or licence alone.' },
          first_test: { type: 'string' },
        },
        required: ['model', 'verdict', 'first_test'],
      },
    },
    missed: { type: 'array', items: { type: 'string' } },
  },
  required: ['corrections', 'overclaims', 'per_model_verdict', 'missed'],
}

const verification = await agent(`${CONTEXT}
YOUR TASK: adversarially verify three research sweeps about using language models for these jobs. Refute rather than agree. Check the key numbers at their sources, especially any claimed gain from LLM post-correction (what base recogniser, what language, what audio) and any claimed Sanskrit or Odia ability. Watch for size or licence being used as a reason to dismiss a model - the steward has said neither is a constraint, so every verdict must rest on capability. Give each model a verdict and a concrete first test. Say what the sweeps missed. Write notes to C:\\Users\\Mukul\\code\\personal-projects\\lecture-archive\\data\\research\\llm-roles-2026-09\\verification.md as you go.

${dossier}`, { label: 'verify:llm-roles', phase: 'Verify', schema: VERDICT, effort: 'high' })

return { research: done, verification, failed }
