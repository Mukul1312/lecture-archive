"""patch_dbg_chk.py — inject finiteness checks into voxcpm2.forward to locate the NaN source.
Idempotent. Run in /workspace/VoxCPM. Remove later by `git checkout src/voxcpm/model/voxcpm2.py`."""
import io
VOX = "src/voxcpm/model/voxcpm2.py"
anchor = "        # [fp32diff] flow-matching loss is numerically unstable in bf16 -> force fp32\n"
inject = (
    "        import sys as _sys\n"
    "        for _nm, _x in [(\"feat_embed\", feat_embed), (\"text_embed\", text_embed),\n"
    "                        (\"combined_embed\", combined_embed), (\"enc_outputs\", enc_outputs),\n"
    "                        (\"residual_outputs\", residual_outputs), (\"dit_hidden\", dit_hidden),\n"
    "                        (\"audio_feats\", audio_feats)]:\n"
    "            print(f\"[chk] {_nm:16s} finite={bool(torch.isfinite(_x).all())} dtype={_x.dtype}\", file=_sys.stderr)\n"
)
s = io.open(VOX, encoding="utf-8").read()
if "[chk]" in s:
    print("dbg checks: already injected")
else:
    assert anchor in s, "anchor not found"
    io.open(VOX, "w", encoding="utf-8").write(s.replace(anchor, inject + anchor, 1))
    print("dbg checks: injected")
