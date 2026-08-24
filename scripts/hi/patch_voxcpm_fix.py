"""
patch_voxcpm_fix.py — consolidated, clean fix for VoxCPM2 LoRA training NaN on 24GB.

Root cause (empirically localized): the NaN is born in the DiT (flow-matching) path, from
(1) PADDED rows fed through the shared per-row DiT estimator (batching variable-length clips)
    -> NaN in the decoder forward -> poisons the masked loss's gradient (0*NaN=NaN); and
(2) a few VALID rows whose fp32 DiT activations overflow in the backward -> grad_norm inf/nan.

Fixes (apply to a CLEAN git checkout of VoxCPM):
  A) memfix        (trainer): cast frozen base to bf16 to fit 24GB, EXCEPT audio_vae + feat_decoder.
  B) fp32-diff     (voxcpm2.py): run the diffusion head + loss in fp32 (autocast disabled).
  C) padfix        (unified_cfm.py): probe the estimator under no_grad, drop padded + non-finite
                   rows from BOTH the estimator call and the loss mask (num and denom).
  D) math-SDPA     (trainer): wrap the training forward in sdpa_kernel([MATH]) — no fused-bf16 NaN.
  E) grad safety   (trainer): zero non-finite grads before clip_grad_norm (belt-and-suspenders;
                   padfix removes the source). Pair with max_grad_norm: 1.0 in the config.

Idempotent. Run in /workspace/VoxCPM:  python /workspace/patch_voxcpm_fix.py
"""
import io

TRN = "scripts/train_voxcpm_finetune.py"
VOX = "src/voxcpm/model/voxcpm2.py"
CFM = "src/voxcpm/modules/locdit/unified_cfm.py"


def patch(path, subs):
    s = io.open(path, encoding="utf-8").read()
    n = 0
    for tag, old, new in subs:
        if tag in s:
            print(f"  [{path}] {tag}: already patched"); continue
        assert old in s, f"ANCHOR NOT FOUND in {path} for {tag}"
        s = s.replace(old, new, 1); n += 1
        print(f"  [{path}] {tag}: patched")
    if n:
        io.open(path, "w", encoding="utf-8").write(s)
    return n


# ---------- A) memfix (trainer) ----------
MEM_old = "    tokenizer = base_model.text_tokenizer\n"
MEM_new = (
    "    tokenizer = base_model.text_tokenizer\n"
    "    import torch as _t   # [memfix] bf16 frozen base to fit 24GB, EXCEPT audio_vae + feat_decoder\n"
    "    _nb = 0\n"
    "    for _n, _p in base_model.named_parameters():\n"
    "        if _p.requires_grad or (\"audio_vae\" in _n) or (\"feat_decoder\" in _n):\n"
    "            continue\n"
    "        _p.data = _p.data.to(_t.bfloat16); _nb += 1\n"
    "    print(f\"[memfix] cast {_nb} frozen base tensors to bf16\", file=sys.stderr)\n"
)

# ---------- D) math-SDPA (trainer training-forward, 20-space indent) ----------
SDPA_old = (
    "                    with accelerator.autocast(dtype=torch.bfloat16):\n"
    "                        outputs = model(\n"
)
SDPA_new = (
    "                    from torch.nn.attention import sdpa_kernel as _sdpak, SDPBackend as _SDPB  # [mathsdpa]\n"
    "                    with accelerator.autocast(dtype=torch.bfloat16), _sdpak([_SDPB.MATH]):\n"
    "                        outputs = model(\n"
)

# ---------- E) grad safety net (trainer) ----------
GRD_old = (
    "            effective_max_norm = max_grad_norm if max_grad_norm > 0 else 1e9\n"
    "            grad_norm = torch.nn.utils.clip_grad_norm_(unwrapped_model.parameters(), max_norm=effective_max_norm)\n"
)
GRD_new = (
    "            for _p in unwrapped_model.parameters():   # [gradguard] zero non-finite grads (padfix removes source)\n"
    "                if _p.grad is not None:\n"
    "                    torch.nan_to_num_(_p.grad, nan=0.0, posinf=0.0, neginf=0.0)\n"
    "            effective_max_norm = max_grad_norm if max_grad_norm > 0 else 1e9\n"
    "            grad_norm = torch.nn.utils.clip_grad_norm_(unwrapped_model.parameters(), max_norm=effective_max_norm)\n"
)

# ---------- B) fp32-diff (voxcpm2.py) ----------
F1_old = (
    "        # Keep diffusion inputs in the same dtype as the model (e.g., bfloat16)\n"
    "        target_dtype = self._dtype()\n"
)
F1_new = (
    "        # [fp32diff] flow-matching loss is numerically unstable in bf16 -> force fp32\n"
    "        target_dtype = torch.float32\n"
)
F2_old = (
    "        diff_loss = self.feat_decoder.compute_loss(\n"
    "            feat_gt.transpose(1, 2).contiguous(),\n"
    "            dit_hidden,\n"
    "            cond=feat_cond.transpose(1, 2).contiguous(),\n"
    "            tgt_mask=loss_seq_mask.transpose(1, 2).contiguous(),\n"
    "            progress=progress,\n"
    "        )\n"
)
F2_new = (
    "        with torch.autocast(device_type=\"cuda\", enabled=False):  # [fp32diff]\n"
    "            diff_loss = self.feat_decoder.compute_loss(\n"
    "                feat_gt.transpose(1, 2).contiguous(),\n"
    "                dit_hidden.float(),\n"
    "                cond=feat_cond.transpose(1, 2).contiguous(),\n"
    "                tgt_mask=loss_seq_mask.transpose(1, 2).contiguous(),\n"
    "                progress=progress,\n"
    "            )\n"
)

# ---------- C) padfix (unified_cfm.py, mean_mode=False branch, 12-space body) ----------
PAD_old = (
    "        else:\n"
    "            u_pred = model_fn(y, r, t)\n"
    "            u_tgt = v\n"
)
PAD_new = (
    "        else:\n"
    "            # [padfix] DiT runs per (b*t) row. Padded rows (mask==0) carry OOD inputs and a few\n"
    "            # valid rows overflow in fp32; one NaN row poisons the shared-weight grad of the\n"
    "            # batched estimator. Probe under no_grad, drop non-finite rows from estimator + mask.\n"
    "            u_tgt = v\n"
    "            if tgt_mask is not None:\n"
    "                _valid = tgt_mask.reshape(tgt_mask.size(0), -1).amax(dim=1) > 0\n"
    "                _idx = _valid.nonzero(as_tuple=True)[0]\n"
    "                if _idx.numel() > 0:\n"
    "                    with torch.no_grad():\n"
    "                        _probe = self.estimator(y[_idx], mu[_idx], t[_idx], cond[_idx], dt=t[_idx] - r[_idx])\n"
    "                    _fin = torch.isfinite(_probe.reshape(_probe.size(0), -1)).all(dim=1)\n"
    "                    _keep = _idx[_fin]\n"
    "                else:\n"
    "                    _keep = _idx\n"
    "                self._padfix_dropped = int(_idx.numel() - _keep.numel())\n"
    "                u_pred = torch.zeros_like(v)\n"
    "                if _keep.numel() > 0:\n"
    "                    _up = self.estimator(y[_keep], mu[_keep], t[_keep], cond[_keep], dt=t[_keep] - r[_keep])\n"
    "                    u_pred = u_pred.index_copy(0, _keep, _up)\n"
    "                _keeprow = torch.zeros(v.size(0), dtype=torch.bool, device=v.device)\n"
    "                if _keep.numel() > 0:\n"
    "                    _keeprow[_keep] = True\n"
    "                tgt_mask = tgt_mask * _keeprow.view(-1, 1, 1)\n"
    "            else:\n"
    "                u_pred = model_fn(y, r, t)\n"
)

na = patch(TRN, [("[memfix]", MEM_old, MEM_new),
                 ("[mathsdpa]", SDPA_old, SDPA_new),
                 ("[gradguard]", GRD_old, GRD_new)])
nb = patch(VOX, [("[fp32diff]", F1_old, F1_new)])
nb += patch(VOX, [("with torch.autocast(device_type=\"cuda\", enabled=False):  # [fp32diff]", F2_old, F2_new)])
nc = patch(CFM, [("[padfix]", PAD_old, PAD_new)])
print(f"done. trainer={na}, voxcpm2={nb}, unified_cfm={nc}")
