"""
patch_fp32diff.py — make VoxCPM2 LoRA training numerically stable on a 24GB card.

Root cause of the NaN diffusion loss: VoxCPM2 computes its flow-matching (CFM) loss in
bf16 (config.dtype=bf16 -> self._dtype()=bf16, and the trainer wraps the forward in
autocast(bf16)). The CFM loss uses a jvp through the DiT's attention + an MSE, both of
which overflow to NaN in bf16 -> loss/diff = nan from step 0 -> grad_norm nan -> dead run.

Fix (surgical, memory-safe):
  A) voxcpm2.py forward: force the diffusion inputs + loss to fp32 and disable autocast
     around feat_decoder.compute_loss. The DiT (feat_dim=64) is tiny, so fp32 here is cheap.
  B) trainer memfix: keep feat_decoder params in fp32 (exclude from the bf16 cast) so the
     fp32 inputs match fp32 weights inside the autocast-disabled block. The 2B LM stays bf16.

Idempotent. Run inside /workspace/VoxCPM.
  python /workspace/patch_fp32diff.py
"""
import io, sys

VOX = "src/voxcpm/model/voxcpm2.py"
TRN = "scripts/train_voxcpm_finetune.py"


def patch(path, subs):
    s = io.open(path, encoding="utf-8").read()
    changed = 0
    for tag, old, new in subs:
        if new.split("\n")[0].strip() in s:   # per-edit marker (NOT the shared tag)
            print(f"  [{path}] {tag}: already patched")
            continue
        assert old in s, f"ANCHOR NOT FOUND in {path} for {tag}:\n{old!r}"
        s = s.replace(old, new, 1)
        changed += 1
        print(f"  [{path}] {tag}: patched")
    if changed:
        io.open(path, "w", encoding="utf-8").write(s)
    return changed


# ---- A) voxcpm2.py: fp32 diffusion loss ----
A1_old = (
    "        # Keep diffusion inputs in the same dtype as the model (e.g., bfloat16)\n"
    "        target_dtype = self._dtype()\n"
)
A1_new = (
    "        # [fp32diff] flow-matching loss is numerically unstable in bf16 -> force fp32\n"
    "        target_dtype = torch.float32\n"
)

A2_old = (
    "        diff_loss = self.feat_decoder.compute_loss(\n"
    "            feat_gt.transpose(1, 2).contiguous(),\n"
    "            dit_hidden,\n"
    "            cond=feat_cond.transpose(1, 2).contiguous(),\n"
    "            tgt_mask=loss_seq_mask.transpose(1, 2).contiguous(),\n"
    "            progress=progress,\n"
    "        )\n"
)
A2_new = (
    "        with torch.autocast(device_type=\"cuda\", enabled=False):  # [fp32diff]\n"
    "            diff_loss = self.feat_decoder.compute_loss(\n"
    "                feat_gt.transpose(1, 2).contiguous(),\n"
    "                dit_hidden.float(),\n"
    "                cond=feat_cond.transpose(1, 2).contiguous(),\n"
    "                tgt_mask=loss_seq_mask.transpose(1, 2).contiguous(),\n"
    "                progress=progress,\n"
    "            )\n"
)

# ---- B) trainer memfix: keep feat_decoder fp32 ----
B_old = "        if _p.requires_grad or (\"audio_vae\" in _n):\n"
B_new = "        if _p.requires_grad or (\"audio_vae\" in _n) or (\"feat_decoder\" in _n):\n"

na = patch(VOX, [("[fp32diff]", A1_old, A1_new), ("[fp32diff]", A2_old, A2_new)])
nb = patch(TRN, [("feat_decoder\" in _n", B_old, B_new)])
print(f"done. voxcpm2 changes={na}, trainer changes={nb}")
