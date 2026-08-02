#!/usr/bin/env python3
"""
Train a LoRA adapter for qwen3.5:4b on the ScreenMagnet development corpus.

This is the step Ollama cannot do. Run it in a python3.13 venv -- torch has no
3.14 wheels, and 3.14 is this box's default python. See README.md.

    python3.13 -m venv ~/.local/share/screenmagnet/loravenv
    source ~/.local/share/screenmagnet/loravenv/bin/activate
    pip install torch --index-url https://download.pytorch.org/whl/cpu
    pip install transformers peft datasets accelerate

    ./train_lora.py --check      # env + corpus sanity, trains nothing
    ./train_lora.py              # train
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
CORPUS = HERE / "corpus.jsonl"
OUTDIR = HERE / "adapter"

# HF repo for the base weights. The Ollama tag `qwen3.5:4b` is a GGUF quant; LoRA
# training needs the safetensors base. Override with --base if the repo name differs.
BASE_MODEL = "Qwen/Qwen3.5-4B"

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
        print("  !! torch has no wheels for 3.14 -- use python3.13")
    for mod in ("torch", "transformers", "peft", "datasets"):
        try:
            m = __import__(mod)
            extra = ""
            if mod == "torch":
                extra = f"  (cuda={m.cuda.is_available()})"
            print(f"  {mod:14s} {getattr(m, '__version__', '?')}{extra}")
        except ImportError:
            print(f"  {mod:14s} NOT INSTALLED")
    if len(rows) < 20:
        print("\nNOTE: fewer than 20 examples. Keep building -- the corpus grows per step.")


def train(base, epochs, rank, lr, max_len):
    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model
    from transformers import (AutoModelForCausalLM, AutoTokenizer,
                              DataCollatorForLanguageModeling, Trainer,
                              TrainingArguments)

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

    model = AutoModelForCausalLM.from_pretrained(
        base, torch_dtype=torch.float32, device_map=None,
    )
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()

    model = get_peft_model(model, LoraConfig(
        r=rank,
        lora_alpha=rank * 2,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
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
            use_cpu=not torch.cuda.is_available(),
        ),
    ).train()

    model.save_pretrained(OUTDIR)
    tok.save_pretrained(OUTDIR)
    print(f"\nAdapter saved to {OUTDIR}")
    print("\nNext -- convert to GGUF and serve from Ollama:")
    print("  python llama.cpp/convert_lora_to_gguf.py "
          f"{OUTDIR} --outfile {HERE}/adapter.gguf")
    print(f"  printf 'FROM qwen3.5:4b\\nADAPTER {HERE}/adapter.gguf\\n' "
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
