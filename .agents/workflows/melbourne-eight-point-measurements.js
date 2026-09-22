export const meta = {
  name: 'melbourne-eight-point-measurements',
  description: 'Measure correction workload, error signals, timing drift and Sanskrit lexicon headroom on the verified Melbourne reference',
  phases: [
    { title: 'Measure', detail: 'four independent measurements on the verified reference and the six matrix transcripts' },
    { title: 'Verify', detail: 'independent recomputation of every headline number from the raw files' },
  ],
}

const COMMON = `
You are working in the repository C:\\Users\\Mukul\\code\\personal-projects\\lecture-archive (Windows, PowerShell and Bash both available).

CONTEXT. A steward (Mukul) is building a transcription pipeline for ~3,766 unique Gour Govinda Swami lectures. He has produced ONE human-verified accuracy reference: he listened to a 69.8-minute 1990 Melbourne lecture and checked all 512 subtitle cues, correcting 17. A settings matrix of six Whisper configurations has just been scored against it. The chosen configuration is medium-beam1: English 20.1% of words wrong or missing, Sanskrit 61.4% unrecognisable, 2.04x real time.

THE FILES YOU NEED (read-only unless stated):
- Verified reference: data/reference/MELBOURNE_vs_90-85_aligned-review.json. Keys: schema, source_srt, offset_ms, cues[]. Each cue: {n, start_ms, end_ms, original, text, status, note}. "text" is the VERIFIED text, "original" the uncorrected subtitle text, status one of ok|fixed. NEVER MODIFY THIS FILE OR ITS .bak.
- Six transcripts: data/reference/matrix-<name>-words.jsonl where <name> is one of small-beam1, small-beam1-prompt, small-beam5, medium-beam1, turbo-beam1, turbo-beam1-prompt. One JSON object per line: {"w": " word", "s": start_seconds, "e": end_seconds, "p": word_probability}. Times are absolute seconds in the mp3.
- Run metadata: data/reference/matrix-<name>-run.json (wall_seconds, speed_vs_realtime, words, gaps_refilled).
- Scores already computed: data/reference/accuracy-<name>.json and data/reference/matrix-summary.json.
- Spans the subtitles never covered, which MUST be excluded from scoring: data/reference/retime-report.json key "spoken_but_not_subtitled" (list of [start,end] seconds). Also has "unmatched_cues" (79 cue numbers whose times were interpolated, not matched to speech).
- THE SCORER TO REUSE, do not reinvent it: scripts/transcript_accuracy.py. Import it (fold, has_diacritics, recognisable, skeleton, score, load_reference, load_hypothesis). fold() lowercases, strips diacritics and drops fillers. has_diacritics() marks a reference word as Sanskrit/name because the verified text writes those in IAST. recognisable() decides whether a heard romanisation would be recognised as the reference word.
- Glossary already built from 66 lecture RTFs: data/research/ssggsm-2026-09/refprep/glossary/{glossary-by-name.csv, glossary-candidates.csv, glossary-curated-top.csv, variant-clusters.csv, scripture-refs.csv} and the builder glossary.py.
- Earlier research code, including the naive quality signal: data/research/ssggsm-2026-09/transcript-check/ (see count_signals.py, count.py, collapse.py).

HARD RULES.
1. Use plain "python" (stdlib only is enough; pandas is NOT guaranteed). ALWAYS set PYTHONIOENCODING=utf-8 before running python, or Windows cp1252 will crash on the IAST text. In Bash: PYTHONIOENCODING=utf-8 python script.py
2. Do NOT run any Whisper decoding, ffmpeg, or anything CPU-heavy. Everything you need is already on disk. No network.
3. Do NOT modify any existing file. Do NOT git add, commit or push. Write NEW files only, into data/reference/analysis/ (create it). Save your analysis script there too, so the work is reproducible.
4. MEASURE, do not estimate. If something cannot be measured from the data on disk, say so plainly in "caveats" and do not invent a number. Wrong numbers here cost the steward months of machine time or years of his own correction time. Several earlier claims in this project turned out to be wrong precisely because they were plausible rather than measured.
5. State the arithmetic behind every number you report, in the "how" field, well enough that someone else could redo it.
6. Report what contradicts your own expectation, not just what confirms it.
`

const MEASURE_SCHEMA = {
  type: 'object',
  properties: {
    headline: { type: 'string', description: 'One sentence: the single most decision-relevant thing you measured.' },
    numbers: {
      type: 'array',
      description: 'Every headline number, with the arithmetic behind it.',
      items: {
        type: 'object',
        properties: {
          name: { type: 'string' },
          value: { type: 'string' },
          how: { type: 'string', description: 'The exact computation: inputs, formula, file paths.' },
        },
        required: ['name', 'value', 'how'],
      },
    },
    conclusions: { type: 'array', items: { type: 'string' }, description: 'What this means for the pipeline, in plain words.' },
    surprises: { type: 'array', items: { type: 'string' }, description: 'Anything that contradicted your expectation.' },
    caveats: { type: 'array', items: { type: 'string' }, description: 'What you could NOT measure, and what is assumed rather than measured.' },
    files_written: { type: 'array', items: { type: 'string' } },
    commands_to_reproduce: { type: 'array', items: { type: 'string' } },
  },
  required: ['headline', 'numbers', 'conclusions', 'surprises', 'caveats', 'files_written'],
}

const TASKS = [
  {
    key: 'workload',
    title: 'correction workload',
    prompt: `${COMMON}
YOUR TASK: measure how much CORRECTION LABOUR each configuration implies. The steward must correct these transcripts by hand, for thousands of lectures, so this number decides his publishing policy.

Do all of this:

1. VERIFY HIS SPEAKING RATE. He is said to speak "about 94 words a minute, roughly 5,700 words an hour". Measure it from the verified reference: reference word count over the reference span (first cue start_ms to last cue end_ms). Report words per minute for the whole span, and separately for English-only and Sanskrit-only words. Also report the rate measured over only the time actually covered by cues, since silence and untranscribed spans deflate the average.

2. COUNT EDIT SITES, NOT ERROR WORDS. This is the important part. 1,901 wrong/missing/invented words does not mean 1,901 corrections: adjacent wrong words are one edit. Align the verified reference to each transcript with difflib.SequenceMatcher over folded tokens (exactly as scripts/transcript_accuracy.py does, including the Sanskrit rescue via recognisable(), and excluding the spoken_but_not_subtitled spans). Then count CONTIGUOUS non-equal opcode blocks that survive the Sanskrit rescue. Report per configuration: edit sites, edit sites per hour of audio, mean and median words per site, and the distribution of site sizes (1 word, 2-3, 4-10, >10).

3. SPLIT BY TRACK. Edit sites that are purely English, purely Sanskrit/names, and mixed. The steward cares because Sanskrit fixes need a different skill (IAST spelling) from English fixes.

4. MEASURE HIS ACTUAL WORKING RATE, do not assume it. The sitting really happened and left traces: data/reference/MELBOURNE_vs_90-85_aligned-review-snapshots/ (snapshots written at most every 10 minutes) and MELBOURNE_vs_90-85_synced-review-snapshots/, plus the review's last_position_s and each cue's status. Use file modification times and the number of cues checked in successive snapshots to reconstruct how long the sitting took and how many cues per hour he actually got through. Report the observed rate, and be explicit about what the snapshot timestamps can and cannot tell you (e.g. gaps could be breaks). Note he did the work in two passes: the earlier "synced" review was carried over into the "aligned" one.

5. PROJECT THE CORPUS. Using the medium-beam1 edit-site rate and the OBSERVED working rate from step 4, estimate the steward's total correction time for 3,766 lectures. Give a range, and label every assumption. The average lecture length is NOT known (a 55-minute guess is currently used); express the answer per 1,000 hours of audio as well, so it survives that guess being wrong.

6. ANSWER THIS DIRECTLY: how much correction labour does choosing medium-beam1 over small-beam1 actually save, in his hours? That is the real payoff of the extra machine time, and nobody has computed it.

Write your script and results to data/reference/analysis/.`,
  },
  {
    key: 'signals',
    title: 'error-signal calibration',
    prompt: `${COMMON}
YOUR TASK: calibrate the warning signals that will tell the steward WHERE to look on the other ~3,700 lectures. Without calibration he must listen to everything with equal attention; with it, the pipeline points at the probable mistakes. One existing signal is known to be useless (it flagged 481 of 785 segments), and that failure is what this task must avoid repeating.

Do all of this:

1. BUILD GROUND TRUTH. Align the verified reference to the medium-beam1 transcript (difflib.SequenceMatcher over folded tokens, Sanskrit rescue via recognisable(), excluding spoken_but_not_subtitled spans), and label every HEARD word as correct or incorrect. Keep each heard word's time and probability p. Report how many heard words you could label and how many you had to discard, and why.

2. CUT THE LECTURE INTO WINDOWS. Use fixed windows (try both 15 s and 30 s) over the reference span. For each window record: error count, error rate, and every candidate signal below. Define a window as "bad" by a threshold you state (e.g. >=3 errors, or error rate above the lecture mean); report results for more than one definition so the choice is visible.

3. TEST THESE CANDIDATE SIGNALS, each on its own:
   - mean word probability in the window
   - minimum word probability
   - share of words with p below 0.3, 0.5, 0.7
   - longest silent gap inside the window (consecutive word end to next word start)
   - words per minute in the window (both unusually low and unusually high)
   - immediate repetition: repeated unigrams/bigrams/trigrams, the classic Whisper loop
   - share of very short tokens (1-2 characters)
   - distance to the nearest gap that had to be re-decoded (matrix-<name>-run.json records gaps_refilled; recompute the gap positions yourself from the words file: gaps >= 6 s between consecutive words)
   - whether the window overlaps one of the 79 interpolated cues from retime-report.json
   Also test at least two COMBINATIONS you think might beat any single signal, and say why you chose them.

4. REPORT PRECISION AND RECALL PROPERLY. For each signal and each threshold: precision, recall, F1, and LIFT over the base rate (what fraction of windows are bad overall). A signal that flags almost everything has high recall and no value - lift is what exposes that. Produce a table sorted by usefulness, and state plainly which signals are worth putting in the pipeline and at what threshold, and which are noise.

5. QUANTIFY THE KNOWN-BAD SIGNAL. Read data/research/ssggsm-2026-09/transcript-check/count_signals.py (and count.py/collapse.py) to see what the 481-of-785 signal actually was. Recompute its precision, recall and lift on this labelled data, so its uselessness is a measurement rather than an anecdote.

6. ANSWER THIS DIRECTLY: if the steward can only afford to listen to 20% of each lecture, which signal ranking puts the most real errors in that 20%? Report the fraction of all errors captured in the top 10%, 20% and 30% of windows for your best ranking, against what random sampling would give.

Write your script and results to data/reference/analysis/.`,
  },
  {
    key: 'timing',
    title: 'read-along timing drift',
    prompt: `${COMMON}
YOUR TASK: measure how trustworthy Whisper's WORD TIMINGS are. The planned website highlights words while the audio plays, so drift shows up directly as the wrong word being lit.

Be careful about circularity, and say so in your caveats: the verified reference's cue times were themselves produced by matching Whisper words (scripts/reference_editor/retime.py), so comparing Whisper times to those cue times partly measures Whisper against itself. Design around that.

Do all of this:

1. CROSS-MODEL AGREEMENT AS A BOUND. Six independent transcripts of the same audio exist. For words that two models agree on (same folded token, in matching alignment positions), compare their start times. Report the distribution of disagreement (median, p90, p95, max) for these pairs at minimum: medium-beam1 vs turbo-beam1, medium-beam1 vs small-beam1, turbo-beam1 vs turbo-beam1-prompt. Explain clearly what this does and does not prove: agreement is not correctness, but disagreement is a floor on the error.

2. COMPARE AGAINST WORD DURATION. Report the distribution of word durations (e) minus (s) in medium-beam1. Timing error only matters relative to how long a word is on screen. State the drift as a fraction of a typical word.

3. THE ANCHORED CUES. For the 433 cues that the re-timing anchored to real speech, compare the cue start time to the start of the first heard word of its matched text in medium-beam1. Report the distribution. Then state honestly how much of this is circular (those cue times came from the small-model words, so medium is at least an independent decoder).

4. DRIFT OVER THE LECTURE. Test whether disagreement grows with time into the recording (a known long-form decoding problem). Fit or bucket by 10-minute blocks and report. If it grows, that changes the pipeline: long lectures would need splitting.

5. THE GAPS. Words recovered by the gap re-decode were decoded in a separate short window and then offset back into absolute time. Check whether those re-decoded words have systematically worse timing agreement than the rest. Identify them as words falling inside a gap >= 6 s in another configuration's word stream, or by any better method you can justify.

6. ANSWER THIS DIRECTLY: is word-level highlighting safe to build, or should the website highlight at the sentence or cue level? Give the threshold that decides it, and the measured number against that threshold. A reader's tolerance for a highlight landing on the wrong word is roughly one word's duration; argue from your measurements.

Write your script and results to data/reference/analysis/.`,
  },
  {
    key: 'lexicon',
    title: 'Sanskrit lexicon headroom',
    prompt: `${COMMON}
YOUR TASK: find out whether a POST-HOC LEXICON PASS can fix the Sanskrit problem. This is the biggest open question in the project. Every decoder setting tried has failed on Sanskrit: the best of six configurations still leaves 61.4% of Sanskrit words unrecognisable, the glossary initial_prompt changed nothing, and large-v3-turbo is actually WORSE at Sanskrit (71.0%) than the small model (68.0%). The remaining idea is to correct the text AFTER decoding, by matching heard romanisations against the glossary already built from 66 lecture RTFs.

Do all of this:

1. CHARACTERISE THE PROBLEM. From the verified reference, list the 676 Sanskrit/name words (has_diacritics() on the verified text marks them). Report the distinct vocabulary, the frequency distribution, and how the medium-beam1 errors break down: Sanskrit words heard as a recognisable romanisation, heard as something unrecognisable, missing entirely, or glued into a neighbouring word. Whisper glues compounds, so count how often the reference's multi-word Sanskrit phrases appear as one heard token or vice versa.

2. CHECK THE GLOSSARY'S COVERAGE HONESTLY. The claim on record is that the glossary covers "25-61% of the Sanskrit in this lecture" - a range that suggests two different definitions were mixed. Measure it properly and define your terms: coverage of distinct Sanskrit vocabulary, and coverage weighted by how often each word occurs. Use glossary-by-name.csv, glossary-candidates.csv and variant-clusters.csv, and say which file gives which answer.

3. MEASURE THE UPPER BOUND OF A LEXICON PASS. For each Sanskrit reference word that medium-beam1 got wrong, test whether the heard token(s) at that position would map to the correct glossary entry by fuzzy matching (reuse skeleton() and recognisable() from scripts/transcript_accuracy.py, and try at least one more approach such as a phonetic skeleton or edit distance on the consonant sequence). Report: how many currently-wrong Sanskrit words a perfect-choice lexicon pass could recover, and therefore what Sanskrit error rate is achievable. This is the number that decides whether the pass is worth building.

4. MEASURE THE DAMAGE IT WOULD DO. This matters as much as the gain. Run the same matcher over the ENGLISH words that are currently CORRECT, and count how many would be wrongly rewritten into a Sanskrit term ("soul" into a glossary word, say). Report the false-correction rate and give examples. A pass that fixes 200 Sanskrit words and breaks 200 English ones is worthless.

5. FIND THE OPERATING POINT. Sweep your matching threshold and report the trade-off curve: Sanskrit words recovered against English words broken. Recommend a threshold, and state the net effect on the two error rates at that point.

6. ANSWER THIS DIRECTLY: should the steward build the lexicon pass? If yes, say what it would achieve in numbers, where in the pipeline it belongs, and what its main failure mode is. If the evidence says no, say no - a clear negative saves him weeks. Also say whether it should apply only to spans already marked as chanted or non-English, rather than the whole transcript.

Write your script and results to data/reference/analysis/.`,
  },
]

phase('Measure')
log('Measuring four things on the verified reference: correction workload, error signals, timing drift, Sanskrit lexicon headroom')

const measured = await parallel(TASKS.map(task => () =>
  agent(task.prompt, { label: `measure:${task.key}`, phase: 'Measure', schema: MEASURE_SCHEMA })
    .then(result => (result ? { ...result, key: task.key, title: task.title } : null))))

const good = measured.filter(Boolean)
log(`${good.length} of ${TASKS.length} measurements returned; verifying their headline numbers independently`)

phase('Verify')

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    verdict: { type: 'string', description: 'CONFIRMED if every headline number reproduced, DISPUTED if any did not.' },
    checks: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          claim: { type: 'string' },
          reproduced: { type: 'boolean' },
          your_value: { type: 'string' },
          note: { type: 'string' },
        },
        required: ['claim', 'reproduced', 'your_value'],
      },
    },
    method_problems: { type: 'array', items: { type: 'string' }, description: 'Errors of method, not arithmetic: circular reasoning, wrong denominator, a metric that cannot support the conclusion drawn.' },
    unsupported_conclusions: { type: 'array', items: { type: 'string' }, description: 'Conclusions that go further than their own numbers allow.' },
    missed: { type: 'array', items: { type: 'string' }, description: 'Decision-relevant things none of the four measured.' },
  },
  required: ['verdict', 'checks', 'method_problems', 'unsupported_conclusions', 'missed'],
}

const dossier = good.map(r => [
  `### ${r.key} - ${r.title}`,
  `HEADLINE: ${r.headline}`,
  'NUMBERS:',
  ...r.numbers.map(n => `  - ${n.name} = ${n.value}\n      how: ${n.how}`),
  `CONCLUSIONS:\n${r.conclusions.map(c => `  - ${c}`).join('\n')}`,
  `SURPRISES:\n${(r.surprises || []).map(c => `  - ${c}`).join('\n')}`,
  `CAVEATS:\n${r.caveats.map(c => `  - ${c}`).join('\n')}`,
  `FILES: ${r.files_written.join(', ')}`,
].join('\n')).join('\n\n')

const verification = await agent(`${COMMON}
YOUR TASK: adversarially verify four measurements that another four agents just produced on this data. Your job is to REFUTE, not to agree. The steward will spend months of machine time and years of his own correction time on these numbers, and this project already has a history of confident claims that turned out to be wrong: a "78% duplicates" figure that was really filename clustering, a "~70 days" compute estimate resting on an unverified note, a subtitle offset described as high-confidence that was 39 seconds out mid-lecture, and a scoring bug that double-counted insertions until it was caught. Assume something here is wrong too, and find it.

For each measurement below:
1. Read the analysis script it wrote (in data/reference/analysis/) and recompute its headline numbers YOURSELF, independently, from the raw files. Do not re-run their script and call that verification - write your own computation. If you get a different number, report both.
2. Attack the METHOD, not just the arithmetic. Look hard for: a denominator that does not match the claim; circular reasoning (especially in the timing work, where the reference's own cue times came from Whisper); a threshold chosen after seeing the answer; precision/recall computed on a base rate that makes a useless signal look good; an upper bound presented as an achievable result; an average that hides a bimodal distribution.
3. Flag conclusions that outrun their evidence.
4. Say what all four MISSED that the steward needs.

Be specific and quantitative. "CONFIRMED" is only allowed if you personally reproduced every headline number.

${dossier}`, { label: 'verify:all-four', phase: 'Verify', schema: VERDICT_SCHEMA, effort: 'high' })

return { measured: good, verification, failed: TASKS.filter((t, i) => !measured[i]).map(t => t.key) }
