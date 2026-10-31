# Note for review-assistance: version 2 packages and carrying answers over (2026-10-31)

**For:** the `review-assistance` session. Written from `lecture-archive`, which changed nothing
in `review-assistance`. Your `contracts/review.pin.json` is the record of what the app
understands; this note is not.

## What to do

1. **Re-pin `contracts/review/` at `6b7e87f`.** It is on branch `every-agreed-piece` in
   `../lecture-archive` (merged into `main` and pushed later the same day, unchanged):
   `git -C ../lecture-archive -c core.autocrlf=false archive 6b7e87f contracts/review`.
   Since your pin `d95d285` four files changed: `README.md`, `examples/index.json` and two new
   examples. **No schema changed**, and the format stays 1.0.
2. **Your tests will then fail on the two new examples, by design** (step 2 of the change order
   under "Versioning"). Make them pass:
   - `valid/package-bg-3-37-brisbane-v2.json`: version 2 of the example package. It must pass
     the schema, P1–P10 and P11.
   - `invalid/package-v2-changes-an-earlier-stop.json`: it must fail **P11 only**. It asks
     stop #0088 in different words (`we'll` became `will`) under the same id.
   - Both index entries carry a new key, **`previous`**: the earlier version that P11 is
     checked against.
3. **Implement P11** (README, "A later version of a package"). Our Python is
   `republish_rules(previous, current)` in `lecture-archive/scripts/review_contract.py`. It
   requires:
   - the same lecture id, and the version one higher;
   - every previous stop present and deep-equal under its id;
   - every new stop's serial higher than every previous serial;
   - a transcript of the same length, with every word identical except `stop`, which may only
     go from null to an id.

   P11 does not yet allow dropping a stop or shifting its times.
4. **Load version 2 packages** from `packages/<lecture>/v2.json`. Stop ids are **no longer in
   timeline order**, because new serials come after v1's highest. The `stops` array still is.
   Never infer order or position from a serial.
5. **Carry answers over by stop id** (agreed 29 October 2026):
   - A v2 stop whose id was in v1 keeps its v1 records, and the reviewer is not asked again.
     New stops start open.
   - A carried-over record still names v1 (package id, version and SHA-256), so A1 and A8 are
     checked against v1. It is older than v2's `published_at`.
   - The accepted list for v2 names v2 (C1), lists every v2 stop in v2's order (C2), and may
     name a v1 record for a kept stop (C3).
6. **Update `docs/data-from-lecture-archive.md`.** Lines 55 and 69 send readers to the pinned
   README for the published hashes and for "How lecture-archive builds a package". Both moved
   on 31 October to `lecture-archive`'s `docs/review-packages.md`, which you do not pin.
7. **Tell Mukul when it has shipped.** `lecture-archive` uploads a v2 only when both hold:
   - your `review.pin.json` names `6b7e87f` or a later commit (`review_publish --version 2`
     checks this itself and refuses otherwise);
   - Mukul confirms that v2 loading and carry-over have shipped.

## What is coming

- **Five v2 packages**, for the five published lectures. They keep all 2,558 v1 stops and add
  2,956 agreement stops, 24% of them a single word.
- **Two new v1 packages**: the arrival class (840 stops, 427 of them agreement) and Cc. Ādi
  4.256 (948 stops, 379 agreement). They need no app change and go up when Mukul says.
- **Agreement stops now come one for every agreed piece, with no 3-second rule.** A piece can
  sit beside another stop, and its clip may overlap that stop's. Its context words stop at the
  first word of a disagreement or verse check. Inside a span, a single-text stop is then almost
  always agreed text, and reviewers may learn to confirm it too easily. That is the new known
  limit under "Keeping the order blind", and it is not measured.

Nothing changes in the answers, accepted-list or results formats.
