# Expressive-narration experiment — pre-registered predictions (2026-07-09)

Companion to [prosody-dubbing-research-2026-07-08.md](prosody-dubbing-research-2026-07-08.md),
[voxcpm2-markup-research-2026-07-08.md](voxcpm2-markup-research-2026-07-08.md).

## The plan being tested

Sequence the problem: **(1) author the _ideal target_ Hindi narration script** (delivery embedded in the text —
beats, pauses, dialogue, question framing) → **(2) render it** and see how close we get. This _separates_ a
cheap iterable text problem from the hard model problem, and turns it into a **decisive experiment**: if a
_well-authored_ script still renders flat/wrong, the ceiling is real (need explicit control or LoRA); if it
sings, the text-centric bottleneck was less binding than feared and authoring carries us far.

## The hypothesis

> Can a well-authored Hindi script, rendered **zero-shot** on VoxCPM2 in his voice, produce **content-appropriate
> expressive** narration — or is **explicit control / a LoRA** required to get past "flat"?

This is the "implicit prosody control" lever (steer delivery through _how the text is written_) pushed to its
limit. It works _only if_ the model (a) honors the authored cues in Hindi and (b) understands the Hindi well
enough to perform it. Both are unverified.

## Why it can partially fail (Shukla's text-centric bottleneck)

Authoring is the _right response_ to the bottleneck — instead of recovering lost delivery, we re-inject cues
into the text. But two parts still bite: **(i)** text has a hard prosodic ceiling (encodes pauses + general
expressiveness, NOT fine pitch/emphasis-strength/idiosyncratic melody), and **(ii)** implicit control only
works if the model _understands_ the text — and VoxCPM2's Hindi comprehension is weak (CN/EN-trained, Hindi OOD,
issue #288). So we predict: authoring can move "flat → generically expressive," but not all the way to "_his_
delivery," and the Hindi-comprehension weakness may block even the generic gains.

## Pre-registered predictions

Written BEFORE testing. Three layers: **P1–P4 mechanical** (does VoxCPM2 render authored cues in Hindi at all),
**P5–P6 ceiling** (script gets generic-expressive, not _his_), **P7 self-inflicted** (rewriting distorts meaning).

| #      | Prediction (what fails)                                                     | Mechanism (why)                                                     | Test                                                                                               | Confirmed if…                                                               |
| ------ | --------------------------------------------------------------------------- | ------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| **P1** | Authored `…`/`,`/`।` pauses **don't land where written** in Hindi           | Hindi pause-behavior unverified in VoxCPM2                          | `markup_test.py` B1/B2/B3                                                                          | pauses appear in wrong places / not at all                                  |
| **P2** | `समझे?` renders as a **pause, not a rising question**                       | `?` documented as pause, not intonation; Hindi unverified           | markup_test A1 vs A2                                                                               | no audible pitch rise on the question                                       |
| **P3** | A word _written_ to be stressed **stays flat**                              | VoxCPM2 has **no** per-word emphasis knob                           | markup_test C1/C2, D1/D2                                                                           | emphasis appears only when text is _dramatized_, not merely "important"     |
| **P4** | Model **under-performs the script because it doesn't understand the Hindi** | weak Hindi in LM backbone                                           | render a rich authored passage; compare expressiveness to the same idea in English                 | Hindi reading flatter than English of same content ← _bet this fails first_ |
| **P5** | Narration sounds **expressively read but not like HIM**                     | speaker-specific delivery is a separate axis (LoRA), not authorable | blind A/B to someone who knows his Hindi lectures                                                  | judged "good reader," not "that's how _he'd_ say it"                        |
| **P6** | Emphasis lands on **generic** points, not _his_ points                      | LLM/model stresses text-meaning, not his rhetorical priorities      | mark where _he_ stresses in a parallel clip; check Hindi stresses the same _ideas_                 | mismatch in which ideas are emphasized                                      |
| **P7** | "Re-arrange completely" **drifts from what he actually said**               | performability traded against fidelity                              | back-translate the authored script → check semantic/theological faithfulness + native-speaker read | meaning shifted from the source                                             |

## Test assets

- **`markup_test.py`** (built, in scratchpad) — isolates one variable per pair (A=question, B=pauses, C=`!`
  emphasis, D=flat-vs-annotated), ref 0008. Directly answers **P1–P4**. _Cheapest first test._
- **F0 measurement** (parselmouth/Praat, local CPU) on his English + Hindi clips — grounds **P6** in his real
  data instead of typology (see the "measure, don't cite" note in the prosody-dubbing doc).
- **Native-speaker judgment** of the _script itself_ (before TTS) — **P7** + whether the LLM Hindi is idiomatic.
- **Blind A/B** "is this him?" — **P5**.

## Decision rules (what each outcome implies — decided in advance)

- **P1–P4 mostly fail** → authoring has _no mechanical grip_ in VoxCPM2-Hindi → don't invest in a full authored
  script for this model; switch renderer (probe IndicF5 / Higgs v3) or go explicit-control.
- **P1–P4 mostly hold, P5 fails** → authoring works but caps at generic-expressive → **LoRA becomes the lever**
  for _his_ cadence (mixed-corpus, per the data-efficiency finding).
- **P1–P4 hold AND P5 acceptable** → **zero-shot + authoring is enough**; LoRA is optional polish. (Best case.)
- **P4 fails specifically** → VoxCPM2's Hindi is the blocker regardless of authoring → renderer swap, not more text work.

## Does LoRA _surely_ required, or will zero-shot work? — resolved by this experiment

Not guessed — **derived from P4 + P5**:

- Zero-shot _reliably_ gives **timbre/identity** (diary hit ~0.87 ECAPA) and, _if P1–P4 hold_, content-appropriate
  expressiveness.
- Zero-shot _cannot_ give **speaker-specific prosody** — it renders the reference clip's prosody + the model's
  inferred prosody. We already tested reference-selection (expressive refs 0004/0107) → "variance, not his
  cadence" → evidence the zero-shot prosody channel is limited.
- **So:** LoRA is _required_ only if P5 fails hard (clearly not him) or P4 fails (Hindi unperformed). If authored
  zero-shot reaches "acceptable + expressive," LoRA is optional. Caveat: LoRA is not a guaranteed fix either —
  14.5 min may be too little for _prosody_ (vs timbre), and it needs mixed-corpus.

## Results (2026-07-10, judged by ear on 14 takes, ref 0008)

| # | Verdict | What he heard |
|---|---|---|
| **P1** pauses land | **HELD** (works) | `…` pauses landed where written — but expected more pitch movement around them |
| **P2** question rise | **HELD** (works) ⚠️ *my prediction was wrong* | **समझे?** *does* read as a question in Hindi (I'd predicted it'd only pause) — but the pitch swing isn't quite his |
| **P3** word emphasis | **CONFIRMED failed** | the **जान बचा ली ×3** repetition stayed flat — no emphasis |
| **P4** expressive / understood | **outcome CONFIRMED, mechanism REFUTED** | words pronounced **nicely** (so Hindi comprehension is FINE — my "weak Hindi" mechanism was WRONG); the real gap is **pitch swing** + **pause LENGTH** — he wants dramatic elongation like *"अरेeee……"* |
| **P5** sounds like him | **PARTIAL** | identity/timbre = him, and the *calm* delivery even resembles his calm self — but **not suitable for these expressive Hindi clips** |
| **P6** his emphasis points | **CONFIRMED failed** | zero-shot *attempted* pitch variation but it didn't land as meaningful emphasis |
| **P7** rewrite drift | **HELD** (no real drift) | script fidelity fine; his own expectation was "a little unrealistic" from pure authoring |

**Per-take:** pace is inconsistent and seed-dependent — `1_setup__s42` too *fast* ("like reading a book, a boring mood he never had"), `s7/s123` too *slow*. Punctuation *does* modulate delivery: `अरे,` vs `अरे!` vs `ओह!` sound distinct. **Best take: `2_action__s123`** ("अरे! was very good"). Takes mostly differ only slightly seed-to-seed.

### What the experiment settled
- **Authoring WORKS for static structure:** pause *placement* (P1) and question intonation (P2) render — P2 was a positive surprise (better than predicted for Hindi).
- **Authoring CANNOT reach the dynamics:** pitch **swing**, word **emphasis** (P3), pause **length/drama**, and his **cadence** (P4/P6) — these are the "flat" complaint, precisely characterized.
- **Key refutation:** the flatness is **NOT** weak Hindi comprehension (words are pronounced well) and **NOT** an identity problem (P5 timbre holds). → So a **renderer swap (IndicF5/Higgs) is NOT motivated** by this result; VoxCPM2's Hindi + identity are fine. The missing piece is **his expressive dynamics**.
- **Therefore the lever is speaker-specific prosody = a LoRA on his Hindi delivery** (learn his swing + dramatic pauses/cadence), **plus** two cheap authoring tricks we haven't tried: (a) force **longer pauses** by splitting into shorter sentences / stacking `…`, `—`; (b) test **vowel elongation** in text (*अरेeee* / *अरे……े*) for his dramatic holds.

### Decision-tree outcome
Not "P1–P4 mostly fail → swap renderer" and not "all hold → done." We're on the **middle branch, sharpened**: base (Hindi + identity) is good, authoring covers pauses/questions, **but the expressive dynamics need a LoRA on his Hindi** — the flatness is *his-cadence*, not comprehension. Authoring tweaks (pause-length, elongation) are a cheap parallel lever to squeeze before/with the LoRA.

## Test material

Structural target (his actual delivery, per the user):

> "यह देवदासी" [pause] "का प्रसंग" [pause] "जो गीत-गोविंद गा रही थी" "समझे?"

### Authored stimulus v1 (user-marked, 2026-07-09) — THIS is what we render

User authored the full markup themselves (rejecting isolated markup_test in favor of rendering the real script,
which tests P1–P5 together). Two fixes applied: restored dropped `जान` in the 3rd repetition; romanized `samjhe?`
→ Devanagari `समझे?`. At render: map `...`/`....` → `…`, `normalize=False`, ref 0008, cfg 2.0, timesteps 10.

> यह देवदासी… का प्रसंग… जो गीत-गोविंद गा रही थी… समझे आप? जयदेव गोस्वामी द्वारा विरचित गीत-गोविंद… यह प्रसंग… तो
> महाप्रभु… महाप्रभु के हृदय में भाव जागृत हो गया… क्योंकि वे भगवान कृष्ण की स्तुति कर रही थी। तो महाप्रभु… उन्माद
> में आ गए। वे उसकी ओर दौड़े… "अरे, कोई गोपी गा रही है"। तो, महाप्रभु में गोपी-भाव जागृत हो गया, और वो उसकी ओर
> दौड़े। गोविंद ने उन्हें रोकते हुए कहा, "अरे! देवदासी गा रही है, एक स्त्री गा रही है…"। ओह! महाप्रभु रुक गए।
> महाप्रभु बोले… "गोविंद, तुमने मेरी जान बचा ली। अगर मैं उसे छू लेता, तो मैं मर जाता। तुमने आज मेरी जान बचा ली।
> संन्यासी होकर अगर मैं किसी स्त्री को छूता तो मैं मर जाता। तुमने आज मेरी जान बचा ली। बहुत-बहुत धन्यवाद।" ये है
> महाप्रभु की शिक्षा… हमें पालन करना है जो महाप्रभु ने हमें सिखाया है।

Note: rendering the real script tests P1–P4 _in combination_, not in isolation — if output is wrong we lose
per-cue attribution and fall back to markup_test to diagnose. P5/P6/P7 judged on this same render.

Full translated script (Claude one-shot — the pre-edit baseline, kept for the P7 fidelity comparison):

> क्या आप देवदासी वाला यह प्रसंग समझते हैं, जो गीत-गोविंद गा रही थी? गीत-गोविंद जयदेव गोस्वामी की रचना है। यह
> प्रसंग... तो महाप्रभु के हृदय में भाव जागृत हुआ, क्योंकि यह भगवान कृष्ण की स्तुति है। तो महाप्रभु उन्मत्त हो गए।
> वे उसकी ओर दौड़े, "अरे! कोई गोपी गा रही है"। इस तरह उनमें गोपी-भाव जागृत हो गया था, और वे उसकी ओर दौड़ रहे थे।
> गोविंद ने उन्हें रोकते हुए कहा, "अरे! देवदासी गा रही है, एक स्त्री गा रही है"। "अरे!" महाप्रभु रुक गए। महाप्रभु
> कहते हैं, "गोविंद, तुमने मेरी जान बचाई। अगर मैंने उसे छू लिया होता, तो मैं मर जाता। तुमने आज मेरी जान बचाई।
> संन्यासी होकर मैं किसी स्त्री को छूता? मैं मर जाता। तुमने आज मेरी जान बचाई। बहुत-बहुत धन्यवाद।" यही महाप्रभु की
> शिक्षा है जिसका हमें पालन करना चाहिए, जो महाप्रभु ने सिखाया है।
