export const meta = {
  name: 'indic-links-survey',
  description: 'Read 34 links the steward found (Indian translation, LLMs, Sanskrit models, speech) and judge each against his projects, then verify',
  phases: [
    { title: 'Read', detail: 'five themed readers scrape and extract facts from their links' },
    { title: 'Verify', detail: 'check licences, sizes, languages and relevance claims at source' },
  ],
}

const CONTEXT = `
CONTEXT. The steward (Mukul, a software engineer learning ML) runs three volunteer projects and found these links while researching. Your job is to read each link at its source and say factually what it is and whether it helps any of these projects:

1. SSGGSM LECTURE TRANSCRIPTION (the main project). About 3,766 English lectures (1985-1996 cassettes, archive.org) by Srila Gour Govinda Swami, an Odia speaker, with chanted Sanskrit verse, Sanskrit/Bengali names inside English sentences, and Bengali songs. Transcripts go on a read-while-listening site with word highlighting; Sanskrit is written in IAST (e.g. śrī-mārkaṇḍeya uvāca). Measured on a human-verified reference: Whisper medium leaves English 19.5% wrong, Sanskrit 58.7% unrecognisable; dropped words are the largest error class. Known ideas in play: route chanted verse spans to a Sanskrit-capable recogniser, or better, RETRIEVE the canonical verse text (each lecture's catalogue entry names its verse, e.g. SB 4.20.28-29) and force-align it; post-ASR correction of Sanskrit names (a glossary pass only gained ~2 points and produced confident wrong words); Devanagari-to-IAST transliteration. Already known and shortlisted elsewhere, so only report what is NEW about them: Su-srota Sanskrit ASR (prathoshap/sushrota-sanskrit-asr; licence unclear), Indic-Transcribe core/flex (bodhan-ai; bespoke licence, no Sanskrit or English numbers found so far), Qwen3-ASR.
2. ODIA TRANSCRIPTION AND TRANSLATION SEVA. Volunteer transcription of Odia-language lectures, with English translation now in scope. Relevant: Odia ASR, Odia-to-English machine translation, and anything that helps a human translator.
3. NARRATOR-VOICE. A separate repository for narrating Odia diary entries (and future English/Hindi narration) with text-to-speech in a DIFFERENT voice from Gour Govinda Swami's (not a clone of him). The team chose to train its own Odia emotional TTS; commercial TTS (Cartesia) showed no emotion control in Odia. Relevant: open Odia TTS, emotion/style control, licences allowing publication.

HARDWARE AND MONEY. Laptop: AMD Ryzen 5 5625U (6 cores), no NVIDIA GPU and so no CUDA, 15.3 GB RAM, Windows 11, about 44 GB free disk. No budget for paid APIs; a rented GPU (RunPod, roughly $0.16-0.34 an hour) is possible for occasional jobs. For every model, say whether it can run on this laptop (GGUF/llama.cpp, ONNX, CTranslate2, or plain CPU PyTorch within 15 GB RAM) and roughly how fast, or whether it needs a GPU.

HOW TO READ.
- Today is 2026-09-22. Read each link at its source; do not describe it from memory. If a page is gated, unreachable or not what its URL suggests, say exactly that.
- Tools: the Firecrawl CLI through Bash (npx -y firecrawl-cli scrape "URL" --only-main-content, or search), the Exa tools (load them with ToolSearch: mcp__plugin_exa_exa__web_fetch_exa and mcp__plugin_exa_exa__web_search_exa), and WebFetch. Firecrawl credits are shared and limited (about 690 left): spend at most 25 yourself, and NEVER send a PDF to Firecrawl (it bills per page) - for an arXiv PDF link, read its abs or html page instead. Prefer Exa or WebFetch where they work.
- For Hugging Face models also try the API, which is free and exact: https://huggingface.co/api/models/<org>/<name> gives licence, tags, gating, downloads and last-modified date (e.g. curl -s through Bash).
- Every fact needs its source URL. Mark anything you could not confirm as UNVERIFIED. Separate the authors' own claims from independent evidence.
- Do NOT download model weights, install anything, or modify files in the repository at C:\\Users\\Mukul\\code\\personal-projects\\lecture-archive except your own notes file. Do NOT commit.
- DURABILITY: write your findings as you go to C:\\Users\\Mukul\\code\\personal-projects\\lecture-archive\\data\\research\\indic-links-2026-09\\<your-key>.md (create the directory; it is gitignored).
`

const LINK_SCHEMA = {
  type: 'object',
  properties: {
    links: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          url: { type: 'string', description: 'The link exactly as given.' },
          title: { type: 'string', description: 'What it actually is: name, organisation, version.' },
          kind: { type: 'string', description: 'One of: machine translation, LLM, encoder/embedding model, tokenizer, speech recognition, text-to-speech, dataset, catalogue, paper, commit, profile/other.' },
          date: { type: 'string' },
          licence: { type: 'string', description: 'Exact licence and any gating or usage restrictions; whether outputs may be published.' },
          size: { type: 'string' },
          languages: { type: 'string', description: 'Explicitly state Sanskrit, Odia, Bengali, Hindi and English support, yes or no.' },
          runs_on_laptop: { type: 'string' },
          key_facts: { type: 'string', description: "The substance: what it does, headline results with benchmark names, marked as the authors' claims or independent." },
          relevance: { type: 'string', description: 'Which of the three projects it could help, exactly how, or why it does not. Be concrete and sceptical.' },
          verdict: { type: 'string', description: 'One of: try soon, keep in mind, not relevant - with a one-line reason.' },
          sources: { type: 'array', items: { type: 'string' } },
        },
        required: ['url', 'title', 'kind', 'licence', 'languages', 'runs_on_laptop', 'key_facts', 'relevance', 'verdict', 'sources'],
      },
    },
    cross_cutting: { type: 'array', items: { type: 'string' }, description: 'Observations that connect several links.' },
    notes_file: { type: 'string' },
  },
  required: ['links', 'cross_cutting'],
}

const BATCHES = [
  {
    key: 'translation-nlp',
    title: 'translation and Indic NLP foundations',
    links: [
      'https://github.com/AI4Bharat/IndicTrans2?tab=readme-ov-file',
      'https://huggingface.co/ai4bharat/IndicBERT-v3-1B/blob/main/README.md',
      'https://ai4bharat.iitm.ac.in//indic-bert/',
      'https://huggingface.co/ibraheemmoosa/xlmindic-base-uniscript',
      'https://github.com/AI4Bharat/indicnlp_catalog',
      'https://huggingface.co/LingoIITGN/Ansh-256k',
      'https://ar5iv.labs.arxiv.org/html/2201.11391',
      'https://www.alphaxiv.org/abs/2103.10730',
    ],
    focus: 'For IndicTrans2, establish exactly which directions exist (Odia to English? Sanskrit? Bengali?), the model sizes including any distilled ones, CPU inference options (CTranslate2 exports?), licence of code and weights, and published quality for Odia-English. For the catalogue, pull out the entries relevant to Sanskrit, Odia, speech, transliteration and IAST, not the whole list.',
  },
  {
    key: 'indian-llms',
    title: 'Indian large language models',
    links: [
      'https://huggingface.co/sarvamai/sarvam-1',
      'https://huggingface.co/sarvamai/sarvam-30b-gguf/blob/main/README.md',
      'https://huggingface.co/abhinand/sarvam-30b-bf16',
      'https://huggingface.co/bharatgenai/Param-1-7B',
      'https://huggingface.co/bharatgenai/Param-1-2.9B-Instruct',
      'https://huggingface.co/bharatgenai/Param-1-2.9B-Instruct/commit/a8437f02110718107987d30ef975ca5ae326673a',
      'https://huggingface.co/bharatgenai/Param-1-2.9B-Instruct/commit/7bfec15ee177b038e5309c672af819b8c21dc156',
      'https://aikosh.indiaai.gov.in/home/models/details/bharatgen_param_1_indic_scale_bilingual_foundation_model.html',
      'https://model.aibase.com/models/details/1959857280912723968',
    ],
    focus: 'For each LLM: languages (does it know Sanskrit, Odia, Bengali?), licence and whether it permits this use, the quantised size and whether it fits 15 GB RAM on CPU (sarvam-30b GGUF quantisations especially), and any evidence it could help with Sanskrit/IAST text: correcting ASR output, identifying a verse from a garbled hypothesis, transliteration, or Odia-English translation. For the two commit links, report exactly what each commit changed and why it might matter (licence? weights? chat template?). Identify what the aibase page actually is.',
  },
  {
    key: 'qwen3-sanskrit',
    title: 'Qwen3 and the Sanskrit fine-tune',
    links: [
      'https://github.com/QwenLM/Qwen3',
      'https://arxiv.org/abs/2505.09388',
      'https://arxiv.org/abs/2505.09388v1',
      'https://qwen.ai/blog?id=qwen3',
      'https://huggingface.co/docs/transformers/main/model_doc/qwen3',
      'https://huggingface.co/dheeyantra/dhee-nxtgen-qwen3-sanskrit-v2',
    ],
    focus: 'Summarise the Qwen3 family briefly (sizes, licence, the smallest models that run on a laptop CPU as GGUF, multilingual claims including Indian languages). Spend most of your effort on dhee-nxtgen-qwen3-sanskrit-v2: what it was trained on, what it can do in Sanskrit (generation, translation, grammar, verse knowledge?), which script it expects (Devanagari or IAST), licence, size, any evaluation, and whether it could realistically help the transcription project - for example restoring a garbled romanised verse to its canonical text, identifying which verse a rough hypothesis is, or converting between scripts. Be sceptical: an LLM that confidently rewrites a verse wrongly is worse than no correction.',
  },
  {
    key: 'speech',
    title: 'speech recognition and speech synthesis',
    links: [
      'https://huggingface.co/ai4bharat/indic-parler-tts',
      'https://huggingface.co/bodhan-ai/indic-speak',
      'https://huggingface.co/prathoshap/sushrota-sanskrit-asr',
      'https://huggingface.co/diabolic6045/GitaWhisper-tiny',
      'https://huggingface.co/bodhan-ai/indic-transcribe-core',
      'https://huggingface.co/bodhan-ai/indic-transcribe-flex',
    ],
    focus: 'For the TTS models (indic-parler-tts, indic-speak): Odia support, voices, emotion or style control through descriptions, licence and whether generated audio may be published, CPU feasibility, and how they compare with the narrator-voice plan to train its own Odia emotional TTS. For the ASR models: GitaWhisper-tiny is new to us - what it was trained on (Gita recitation?), output script, licence, evaluation, and whether it could recognise or IDENTIFY Bhagavad-gita verses in the lectures. For Su-srota and Indic-Transcribe, report only what is new or changed since this summary: Su-srota licence unclear, chant CER about 6%; Indic-Transcribe bespoke Indic Open Model License, no Sanskrit or English numbers, native-script output only, refuses audio over 45 s.',
  },
  {
    key: 'papers-and-misc',
    title: 'papers and miscellaneous links',
    links: [
      'https://zenodo.org/records/17341822',
      'https://arxiv.org/html/2605.29637',
      'https://github.com/Nitinmall-1390/Nitinmall',
      'https://arxiv.org/pdf/2401.18034v2',
    ],
    focus: 'Identify each precisely. For the arXiv PDF link, read https://arxiv.org/abs/2401.18034v2 (or its html version) instead of the PDF. For the GitHub profile, say what projects it holds that relate to Indian languages or Sanskrit, and whether anything there is usable or it is just a personal page. For the Zenodo record: what dataset or artefact, its licence and size, and whether it contains Sanskrit, Odia or speech data relevant to the projects.',
  },
]

phase('Read')
log('Five themed readers on 34 links')

const read = await parallel(BATCHES.map(b => () =>
  agent(`${CONTEXT}
YOUR BATCH: ${b.title}. Read every one of these links:
${b.links.map(l => `- ${l}`).join('\n')}

${b.focus}

Return one entry per link, in the order given, even when a link turns out to be a duplicate or unreachable.`,
    { label: `read:${b.key}`, phase: 'Read', schema: LINK_SCHEMA })
    .then(r => (r ? { ...r, key: b.key, title: b.title } : null))))

const done = read.filter(Boolean)
const failed = BATCHES.filter((b, i) => !read[i]).map(b => b.key)
if (failed.length) log(`Batches with no result: ${failed.join(', ')}`)

phase('Verify')

const dossier = done.map(r => [
  `### Batch: ${r.key}`,
  ...r.links.map(l => [
    `- ${l.url}`,
    `    is: ${l.title} [${l.kind}]${l.date ? `, ${l.date}` : ''}${l.size ? `, ${l.size}` : ''}`,
    `    licence: ${l.licence}`,
    `    languages: ${l.languages}`,
    `    laptop: ${l.runs_on_laptop}`,
    `    facts: ${l.key_facts}`,
    `    relevance: ${l.relevance}`,
    `    verdict: ${l.verdict}`,
    `    sources: ${l.sources.join(' ')}`,
  ].join('\n')),
  `CROSS-CUTTING:\n${r.cross_cutting.map(c => `  * ${c}`).join('\n')}`,
].join('\n')).join('\n\n')

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    checked: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          url: { type: 'string' },
          licence_verified: { type: 'string' },
          languages_verified: { type: 'string', description: 'Especially Sanskrit and Odia claims.' },
          laptop_claim_verified: { type: 'string' },
          errors_found: { type: 'string' },
          final_verdict: { type: 'string', description: 'try soon / keep in mind / not relevant, with the reason.' },
        },
        required: ['url', 'licence_verified', 'languages_verified', 'laptop_claim_verified', 'errors_found', 'final_verdict'],
      },
    },
    overclaims: { type: 'array', items: { type: 'string' } },
    best_three_for_the_steward: { type: 'array', items: { type: 'string' }, description: 'The three links most worth his time, each with the concrete next step.' },
  },
  required: ['checked', 'overclaims', 'best_three_for_the_steward'],
}

const verification = await agent(`${CONTEXT}
YOUR TASK: verify what five readers reported about the steward's 34 links. Refute rather than agree. Focus on the links any reader marked "try soon" or "keep in mind", and on every claim that a model supports Sanskrit or Odia, runs on this laptop, or permits publication: check those at the source yourself (the Hugging Face API at https://huggingface.co/api/models/<org>/<name> is exact for licence, gating and tags). Also check any link marked "not relevant" whose dismissal looks hasty. Report errors and overclaims, give each checked link a final verdict, and name the three links most worth the steward's time with a concrete next step for each. Write notes to C:\\Users\\Mukul\\code\\personal-projects\\lecture-archive\\data\\research\\indic-links-2026-09\\verification.md as you go.

THE READERS' REPORTS:

${dossier}`, { label: 'verify:links', phase: 'Verify', schema: VERDICT_SCHEMA, effort: 'high' })

return { read: done, verification, failed }
