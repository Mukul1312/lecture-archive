export const meta = {
  name: 'ssggsm-reference-and-catalogue-prep',
  description: 'Resolve the Melbourne subtitle offset, read the archive catalogues, measure Final-pass editing, build a glossary, and test tape-boundary detection',
  phases: [
    { title: 'Prepare', detail: 'archive catalogues, subtitle offset, draft-vs-Final diffs, glossary, boundary probe' },
    { title: 'Synthesize', detail: 'what is ready for the listening sitting and what it changes' },
  ],
}

const SCRATCH = 'C:/Users/Mukul/AppData/Local/Temp/claude/c--Users-Mukul-code-personal-projects-lecture-archive/7043a597-7e85-48b9-ba1e-a11f0eeb11b9/scratchpad/refprep'
const INDEX = 'C:/Users/Mukul/AppData/Local/Temp/claude/c--Users-Mukul-code-personal-projects-lecture-archive/7043a597-7e85-48b9-ba1e-a11f0eeb11b9/scratchpad/transcript-check/transcripts-index.json'
const AUDIO_INDEX = 'C:/Users/Mukul/AppData/Local/Temp/claude/c--Users-Mukul-code-personal-projects-lecture-archive/7043a597-7e85-48b9-ba1e-a11f0eeb11b9/scratchpad/transcript-check/audio-index.json'

const RULES = `HARD RULES — read twice.
1. An rclone upload to Google Drive is running on this machine. NEVER kill, inspect, configure or invoke rclone. Keep network use modest: download only the files your task names.
2. BE GENTLE WITH THE CPU. If you run faster-whisper, use the interpreter at C:/Users/Mukul/code/personal-projects/lecture-archive/.venv-transcribe/Scripts/python.exe, model "small", device cpu, compute_type int8, cpu_threads=4, and transcribe at most 3 audio windows of at most 2 minutes each. Never transcribe a whole lecture. Never run pyannote or any diarization model.
3. C:/Users/Mukul/code/personal-projects/lecture-archive is READ-ONLY. Write every temp file under ${SCRATCH} (mkdir -p it first). No pip installs — stdlib plus what is installed (antiword, pdftotext, ffmpeg, ffprobe, numpy are available; striprtf, pandas, libreoffice, catdoc are NOT).
4. Report honestly with numbers. Say UNVERIFIED rather than guessing. Small samples prove little — say so.

CONTEXT. Archive.org item "ssggsm-transcripts" holds 833 original files of English-lecture transcripts by Srila Gour Govinda Swami Maharaja; items SSGGSM1985..SSGGSM1996 hold 5,936 mp3 recordings. A previous pass found: only 16 of 818 documents are marked "Final" (the archive's own description says everything else is a draft that "may have many errors"); all 8 sampled transcripts covered only part of their lecture; two .srt subtitle files exist and are the best reference material in the corpus; 32.9% of mp3s are compilation tapes holding several lectures joined by "&"; 77.9% of mp3s are duplicate tape copies of another recording.
Parsed indexes you can reuse (read, do not modify): transcripts ${INDEX}, audio ${AUDIO_INDEX}.
The owner will spend one 2-2.5 hour sitting verifying the Melbourne subtitle file against its audio, to create a verbatim reference for measuring Whisper accuracy. Your work must make that sitting productive.`

const CATALOGUE_SCHEMA = {
  type: 'object',
  properties: {
    xls_read: { type: 'boolean' },
    mdb_read: { type: 'boolean' },
    method: { type: 'string' },
    xls_shape: { type: 'string', description: 'sheets, columns, row count' },
    mdb_shape: { type: 'string', description: 'tables, columns, row count' },
    columns: { type: 'array', items: { type: 'string' } },
    has_place_legend: { type: 'boolean' },
    place_codes_found: { type: 'number' },
    has_verse_refs: { type: 'boolean' },
    has_session_or_duplicate_info: { type: 'boolean' },
    row_count_total: { type: 'number' },
    csv_paths: { type: 'array', items: { type: 'string' } },
    overlap_with_owner_sheet: { type: 'string', description: 'how its columns line up with the owner sheet columns given in the prompt' },
    notes: { type: 'string' },
  },
  required: ['xls_read', 'mdb_read', 'method', 'notes'],
}

const OFFSET_SCHEMA = {
  type: 'object',
  properties: {
    srt_cues: { type: 'number' },
    srt_first_cue_time: { type: 'string' },
    srt_last_cue_time: { type: 'string' },
    srt_span_minutes: { type: 'number' },
    audio_file_used: { type: 'string' },
    audio_duration_minutes: { type: 'number' },
    offset_seconds: { type: 'number', description: 'subtract this from SRT times to get audio times; 0 if they already align' },
    offset_confidence: { type: 'string', enum: ['high', 'medium', 'low', 'unresolved'] },
    method: { type: 'string' },
    probe_evidence: { type: 'array', items: { type: 'string' }, description: 'what each probe window returned and how it matched SRT text' },
    coverage_check: { type: 'string', description: 'does the SRT cover the whole lecture or part of it' },
    listening_instructions: { type: 'string', description: 'exact steps for the owner: which audio URL, which SRT, what offset to apply, how to note errors' },
    notes: { type: 'string' },
  },
  required: ['srt_cues', 'offset_confidence', 'method', 'listening_instructions', 'notes'],
}

const DIFF_SCHEMA = {
  type: 'object',
  properties: {
    pairs_compared: { type: 'number' },
    per_pair: { type: 'array', items: { type: 'string' }, description: 'one line per pair: names, word counts, % words changed, what kind of edits' },
    edit_categories: { type: 'object', additionalProperties: true, description: 'counts of edit kinds seen: filler removal, verse substitution, readability insertion, span notes, reordering' },
    median_percent_words_changed: { type: 'number' },
    implication_for_wer: { type: 'string' },
    notes: { type: 'string' },
  },
  required: ['pairs_compared', 'implication_for_wer', 'notes'],
}

const GLOSSARY_SCHEMA = {
  type: 'object',
  properties: {
    files_read: { type: 'number' },
    extractor_used: { type: 'string' },
    legacy_font_files: { type: 'number', description: 'files whose diacritics are stored as legacy font bytes' },
    candidate_terms: { type: 'number' },
    top_terms: { type: 'array', items: { type: 'string' }, description: 'up to 40 highest-value terms for a Whisper prompt' },
    variant_clusters: { type: 'array', items: { type: 'string' }, description: 'up to 15 examples of one name spelled several ways' },
    glossary_path: { type: 'string' },
    recommended_prompt: { type: 'string', description: 'a concrete initial_prompt / hotwords string under 400 characters' },
    notes: { type: 'string' },
  },
  required: ['files_read', 'extractor_used', 'candidate_terms', 'glossary_path', 'notes'],
}

const BOUNDARY_SCHEMA = {
  type: 'object',
  properties: {
    tape_used: { type: 'string' },
    duration_minutes: { type: 'number' },
    expected_sessions: { type: 'number' },
    silence_candidates: { type: 'array', items: { type: 'string' }, description: 'timestamps of long silences with their lengths' },
    loudness_or_spectral_shifts: { type: 'array', items: { type: 'string' } },
    music_or_kirtana_candidates: { type: 'array', items: { type: 'string' } },
    boundary_found: { type: 'string', enum: ['yes', 'probable', 'no', 'unresolved'] },
    best_boundary_estimate: { type: 'string' },
    verification: { type: 'string', description: 'how a short Whisper probe around the estimate supported or refuted it' },
    method_cost: { type: 'string', description: 'wall-clock time and what it would cost across 1,954 compilation tapes' },
    diarization_verdict: { type: 'string', description: 'whether speaker diarization would add anything the cheap signals did not give' },
    notes: { type: 'string' },
  },
  required: ['tape_used', 'boundary_found', 'method_cost', 'diarization_verdict', 'notes'],
}

const SYNTH_SCHEMA = {
  type: 'object',
  properties: {
    listening_sitting_ready: { type: 'boolean' },
    listening_brief: { type: 'string', description: 'the exact instructions to hand the owner' },
    catalogue_verdict: { type: 'string' },
    boundary_strategy: { type: 'string' },
    glossary_verdict: { type: 'string' },
    wer_harness_rules: { type: 'string', description: 'normalization and exclusion rules the accuracy harness must apply' },
    surprises: { type: 'array', items: { type: 'string' } },
    next_actions: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string' },
  },
  required: ['listening_sitting_ready', 'listening_brief', 'boundary_strategy', 'summary'],
}

phase('Prepare')
const [catalogue, offset, diffs, glossary, boundary] = await parallel([
  () => agent(`${RULES}

TASK: read the archive's own lecture catalogue files and convert them to CSV.
Files, both inside archive.org item "ssggsm-transcripts": "Data base of lectures.xls" (about 45 KB) and "database for lectures.mdb" (about 717 KB). Download with curl using URL-encoded names to ${SCRATCH}/catalogue/.
No pandas, xlrd or Access tooling exists here, so parse the formats yourself with the stdlib: .xls is an OLE2 compound file containing a BIFF workbook stream (parse the FAT/directory, then walk BIFF records: BOF, BOUNDSHEET, LABELSST/SST for shared strings, LABEL, NUMBER, RK, ROW, EOF); .mdb is a Jet database (page-based: parse the page size from the header, walk table definition pages (type 0x02) and data pages (type 0x01) to recover column names and row values). Recover as much as you honestly can — partial recovery of column names and a sample of rows is a useful result; claiming success you cannot show is not.
Write whatever you recover as CSV under ${SCRATCH}/catalogue/ and report the paths.
Then compare against the owner's own tracking sheet, whose columns are exactly: Folder Year | Primary Date | Date Quality | All Dates on Tape | Sessions Detected | Title / Tape Label | Scripture References | Session Type Codes | Location Code | Location Name | Variant / Source Marker | Quality / Consistency Flags | Duplicate Group ID | Tapes in Group | Likely Duplicate Copy | Filename | Download URL.
Report specifically: does the archive catalogue contain a place-code legend (e.g. BBSR=Bhubaneswar, MEL=Melbourne, PHI=Philadelphia), authoritative verse references, session or duplicate information, and anything the owner's sheet lacks.`, { label: 'catalogue:xls+mdb', phase: 'Prepare', schema: CATALOGUE_SCHEMA }),

  () => agent(`${RULES}

TASK: make the owner's listening sitting productive by resolving the subtitle clock offset.
Subtitle file: "19901114_SB12.10.2_Melbourne_TakeHolyNameBecomeFearless.srt" in item ssggsm-transcripts (download it; it has about 512 cues, first cue near 01:01:09, last near 02:10:02, spanning about 68.9 minutes).
Audio candidates in item SSGGSM1990: "90-11-14 SB12.10.2 MEL 90-85.mp3" (about 92.7 min) and "90-11-14 SB12.10.2 MEL BTM143.mp3" (about 88.4 min). Confirm durations with ffprobe after download.
The subtitle clock does not match any audio here, so find the constant offset. Method: take distinctive text from the first cues, the middle and the last cues. Use ffmpeg to cut at most three windows of at most 2 minutes from ONE audio file and transcribe them with faster-whisper under the CPU limits above. Compare what each window says with the subtitle text at the corresponding clock position, and solve for the offset. Sensible hypotheses to test: offset 3669 s (the first cue time, i.e. the subtitles were timed against a video with an hour of preceding material), offset 0, and the difference between the audio duration and the subtitle span.
Report the offset with a confidence, and whether the subtitles cover the whole lecture or only part.
Finally write "listening_instructions": precise steps for the owner — which audio URL to open, which subtitle file, what offset to apply, how to mark a wrong cue, and how long it should take. Assume they will listen straight through once.`, { label: 'reference:srt-offset', phase: 'Prepare', schema: OFFSET_SCHEMA }),

  () => agent(`${RULES}

TASK: measure how much editing a "Final" pass applies, by diffing the four lectures that exist as both draft and Final.
Find their exact filenames in ${INDEX}. The four stems are: 19890310_SB4.20.28-29_Mayapur_FollowthePathoftheMahajanas, 19890325_SB7.7.12-14_Bhubaneswar_GuruMustBePremiBhakta, "19000000 another class" (.doc and .rtf), "19940215 appearance_vishnupriya_bbsr" (.doc and .rtf).
Download both members of each pair into ${SCRATCH}/diffs/, extract plain text (antiword for .doc, your own stdlib RTF stripper for .rtf, python zipfile for .docx), and compare: word counts each side, percentage of words changed (a word-level diff via difflib is fine), and WHAT changed. Classify the edits you see: hesitation or filler removal, repetition removal, verse text replaced with published translations, parenthetical readability insertions, language-span notes replacing speech, reordering, spelling normalisation of names.
Then state plainly what this implies for using drafts or Finals as a reference for measuring speech-recognition accuracy, with the numbers behind it.`, { label: 'measure:draft-vs-final', phase: 'Prepare', schema: DIFF_SCHEMA }),

  () => agent(`${RULES}

TASK: build a candidate glossary of recurring names and terms, to feed Whisper's initial_prompt and hotwords.
Choose about 60 .rtf transcripts from ${INDEX}, spread across the years 1985-1996 and across places. Download them into ${SCRATCH}/glossary/ and extract text with ONE stripper that you write and keep (do not write several). Validate your stripper first against any already-extracted sample text under .../scratchpad/transcript-check/sample-*/ if present, and say whether it agreed.
Watch for legacy Sanskrit fonts: diacritics may be stored as 8-bit font slots (Balaram, Sanskrit-Times, Rama-Palatino) rather than Unicode, which decodes to mojibake. Count how many files show this and keep those files' terms out of the glossary unless you can decode them.
From the clean text, extract: proper nouns (people, places, deities), Sanskrit and Bengali terms, and scripture titles. Rank by document frequency. Cluster spelling variants of the same term (one sampled file spelled one name five ways). Write the full ranked list with counts to a CSV under ${SCRATCH}/glossary/ and report its path.
Finally propose a concrete initial_prompt string under 400 characters: the terms most likely to help an English Whisper decode this speaker, without biasing it toward words he rarely says.`, { label: 'glossary:terms', phase: 'Prepare', schema: GLOSSARY_SCHEMA }),

  () => agent(`${RULES}

TASK: find out whether a lecture boundary on a compilation tape can be detected cheaply, without diarization.
Tape: "89-03-27 SB7.7.16 & 89-03-30 CCAdi4.225 BBSR DINA2.mp3" in item SSGGSM1989 — its name says it holds two lectures, recorded three days apart. Download it to ${SCRATCH}/boundary/ and confirm its duration with ffprobe.
Try the cheap signals, in this order, and report what each gave:
1. ffmpeg silencedetect at a few thresholds (e.g. -35 dB and -45 dB, minimum 2 s and 5 s) — list the long silences with timestamps.
2. A loudness or spectral profile over time (ffmpeg astats or ebur128 in short windows) — look for a step change in noise floor or room sound, which is what a tape splice between two different recordings produces.
3. Music or chanting stretches, which often sit between sessions. Use a simple spectral heuristic; do not install anything.
Then verify: pick your best boundary estimate and transcribe at most two 2-minute windows (one just before, one just after) under the CPU limits above. A real boundary shows an ending (closing prayers, "Hare Krishna") followed by an opening (invocation, a new verse being read).
Report the wall-clock cost of your method for one tape and what it would cost across 1,954 compilation tapes. Then answer plainly: would speaker diarization have told you anything these signals did not, given both sessions have the same lecturer? Judge only from what you observed.`, { label: 'boundary:cheap-signals', phase: 'Prepare', schema: BOUNDARY_SCHEMA }),
])

log(`prepare done: catalogue=${catalogue ? 'ok' : 'FAILED'} offset=${offset ? offset.offset_confidence : 'FAILED'} diffs=${diffs ? diffs.pairs_compared : 'FAILED'} glossary=${glossary ? glossary.candidate_terms : 'FAILED'} boundary=${boundary ? boundary.boundary_found : 'FAILED'}`)

phase('Synthesize')
const synthesis = await agent(`${RULES}

TASK: pull this together for the owner, who is about to spend one 2-2.5 hour sitting building a verbatim reference, and who then wants a transcription pipeline design.
EVIDENCE:
ARCHIVE CATALOGUE: ${JSON.stringify(catalogue)}
SUBTITLE OFFSET: ${JSON.stringify(offset)}
DRAFT VS FINAL: ${JSON.stringify(diffs)}
GLOSSARY: ${JSON.stringify(glossary)}
TAPE BOUNDARY: ${JSON.stringify(boundary)}
Also known: the owner's tracking sheet already carries Duplicate Group ID, Tapes in Group, Likely Duplicate Copy, Sessions Detected, All Dates on Tape, Location Code/Name, Variant/Source Marker and a direct archive.org Download URL per tape. Transcripts will be corrected on a website with private drafts and public publication, replacing OneNote. Diarization is deferred unless it earns its place. The machine is a 6-core Ryzen 5 5625U laptop with no CUDA GPU.
Produce:
1. listening_brief — the exact instructions to hand the owner for the sitting, or, if the offset is unresolved, the smallest extra step needed before the sitting is worth doing.
2. catalogue_verdict — whether the archive's own catalogue adds anything to the owner's sheet, and what to take from it.
3. boundary_strategy — how to split compilation tapes, with the cost, and a plain yes or no on diarization based on the evidence.
4. glossary_verdict — is the glossary usable for a Whisper prompt, and what would make it better.
5. wer_harness_rules — the normalization and exclusion rules the accuracy harness must apply, given that these transcripts never contain fillers, are often partial, and use gap placeholders.
6. surprises, next_actions, summary.
Be specific and quantitative. Where a stage failed or returned low confidence, say what is still unknown rather than papering over it.`, { label: 'synthesize', phase: 'Synthesize', schema: SYNTH_SCHEMA })

return { catalogue, offset, diffs, glossary, boundary, synthesis }
