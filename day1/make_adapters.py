"""Write two rank-8 LoRA adapters for the served Gemma 4 E2B checkpoint, targeting q_proj and o_proj.

zero: lora_B is all zeros, so output must equal the base model's.
rand: lora_B is small random values, so output must differ from the base model's.
Shapes are read from the checkpoint (packed int4: 8 values per int32 column).

usage: python3 day1/make_adapters.py <snapshot_dir> <out_dir>
"""
import json, sys, torch
from safetensors import safe_open
from safetensors.torch import save_file

snap, out = sys.argv[1], sys.argv[2]
cfg = json.load(open(f"{snap}/config.json"))
tc = cfg.get("text_config", cfg)
rank = 8
torch.manual_seed(0)

shapes = {}
for i in range(tc["num_hidden_layers"]):
    with safe_open(f"{snap}/model-layer-{i:03d}.safetensors", "pt") as h:
        for mod in ("q_proj", "o_proj"):
            out_f, packed_in = h.get_slice(f"model.language_model.layers.{i}.self_attn.{mod}.weight_packed").get_shape()
            shapes[(i, mod)] = (out_f, packed_in * 8)

for name, scale in (("zero", 0.0), ("rand", 0.05)):
    tensors = {}
    for (i, mod), (out_f, in_f) in shapes.items():
        key = f"base_model.model.model.language_model.layers.{i}.self_attn.{mod}"
        tensors[f"{key}.lora_A.weight"] = (torch.randn(rank, in_f) * 0.05).half()
        tensors[f"{key}.lora_B.weight"] = (torch.randn(out_f, rank) * scale).half()
    d = f"{out}/{name}"
    import os; os.makedirs(d, exist_ok=True)
    save_file(tensors, f"{d}/adapter_model.safetensors")
    json.dump({"peft_type": "LORA", "r": rank, "lora_alpha": 16, "lora_dropout": 0.0, "bias": "none",
               "target_modules": ["q_proj", "o_proj"], "task_type": "CAUSAL_LM",
               "base_model_name_or_path": cfg.get("_name_or_path", "")}, open(f"{d}/adapter_config.json", "w"), indent=1)
    print(name, len(tensors), "tensors ->", d)
