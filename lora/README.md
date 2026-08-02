# qwen3.5:4b LoRA — watching this project get built

Claude builds ScreenManget. `qwen3.5:4b` watches every step and writes down what happened
and *why*. That record becomes a LoRA adapter for qwen.

## The loop

```
Claude does a build step
        │
        ▼
observer.py  ──►  qwen3.5:4b explains it  ──►  corpus.jsonl
                                                    │
                                                    ▼
                                            train_lora.py  (peft + transformers)
                                                    │
                                                    ▼
                                          convert to GGUF  (llama.cpp)
                                                    │
                                                    ▼
                                    Modelfile:  FROM qwen3.5:4b
                                                ADAPTER ./adapter.gguf
                                                    │
                                                    ▼
                                             ollama create / run
```

**Ollama's role:** it runs qwen for the observation half, and it *serves* the finished
adapter at the end via the `ADAPTER` directive. It does not do the training step —
Ollama has no fine-tuning code path. That middle step is `train_lora.py`, below.

## Status

| Stage | State |
|---|---|
| Observation → corpus | ✅ **running** — `observer.py`, corpus grows per build step |
| Training script | ✅ written — `train_lora.py` |
| Base weights downloaded | ⚠ **not yet** — ~8 GB from HF, see below |
| Training run | ⚠ **not yet** — needs a hardware decision, see below |
| GGUF conversion | ⚠ **not yet** |
| Ollama adapter serving | ⚠ **not yet** |

## Hardware reality (verified on this box)

| Thing | State | Consequence |
|---|---|---|
| Default python | **3.14.6** (linuxbrew) | ❌ torch publishes no 3.14 wheels — cannot use |
| `/usr/bin/python3.13` | present | ✅ **build the venv on 3.13** |
| ROCm | **not installed**, no `/opt/rocm` | no GPU training out of the box |
| GPU | Phoenix1 = **gfx1103** | ROCm doesn't officially support gfx1103; needs the `HSA_OVERRIDE_GFX_VERSION=11.0.0` hack |
| Root filesystem | `steamos-readonly` **enabled** | installing ROCm system-wide fights the immutable root |
| RAM | 30 GB | ✅ enough for CPU LoRA on a 4B at low rank |

### Three honest options for the training step

1. **CPU on this box** — works, no new system packages, venv on python3.13. Slow: expect
   hours for a few hundred examples on a 4B at rank 8–16. Perfectly fine for a corpus this
   size, which is small by design.
2. **Another fleet device** — if any machine in `machine-lineup` has an NVIDIA GPU, that's
   the fast path (unsloth requires CUDA and is not an option on this AMD box).
3. **Rented GPU** — upload `corpus.jsonl`, train, download the adapter. Fastest, costs money.

**Recommendation: option 1.** The corpus is deliberately small and the point is a
personality/domain adapter, not a capability jump. CPU is adequate and avoids touching
the immutable root.

## Setup

```bash
python3.13 -m venv ~/.local/share/screenmanget/loravenv
source ~/.local/share/screenmanget/loravenv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install transformers peft datasets accelerate
```

Then:

```bash
python train_lora.py --check          # verify env, count corpus, no training
python train_lora.py                  # actually train
```

## Corpus format

One JSON object per line:

```json
{"ts": "...", "project": "ScreenManget", "step": "...", "detail": "...",
 "explanation": "...", "model": "qwen3.5:4b"}
```

`detail` (what Claude did) is the input; `explanation` (qwen's reasoning about it) is the
target. Training on its own explanations reinforces the *reasoning pattern* — the model
learns to think about engineering decisions the way this project makes them.

## Adding an observation manually

```bash
./observer.py "step title" "what actually happened, in detail"
./observer.py --show
```
