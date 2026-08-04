#!/usr/bin/env python3
r"""
Train a LoRA adapter for the local Qwen3-4B-Instruct-2507 quant
(Ollama tag goekdenizguelmez/JOSIEFIED-Qwen3:4b-instruct-2507-q4_k_m) on the
ScreenMagnet development corpus.

This is the step Ollama cannot do. Run it in a python3.13 venv -- torch has no
3.14 wheels, and 3.14 may be this box's default python. See README.md.

Linux/SteamOS (bash, CPU-only -- AMD gfx1103 has no ROCm training path here):
    python3.13 -m venv ~/.local/share/screenmagnet/loravenv
    source ~/.local/share/screenmagnet/loravenv/bin/activate
    pip install torch --index-url https://download.pytorch.org/whl/cpu
    pip install transformers peft datasets accelerate

Windows (this box -- NVIDIA RTX 4060 Laptop 8GB, python3.13.14 via "py -3.13",
GPU path uses 4-bit QLoRA so it fits in 8GB):
    py -3.13 -m venv %LOCALAPPDATA%\screenmagnet\loravenv
    %LOCALAPPDATA%\screenmagnet\loravenv\Scripts\activate
    pip install torch --index-url https://download.pytorch.org/whl/cu126
    pip install transformers peft datasets accelerate bitsandbytes

    ./train_lora.py --check      # env + corpus sanity, trains nothing
    ./train_lora.py              # train (auto: CUDA 4-bit QLoRA if available, else CPU)
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
CORPUS = HERE / "corpus.jsonl"
OUTDIR = HERE / "adapter"

# HF repo for the base weights. Verified to exist at
# https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507 -- config.json architectures =
# ["Qwen3ForCausalLM"], model_type "qwen3", 36 layers, GQA (32 query / 8 KV heads).
# The Ollama tag actually pulled on this box (see OLLAMA_MODEL_TAG below) is a GGUF
# quant of this same base; LoRA training needs the original safetensors weights, not
# the GGUF. Override with --base if the repo name differs.
BASE_MODEL = "Qwen/Qwen3-4B-Instruct-2507"

# Local Ollama tag this adapter is eventually served under (see train()'s closing
# instructions). Not used for training -- just documentation/output.
OLLAMA_MODEL_TAG = "goekdenizguelmez/JOSIEFIED-Qwen3:4b-instruct-2507-q4_k_m"

PROMPT = (
    "You are observing the ScreenMagnet project being built.\n\n"
    "STEP: {step}\n\nWHAT HAPPENED:\n{detail}\n\nExplain this step:"
)


def load_corpus():
    if not CORPUS.exists():
        sys.exit(f"No corpus at {CORPUS}. Run observer.py first.")
    rows = []
    for n, line in enumerate(CORPUS.open(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            print(f"  ! skipping malformed line {n}")
            continue
        exp = d.get("explanation", "")
        if not exp or exp.startswith("[OBSERVER FAILED"):
            print(f"  ! skipping line {n} (no usable explanation)")
            continue
        rows.append({
            "prompt": PROMPT.format(step=d.get("step", ""), detail=d.get("detail", "")),
            "completion": exp,
        })
    return rows


def check():
    print(f"corpus:  {CORPUS}")
    rows = load_corpus()
    print(f"usable examples: {len(rows)}")
    if rows:
        chars = sum(len(r["prompt"]) + len(r["completion"]) for r in rows)
        print(f"total chars: {chars:,}  (~{chars // 4:,} tokens)")
    print(f"python:  {sys.version.split()[0]}")
    if sys.version_info[:2] >= (3, 14):
        print("  !! torch has no wheels for 3.14 -- use python3.13 (py -3.13 on Windows)")
    for mod in ("torch", "transformers", "peft", "datasets", "accelerate", "bitsandbytes"):
        try:
            m = __import__(mod)
            extra = ""
            if mod == "torch":
                cuda_ok = m.cuda.is_available()
                extra = f"  (cuda={cuda_ok}"
                if cuda_ok:
                    extra += f", device={m.cuda.get_device_name(0)}"
                    props = m.cuda.get_device_properties(0)
                    extra += f", vram={props.total_memory / 2**30:.1f}GB"
                else:
                    extra += " -- will fall back to CPU (slow)"
                extra += ")"
            print(f"  {mod:14s} {getattr(m, '__version__', '?')}{extra}")
        except ImportError:
            note = "  (needed for 4-bit QLoRA on GPU)" if mod == "bitsandbytes" else ""
            print(f"  {mod:14s} NOT INSTALLED{note}")
    if len(rows) < 20:
        print("\nNOTE: fewer than 20 examples. Keep building -- the corpus grows per step.")


def train(base, epochs, rank, lr, max_len):
    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (AutoModelForCausalLM, AutoTokenizer,
                              BitsAndBytesConfig, DataCollatorForLanguageModeling,
                              Trainer, TrainingArguments)

    rows = load_corpus()
    if not rows:
        sys.exit("Corpus has no usable examples.")
    print(f"Training on {len(rows)} examples from {CORPUS.name}")

    tok = AutoTokenizer.from_pretrained(base)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    def encode(row):
        text = row["prompt"] + "\n\n" + row["completion"] + tok.eos_token
        return tok(text, truncation=True, max_length=max_len)

    ds = Dataset.from_list(rows).map(encode, remove_columns=["prompt", "completion"])

    use_cuda = torch.cuda.is_available()
    if use_cuda:
        # QLoRA: base weights in 4-bit NF4 with double quantization, compute in
        # bf16. Lets an 8GB card hold the 4B base + adapter + optimizer states +
        # activations comfortably. device_map="auto" places everything on the GPU.
        print(f"CUDA device: {torch.cuda.get_device_name(0)} -- loading base in 4-bit (QLoRA)")
        model = AutoModelForCausalLM.from_pretrained(
            base,
            quantization_config=BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=torch.bfloat16,
            ),
            device_map="auto",
        )
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    else:
        print("No CUDA device found -- falling back to CPU (float32, slow)")
        model = AutoModelForCausalLM.from_pretrained(
            base, torch_dtype=torch.float32, device_map=None,
        )
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()

    model.config.use_cache = False  # incompatible with gradient checkpointing

    model = get_peft_model(model, LoraConfig(
        r=rank,
        lora_alpha=rank * 2,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        # Verified against transformers' modeling_qwen3.py: Qwen3Attention has
        # q_proj/k_proj/v_proj/o_proj, Qwen3MLP has gate_proj/up_proj/down_proj --
        # same naming as Qwen2/Llama-style archs, so these names apply as-is.
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    ))
    model.print_trainable_parameters()

    Trainer(
        model=model,
        train_dataset=ds,
        data_collator=DataCollatorForLanguageModeling(tok, mlm=False),
        args=TrainingArguments(
            output_dir=str(OUTDIR / "checkpoints"),
            num_train_epochs=epochs,
            per_device_train_batch_size=1,
            gradient_accumulation_steps=8,
            learning_rate=lr,
            logging_steps=1,
            save_strategy="epoch",
            report_to=[],
            use_cpu=not use_cuda,
            bf16=use_cuda,
            optim="paged_adamw_8bit" if use_cuda else "adamw_torch",
        ),
    ).train()

    model.save_pretrained(OUTDIR)
    tok.save_pretrained(OUTDIR)
    print(f"\nAdapter saved to {OUTDIR}")
    print("\nNext -- convert to GGUF and serve from Ollama:")
    print("  python llama.cpp/convert_lora_to_gguf.py "
          f"{OUTDIR} --outfile {HERE}/adapter.gguf")
    print(f"  printf 'FROM {OLLAMA_MODEL_TAG}\\nADAPTER {HERE}/adapter.gguf\\n' "
          "> Modelfile && ollama create screenmagnet-qwen -f Modelfile")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--check", action="store_true", help="sanity-check env and corpus only")
    p.add_argument("--base", default=BASE_MODEL, help=f"HF base model (default {BASE_MODEL})")
    p.add_argument("--epochs", type=int, default=3)
    p.add_argument("--rank", type=int, default=16)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--max-len", type=int, default=2048)
    a = p.parse_args()

    if a.check:
        check()
    else:
        train(a.base, a.epochs, a.rank, a.lr, a.max_len)
