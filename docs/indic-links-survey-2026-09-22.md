# The steward's Indic links, read and judged (2026-09-22)

The steward collected 34 links while researching Indian-language models: translation,
language models, Sanskrit models, speech recognition and speech synthesis. Two of them are
the same Qwen3 paper, so 33 distinct items. Each was read at its source by one of five
themed readers and judged against the three projects: SSGGSM lecture transcription, the
Odia transcription and translation seva, and narrator-voice. A verifier then re-checked
every licence, every "supports Sanskrit/Odia" claim and every "runs on this laptop" claim.

Source: workflow run `wf_b39c2eed-460` (script `.agents/workflows/indic-links-survey.js`).
Full result with a source URL for every fact:
`data/research/indic-links-2026-09/workflow-result-wf_b39c2eed-460.json`. Each reader's
notes are in the same directory.

**Every accuracy figure below is the authors' own** unless marked otherwise. No link
reports results on archival cassette audio or on chanting inside a lecture. Every laptop
speed is an estimate; none was measured on this Ryzen 5 5625U.

## Summary

- **One real find for the transcription project: Prabhupadavani** (arXiv 2201.11391). It
  is 94 hours of English devotional lectures, mostly Srila Prabhupada's, with the
  code-mixed Sanskrit (8.6% of tokens) and Bengali (7.8%) **romanised with diacritics and
  counted per language**. That is exactly the trilingual code-switching the steward
  identified as the main source of errors. It can serve as a second, independent benchmark
  where Bengali is already marked. It cannot be used for training without permission: the
  audio is the Bhaktivedanta Book Trust's, supplied through Vanipedia.
- **For the Odia seva: IndicTrans2** (MIT) translates Odia to English with strong published
  scores. Its distilled 200M model is small enough for the laptop. **Indic-Transcribe-core**
  has the best self-reported Odia recognition score. Both are worth one small test.
- **For the trilingual hypothesis: Indic-Transcribe-flex** is the one open recogniser trained
  on Indian English, Sanskrit and Bengali together, with a mixed-script output mode. No
  accuracy has been published for its English or Sanskrit.
- **For narrator-voice: nothing new.** Indic Parler-TTS and Indic-Speak are already in its
  research. Neither officially supports emotion control in Odia.
- **Not useful:** the language models (Sarvam, Param-1, Qwen3 and the Sanskrit Qwen3
  fine-tune), the encoders and tokenizer, GitaWhisper, and four miscellaneous pages. The
  reasons are in the table. The common pattern: **deterministic tools beat language models
  for the Sanskrit tasks**. Retrieve the verse the catalogue names, align it to the audio,
  and transliterate with rules.

## For SSGGSM transcription

### Prabhupadavani — try soon, as a benchmark

[Prabhupadavani: a code-mixed speech translation dataset for 25 languages](https://ar5iv.labs.arxiv.org/html/2201.11391)
(IIT Kanpur, IIT Kharagpur, UPenn, IIT Mandi; COLING 2022 workshop). Repository:
[frozentoad9/CMST](https://github.com/frozentoad9/CMST).

- **What it is:** 94 hours of aligned lecture speech from 130+ speakers, with Srila
  Prabhupada dominant. The source transcription is English (83.6% of tokens) with
  Sanskrit (8.56%; 51,246 tokens, 7,202 distinct) and Bengali (7.84%), **romanised with
  diacritics**, plus translations into 25 languages.
- **Why it matters here:** it is the only public speech set in this domain. It shows the
  same pattern as Gurudeva's lectures: English exposition with Sanskrit and Bengali
  quotations. It answers two open problems at once:
  - **A second reference.** Every calibration so far rests on one lecture.
  - **Bengali already marked.** Our reference does not mark Bengali, so trilingual models
    cannot yet be scored fairly on it.
- **Licence:** the repository is Apache-2.0, but it says the audio is "provided by
  Vanipedia courtesy Bhaktivedanta Book Trust". **Using it as a private test set is one
  thing. Training a model on it, or publishing anything derived from it, needs BBT's
  permission.**
- **Next step:** download the test split, run the current baseline (Whisper medium, skip
  rule off), and score the Sanskrit and Bengali spans separately. This tests the
  code-switching hypothesis on a second corpus without touching the Melbourne reference.
- Caution: it is a different speaker and a different recording chain. It complements the
  Melbourne reference; it does not replace it.

### Indic-Transcribe-flex — keep in mind, for the trilingual test

[bodhan-ai/indic-transcribe-flex](https://huggingface.co/bodhan-ai/indic-transcribe-flex)
(Bodhan AI with AI4Bharat, 2026).

- A 1.2B fine-tune of NVIDIA Canary-1B-v2. It covers Indian English, Sanskrit, Odia and
  Bengali, and has a **mixed-script mode**. Its sibling *core* writes every language in its
  own script.
- **Published numbers:** Odia 10.2, Bengali 5.0, Hindi 4.1 (telephone speech). **None for
  English or Sanskrit.**
- **Limits:**
  - It refuses audio longer than 45 s, so it needs chunking.
  - Its romanised mode is typing-style, not IAST.
  - It has no word timestamps, so words would need forced alignment.
  - Its 4.6 GB fp32 checkpoint makes a rented GPU the realistic route.
- **Licence:** Indic Open Model License v1.0 (5 Sep 2026). Running it and publishing its
  transcripts is permitted. Its share-alike terms apply only to redistributing or hosting
  the model.
- It is the natural open candidate for testing the trilingual hypothesis, beside Whisper
  in multilingual mode and the commercial code-switching services.

### Su-śrotā — keep the dataset in mind; still not the model

[prathoshap/sushrota-sanskrit-asr](https://huggingface.co/prathoshap/sushrota-sanskrit-asr).

- The **model is still unlicensed**, so its output must not be published.
- **What is new:** its training data is now published under CC-BY-4.0
  ([sushrota-sanskrit-asr-data](https://huggingface.co/datasets/prathoshap/sushrota-sanskrit-asr-data)):
  17.4 h of Sanskrit with Devanagari transcripts.
- The verifier corrected the reader on two points:
  - **It is read Sanskrit, not chant.** The 327-clip test split is phone and room
    recordings of people reading known text. The 21 scholars *read* Bhāgavatam, Upaniṣad
    and stotra texts, and those clips sit in the training split.
  - The licence of a 7.6-hour recitation portion is unverified.
- Useful later as Sanskrit fine-tuning data, or as a test for other Sanskrit recognisers.
  It is not a benchmark for chanted verse.

### Not useful for transcription, and why

- **GitaWhisper-tiny:** Whisper-tiny fine-tuned on Gītā recitation, 92% WER on its own
  clean 30-verse test, Gītā only. The verse bank plus alignment covers more.
- **dhee-nxtgen-qwen3-sanskrit-v2:** a 1.7B chat fine-tune of Qwen3. It publishes no
  training data and no evaluation, and its tokenizer is identical to Qwen3's. **Sanskrit is
  not among Qwen3's 119 languages.** A language model confidently "restoring" a verse
  wrongly is worse than leaving it garbled.
- **Transliteration: use `indic_transliteration` (MIT).** The romanisations in the
  AI4Bharat and Google resources (IndicXlit, Aksharantar, Dakshina) are typing-style, not
  IAST. Aksharamukha (used by XLMIndic) is AGPL.

## For the Odia seva

- **IndicTrans2** ([AI4Bharat](https://github.com/AI4Bharat/IndicTrans2)): try soon.
  - **Coverage:** Odia to English exists, as do Sanskrit and Bengali to English. Code and
    checkpoints are MIT; the Hugging Face repositories have an automatic click-through
    gate.
  - **Published quality:** Odia to English chrF++ **66.2** (IN22-Gen), against Google's
    64.6. The distilled 200M model loses very little (65.8). English to Odia is weaker
    (43.9). Its training data includes Vanipedia devotional text.
  - **On this laptop:** the 200M model fits easily. But its preprocessing toolkit has no
    Windows build, so plan on WSL or a RunPod pod.
  - **Caution:** it accepts Sanskrit only in Devanagari. Sanskrit quoted inside Odia text,
    in Odia script, will be translated as Odia. Pull verses out and use their canonical
    translations.
  - **Test:** translate 20–30 sentences that already have a human translation. Score
    chrF++ against it, and have the translator time post-editing against translating from
    scratch.
- **Indic-Transcribe-core**: try soon. Self-reported Odia OIWER **8.7**, the best of any
  open model, on AI4Bharat's closed telephone benchmark. Test one 5–10-minute Odia clip on
  a rented GPU against the current Sarvam or Azure transcript. It gives no word timestamps,
  and it writes English words in Odia script.
- **Sarvam-30B GGUF** (Apache-2.0): keep in mind. It is the only permissively licensed
  language model here that claims Odia, and it is worth a test only if IndicTrans2
  disappoints. It is too large for the laptop at usable quality.
- An independent paper in the list (IndicKLAR, arXiv 2605.29637) finds **Odia the weakest
  of 18 Indian languages for open 1–14B language models**. Tools built for Indian
  languages matter more than general models here.

## For narrator-voice

- **Indic Parler-TTS** (Apache-2.0): two Odia voices (Manas, Debjani), trained on about
  19 h. **Emotion prompts are not officially supported for Odia.** It is a free, calm
  baseline, already covered in narrator-voice's research.
- **Indic-Speak** (Indic Open Model License plus Llama 3.2 terms): production-tier Odia
  voices (Akash, Itishree). Its authors call style control unreliable, and it needs a GPU.
  **Training our own Odia TTS on its audio would bring its licence along.** Already in
  narrator-voice's notes.
- Neither changes the decision to train an Odia emotional TTS.

## Licence traps worth remembering

- **BharatGen changed licences.** The two commit links show Param-1-2.9B-Instruct moving
  from MIT to the BharatGen Research License. That licence is non-commercial and requires
  written approval to publish outputs. The card's text still says MIT.
- **Sarvam-1's research licence** limits use of its *outputs* to non-commercial research.
- **"MIT" on a Gemma-derived model** (IndicBERT-v3) probably does not remove Gemma's terms
  (the reader's reading, not legal advice).
- **Paramanu** weights are CC-BY-NC-SA.

## Every link

Verdicts are the verifier's. "Sa / Or / Bn" = Sanskrit, Odia, Bengali support.

| link | what it is | licence | Sa / Or / Bn | verdict |
|---|---|---|---|---|
| [IndicTrans2](https://github.com/AI4Bharat/IndicTrans2?tab=readme-ov-file) | Translation, 22 Indian languages ↔ English | MIT (auto-gated) | yes / yes / yes | **try soon** (Odia seva) |
| [Prabhupadavani](https://ar5iv.labs.arxiv.org/html/2201.11391) | 94 h code-mixed lecture speech dataset | Apache-2.0 repo; audio BBT/Vanipedia | yes / no / yes | **try soon** (SSGGSM benchmark) |
| [indic-transcribe-core](https://huggingface.co/bodhan-ai/indic-transcribe-core) | ASR, native-script output | Indic Open Model License | yes / yes / yes | **try soon** (Odia seva) |
| [indic-transcribe-flex](https://huggingface.co/bodhan-ai/indic-transcribe-flex) | ASR, mixed-script mode | Indic Open Model License | yes / yes / yes | keep in mind (trilingual test) |
| [sushrota-sanskrit-asr](https://huggingface.co/prathoshap/sushrota-sanskrit-asr) | Sanskrit ASR; CC-BY dataset now published | model unlicensed; data CC-BY-4.0 | yes / no / no | keep in mind (dataset) |
| [sarvam-30b-gguf](https://huggingface.co/sarvamai/sarvam-30b-gguf/blob/main/README.md) | 30B mixture-of-experts language model | Apache-2.0 | claimed / yes / yes | keep in mind (Odia seva fallback) |
| [indic-parler-tts](https://huggingface.co/ai4bharat/indic-parler-tts) | TTS, 2 Odia voices | Apache-2.0 (auto-gated) | yes / yes / yes | keep in mind (already in narrator-voice) |
| [indic-speak](https://huggingface.co/bodhan-ai/indic-speak) | TTS, Llama-3.2-3B based | Indic Open Model License + Llama | yes / yes / yes | keep in mind (already in narrator-voice) |
| [indicnlp_catalog](https://github.com/AI4Bharat/indicnlp_catalog) | Catalogue of Indic NLP resources | none on the repo | — | keep in mind (stale since Dec 2024) |
| [Qwen3 repository](https://github.com/QwenLM/Qwen3) | Qwen3 language models | Apache-2.0 | **no** / yes / yes | keep in mind at most |
| [Qwen3 report](https://arxiv.org/abs/2505.09388) and [v1](https://arxiv.org/abs/2505.09388v1) | Technical report (the same paper twice) | arXiv | no / — / — | keep in mind / duplicate |
| [Qwen3 blog](https://qwen.ai/blog?id=qwen3) | Release blog with the 119-language list | — | no / yes / yes | keep in mind |
| [Transformers Qwen3 docs](https://huggingface.co/docs/transformers/main/model_doc/qwen3) | Library documentation | — | — | not relevant |
| [dhee-nxtgen-qwen3-sanskrit-v2](https://huggingface.co/dheeyantra/dhee-nxtgen-qwen3-sanskrit-v2) | Sanskrit chat fine-tune of Qwen3-1.7B | Apache-2.0 | claimed / no / no | not relevant |
| [GitaWhisper-tiny](https://huggingface.co/diabolic6045/GitaWhisper-tiny) | Whisper-tiny on Gītā recitation | contradictory | Gītā only / no / no | not relevant |
| [IndicBERT-v3-1B](https://huggingface.co/ai4bharat/IndicBERT-v3-1B/blob/main/README.md) | Encoder from Gemma-3-1B, no scores | MIT label; Gemma terms | yes / yes / yes | not relevant |
| [IndicBERT page](https://ai4bharat.iitm.ac.in//indic-bert/) | Project page, **404**; old IndicBERT v1 | MIT | no / yes / yes | not relevant |
| [xlmindic-base-uniscript](https://huggingface.co/ibraheemmoosa/xlmindic-base-uniscript) | 11M encoder on romanised text | Apache-2.0 (needs AGPL Aksharamukha) | yes / yes / yes | not relevant |
| [Ansh-256k](https://huggingface.co/LingoIITGN/Ansh-256k) | A tokenizer, not a model | Apache-2.0 | yes / yes / yes | not relevant |
| [MuRIL](https://www.alphaxiv.org/abs/2103.10730) | 2021 encoder (Google) | Apache-2.0 | pretraining only | not relevant |
| [sarvam-1](https://huggingface.co/sarvamai/sarvam-1) | 2B base language model | Sarvam research licence (restricts outputs) | no / yes / yes | not relevant |
| [sarvam-30b-bf16](https://huggingface.co/abhinand/sarvam-30b-bf16) | Community repack of Sarvam-30B | Apache-2.0 | as Sarvam-30B | not relevant (duplicate) |
| [Param-1-7B](https://huggingface.co/bharatgenai/Param-1-7B) | 7B base mixture-of-experts | BharatGen Research License | yes / yes / yes | not relevant |
| [Param-1-2.9B-Instruct](https://huggingface.co/bharatgenai/Param-1-2.9B-Instruct) | English–Hindi instruct model | inconsistent (MIT → BRL) | no / no / no | not relevant |
| [commit a8437f0](https://huggingface.co/bharatgenai/Param-1-2.9B-Instruct/commit/a8437f02110718107987d30ef975ca5ae326673a) | The licence change, MIT → BharatGen Research License | — | — | licence evidence |
| [commit 7bfec15](https://huggingface.co/bharatgenai/Param-1-2.9B-Instruct/commit/7bfec15ee177b038e5309c672af819b8c21dc156) | The original release | — | — | not relevant |
| [AIKosh listing](https://aikosh.indiaai.gov.in/home/models/details/bharatgen_param_1_indic_scale_bilingual_foundation_model.html) | Government listing for Param-1 (currently unavailable) | MIT in metadata | no / no / no | not relevant |
| [AIbase page](https://model.aibase.com/models/details/1959857280912723968) | Stale third-party mirror of the Param-1 card | — | no / no / no | not relevant |
| [Zenodo 17341822](https://zenodo.org/records/17341822) | Self-published "IndicGPT" report, nothing released, a fabricated citation | CC-BY-4.0 (text) | — | not relevant |
| [IndicKLAR](https://arxiv.org/html/2605.29637) | Paper: LLM knowledge consistency across Indian languages | CC-BY-4.0 data, MIT code | yes / yes / yes | not relevant as a tool; Odia is weakest for open LLMs |
| [Nitinmall](https://github.com/Nitinmall-1390/Nitinmall) | A student's hobby voice assistant wrapping cloud APIs | no licence granted | overstated | not relevant |
| [Paramanu v2](https://arxiv.org/pdf/2401.18034v2) | Small Indian language models (superseded version) | CC-BY-NC-SA | yes / yes / yes | not relevant |
