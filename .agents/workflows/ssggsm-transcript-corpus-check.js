export const meta = {
  name: 'ssggsm-transcript-corpus-check',
  description: 'Check whether the 833 archive.org SSGGSM transcripts are verbatim and pairable with audio files',
  phases: [
    { title: 'Inventory', detail: 'list transcript and audio filenames from archive.org metadata' },
    { title: 'Sample', detail: 'fetch individual transcripts and judge verbatim vs edited' },
    { title: 'Pair', detail: 'match transcript names to audio; measure WER where a local ASR run exists' },
    { title: 'Synthesize', detail: 'gold-set and reuse recommendation' },
  ],
}

const SCRATCH = 'C:/Users/Mukul/AppData/Local/Temp/claude/c--Users-Mukul-code-personal-projects-lecture-archive/7043a597-7e85-48b9-ba1e-a11f0eeb11b9/scratchpad/transcript-check'

const RULES = `HARD RULES.
1. An rclone upload is running on this machine: never kill, inspect or invoke rclone, and do not run heavy network or disk work. Small curl requests to archive.org are fine.
2. Never modify anything under C:/Users/Mukul/code/personal-projects — read-only. Write all temp files under ${SCRATCH} (create it with mkdir -p).
3. Use Bash with curl for archive.org and python for parsing. No pip installs; use only the standard library plus what is already installed.
4. Report honestly. Say UNVERIFIED rather than guessing. Small samples mean uncertain conclusions — say so.
Background: archive.org item "ssggsm-transcripts" holds 833 original files (710 .rtf, 82 .doc, 22 .docx, 3 .pdf) of transcripts of English lectures by Srila Gour Govinda Swami Maharaja. Audio for the same lectures lives in archive.org items SSGGSM1985, SSGGSM1986, SSGGSM1989, SSGGSM1990, SSGGSM1991, SSGGSM1992, SSGGSM1993, SSGGSM1994, SSGGSM1995, SSGGSM1996 (5,936 mp3 files). Audio filenames look like "21.8.85 SB6.2.36-37 Zurich.mp3" (D.M.YY, scripture reference, place). Transcript filenames look like "19000000 (SB 9_15_24) A vaishnava has no pride or envy.rtf" (YYYYMMDD prefix where 19000000 means the date is unknown).
Purpose: decide whether these existing transcripts can serve as a verbatim reference set for measuring the word error rate of local Whisper transcription, and whether they can be paired to their audio automatically.`

const INVENTORY_SCHEMA = {
  type: 'object',
  properties: {
    total_files: { type: 'number' },
    by_extension: { type: 'object', additionalProperties: true },
    dated_count: { type: 'number', description: 'files whose 8-digit prefix is a real date, not 19000000' },
    undated_count: { type: 'number' },
    year_histogram: { type: 'object', additionalProperties: true, description: 'year from prefix -> count' },
    with_scripture_ref: { type: 'number' },
    with_place_name: { type: 'number' },
    duplicate_basenames: { type: 'number', description: 'same title under more than one extension' },
    sample_for_reading: { type: 'array', items: { type: 'string' }, description: 'exactly 8 exact filenames spread across extensions and dated/undated' },
    zurich_candidates: { type: 'array', items: { type: 'string' }, description: 'filenames plausibly matching the 1985-08-21 Zurich SB 6.2.36-37 lecture' },
    index_path: { type: 'string', description: 'path of the JSON file you wrote with every filename and its parsed fields' },
    notes: { type: 'string' },
  },
  required: ['total_files', 'by_extension', 'dated_count', 'undated_count', 'sample_for_reading', 'index_path', 'notes'],
}

const AUDIO_SCHEMA = {
  type: 'object',
  properties: {
    total_audio_files: { type: 'number' },
    per_item: { type: 'object', additionalProperties: true },
    parsed_date_count: { type: 'number' },
    parsed_verse_count: { type: 'number' },
    parsed_place_count: { type: 'number' },
    multi_part_count: { type: 'number', description: 'files that look like sides or parts of one lecture' },
    duplicate_md5_count: { type: 'number' },
    total_duration_hours: { type: 'number' },
    index_path: { type: 'string' },
    notes: { type: 'string' },
  },
  required: ['total_audio_files', 'per_item', 'index_path', 'notes'],
}

const SAMPLE_SCHEMA = {
  type: 'object',
  properties: {
    filename: { type: 'string' },
    parsed: { type: 'boolean', description: 'whether you could extract plain text with available tools' },
    tool_used: { type: 'string' },
    word_count: { type: 'number' },
    verdict: { type: 'string', enum: ['verbatim', 'lightly-edited', 'heavily-edited', 'not-a-transcript', 'unparsable'] },
    confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
    evidence: { type: 'array', items: { type: 'string' }, description: 'short quotes or counts backing the verdict: filler words, false starts, repetitions, audience questions, speaker labels, editorial headings, footnotes, diacritics' },
    signals: { type: 'object', additionalProperties: true, description: 'counts: fillers, false_starts, question_markers, speaker_labels, headings, bracketed_editorial, sanskrit_diacritics' },
    covers_whole_lecture: { type: 'string', enum: ['yes', 'partial', 'unknown'] },
    pairing_fields: { type: 'object', additionalProperties: true, description: 'date, scripture reference and place you could parse from the name or the text' },
    notes: { type: 'string' },
  },
  required: ['filename', 'parsed', 'verdict', 'confidence', 'evidence', 'notes'],
}

const PAIR_SCHEMA = {
  type: 'object',
  properties: {
    method: { type: 'string' },
    high_confidence_pairs: { type: 'number' },
    ambiguous_pairs: { type: 'number' },
    unpairable_transcripts: { type: 'number' },
    example_pairs: { type: 'array', items: { type: 'string' } },
    limiting_factor: { type: 'string' },
    notes: { type: 'string' },
  },
  required: ['high_confidence_pairs', 'unpairable_transcripts', 'limiting_factor', 'notes'],
}

const WER_SCHEMA = {
  type: 'object',
  properties: {
    attempted: { type: 'boolean' },
    transcript_used: { type: 'string' },
    wer_percent: { type: 'number' },
    normalization: { type: 'string' },
    asr_word_count: { type: 'number' },
    reference_word_count: { type: 'number' },
    interpretation: { type: 'string', description: 'what the number does and does not prove' },
    notes: { type: 'string' },
  },
  required: ['attempted', 'notes'],
}

const SYNTH_SCHEMA = {
  type: 'object',
  properties: {
    verbatim_share_estimate: { type: 'string' },
    usable_as_reference: { type: 'string', enum: ['yes', 'partly', 'no', 'unknown'] },
    recommended_reference_set: { type: 'string' },
    pairing_recommendation: { type: 'string' },
    conversion_tooling_needed: { type: 'string' },
    risks: { type: 'array', items: { type: 'string' } },
    open_questions: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string' },
  },
  required: ['usable_as_reference', 'recommended_reference_set', 'summary'],
}

phase('Inventory')
const [transcripts, audio] = await parallel([
  () => agent(`${RULES}

TASK: inventory every file in the archive.org item "ssggsm-transcripts".
Steps: curl https://archive.org/metadata/ssggsm-transcripts ; keep only files with source=="original" ; parse each name for the 8-digit date prefix, a scripture reference (SB / CC / BG / Bhagavad-gita / Caitanya-caritamrta etc.), and a place name. Write the full parsed list as JSON to ${SCRATCH}/transcripts-index.json and report its path.
Then choose exactly 8 filenames for a reading sample: spread them across extensions (at least 4 .rtf, 1 .docx, 2 .doc, 1 .pdf if those exist) and across dated and undated names, preferring names that look like ordinary lectures rather than biographies or songs.
Also list any filenames that plausibly match the 1985-08-21 Zurich lecture on Srimad-Bhagavatam 6.2.36-37 (look for 19850821, "6.2.36", "6_2_36", "Zurich").`, { label: 'inventory:transcripts', phase: 'Inventory', schema: INVENTORY_SCHEMA }),
  () => agent(`${RULES}

TASK: inventory the audio filenames across the ten SSGGSM year items.
Steps: for each of SSGGSM1985 SSGGSM1986 SSGGSM1989 SSGGSM1990 SSGGSM1991 SSGGSM1992 SSGGSM1993 SSGGSM1994 SSGGSM1995 SSGGSM1996, curl https://archive.org/metadata/<item> and keep files with source=="original" that end in .mp3. For each, record name, size, length (seconds), md5, sha1 and the item it belongs to. Parse each name into date (the D.M.YY prefix), scripture reference and place. Detect files that look like sides or parts of one lecture ("Side A", "Side B", "GK10A", "part 2", "pt2"). Detect md5 values that appear more than once.
Write the full parsed index as JSON to ${SCRATCH}/audio-index.json and report its path. Report per-item counts, how many names yielded a date, a verse and a place, the multi-part count, duplicate md5 count, and total duration in hours (treat a missing length as 0 and say how many were missing in notes).`, { label: 'inventory:audio', phase: 'Inventory', schema: AUDIO_SCHEMA }),
])

log(`transcripts: ${transcripts ? transcripts.total_files : 'FAILED'} files; audio: ${audio ? audio.total_audio_files : 'FAILED'} files`)

phase('Sample')
const sample = (transcripts && transcripts.sample_for_reading ? transcripts.sample_for_reading : []).slice(0, 8)
const assessments = (await parallel(sample.map((name, i) => () => agent(`${RULES}

TASK: fetch one transcript file from archive.org and judge whether it is a VERBATIM transcript of speech or an EDITED text.
File name (exact): ${name}
Download it with curl into ${SCRATCH}/sample-${i}/ . URL form: https://archive.org/download/ssggsm-transcripts/<URL-encoded file name>.
Extract plain text with what is available: for .rtf strip RTF control words with a small python script; for .docx unzip word/document.xml with python's zipfile and strip tags; for .doc try python (there is no antiword) and if you cannot, set parsed=false and say why; for .pdf try pdftotext and if missing, set parsed=false.
Then judge, quoting short excerpts as evidence:
- VERBATIM markers: filler words (um, uh, you know), false starts and self-corrections, repeated words, unfinished sentences, audience questions and answers, transcriber notes like [inaudible], time stamps, speaker labels.
- EDITED markers: clean complete sentences throughout, section headings, footnotes, diacritics on Sanskrit words (a typeset style), no fillers at all, paragraph structure typical of published books.
Count each signal. Estimate the word count. Say whether the file appears to cover a whole lecture or only part. Extract any date, scripture reference and place you can from the name or the text.
Remember: a text with zero fillers across thousands of words is strong evidence of editing, not of a perfect speaker.`, { label: `sample:${i + 1}`, phase: 'Sample', schema: SAMPLE_SCHEMA }))))
  .filter(Boolean)

log(`assessed ${assessments.length}/${sample.length} sampled transcripts`)

phase('Pair')
const [pairing, wer] = await parallel([
  () => agent(`${RULES}

TASK: work out how well transcript names can be paired to audio names automatically.
Inputs: the transcript index at ${transcripts ? transcripts.index_path : SCRATCH + '/transcripts-index.json'} and the audio index at ${audio ? audio.index_path : SCRATCH + '/audio-index.json'}. Read both with python.
Write a matching script in ${SCRATCH} that tries, in order: (1) exact date match plus scripture-reference match; (2) date only; (3) scripture reference plus place; (4) fuzzy title similarity. Count high-confidence pairs (a rule that identifies exactly one audio file), ambiguous pairs (more than one candidate) and transcripts that cannot be paired at all. Give up to 8 example pairs as "transcript -> audio" strings. State the single biggest limiting factor, with a number behind it.`, { label: 'pair:match', phase: 'Pair', schema: PAIR_SCHEMA }),
  () => agent(`${RULES}

TASK: if a transcript exists for the 1985-08-21 Zurich lecture, measure how far local Whisper output is from it.
The local ASR output for that lecture is read-only at C:/Users/Mukul/code/personal-projects/lecture-archive/data/transcribe/jobs/21-8-85-20sb6-2-36-37-20zurich-6ca3c5b8/asr/full.jsonl (one JSON object per line with a "text" field). Do not modify it. The audio is 89.2 minutes.
Candidate transcript filenames from the inventory: ${transcripts && transcripts.zurich_candidates && transcripts.zurich_candidates.length ? transcripts.zurich_candidates.join(' | ') : '(none found — search the index yourself at ' + (transcripts ? transcripts.index_path : SCRATCH + '/transcripts-index.json') + ' for 1985 dates, "6.2.36", "6_2_36" or "Zurich")'}
If you find a plausible match: download it, extract text, and compute the word error rate of the ASR text against it with a python script you write in ${SCRATCH} (Levenshtein over word tokens; normalize by lowercasing, stripping punctuation, and collapsing whitespace; state your normalization). Report both word counts.
If no transcript matches that lecture, set attempted=false and explain what you searched. Do not transcribe any audio yourself and do not run Whisper — the CPU is busy.
In "interpretation", be explicit about what the number proves: a low rate means the transcript is close to the audio's words; a high rate could mean either poor ASR or an edited transcript, and cannot tell them apart on its own.`, { label: 'pair:wer', phase: 'Pair', schema: WER_SCHEMA }),
])

phase('Synthesize')
const synthesis = await agent(`${RULES}

TASK: decide whether these existing transcripts can serve as the reference set for measuring Whisper's accuracy on this corpus, and how to build that reference set.
Evidence, as JSON:
TRANSCRIPT INVENTORY: ${JSON.stringify(transcripts)}
AUDIO INVENTORY: ${JSON.stringify(audio)}
SAMPLE ASSESSMENTS (${assessments.length} files): ${JSON.stringify(assessments)}
PAIRING: ${JSON.stringify(pairing)}
WER ATTEMPT: ${JSON.stringify(wer)}
Context for the recommendation: one person will do the listening and correcting, the corpus is at least 7,378 audio-hours across 5,936 files, and there is no budget for paid transcription services. A reference set is needed to choose between Whisper model settings. The owner can listen to roughly 2-3 hours of audio at a time.
Produce: an estimate of what share of the 833 transcripts look verbatim (with the sample size stated plainly); whether they are usable as a reference set; a concrete recommended reference set (which lectures, how many minutes in total, how to build it, and how much human listening it costs); a pairing recommendation; what file-conversion tooling would be needed to use the transcripts at scale; risks; and open questions.
Do not overstate: ${assessments.length} sampled files out of 833 cannot settle the whole corpus. Give the numbers behind every claim.`, { label: 'synthesize', phase: 'Synthesize', schema: SYNTH_SCHEMA })

return { transcripts, audio, assessments, pairing, wer, synthesis }
