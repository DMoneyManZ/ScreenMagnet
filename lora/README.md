# qwen3.5:4b LoRA — watching this project get built

Claude builds ScreenMagnet. `qwen3.5:4b` watches every step and writes down what happened
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

## Hardware reality (verified per-box)

### SteamOS/Linux box

| Thing | State | Consequence |
|---|---|---|
| Default python | **3.14.6** (linuxbrew) | ❌ torch publishes no 3.14 wheels — cannot use |
| `/usr/bin/python3.13` | present | ✅ **build the venv on 3.13** |
| ROCm | **not installed**, no `/opt/rocm` | no GPU training out of the box |
| GPU | Phoenix1 = **gfx1103** | ROCm doesn't officially support gfx1103; needs the `HSA_OVERRIDE_GFX_VERSION=11.0.0` hack |
| Root filesystem | `steamos-readonly` **enabled** | installing ROCm system-wide fights the immutable root |
| RAM | 30 GB | ✅ enough for CPU LoRA on a 4B at low rank |

### Windows box (this repo checkout, `C:\Users\murph\ScreenManget`)

| Thing | State | Consequence |
|---|---|---|
| Default python | 3.14 present alongside 3.13 | ✅ **use `py -3.13`** for the venv (same torch-wheel constraint as the SteamOS box) |
| `py -3.13` | present (python3.13.14) | ✅ **build the venv on 3.13**, no `/usr/bin/python3.13` here — it's a `py` launcher alias instead |
| GPU | **NVIDIA GeForce RTX 4060 Laptop, 8GB VRAM** | ✅ real CUDA training path — no AMD/ROCm workaround needed |
| Driver | 596.21 (`nvidia-smi`, CUDA 13.2 max-supported) | verified empirically: `cu121`/`cu124` wheel indexes have no cp313/win_amd64 torch wheels at all — **`cu126` is the one that works** on this box's Python 3.13, confirmed via `pip install --dry-run` and a real install (torch 2.13.0+cu126) |
| Ollama | already running, `http://localhost:11434`, tag `goekdenizguelmez/JOSIEFIED-Qwen3:4b-instruct-2507-q4_k_m` pulled | observation half already works today; base weights for training still need a separate HF download (see `BASE_MODEL` in `train_lora.py`) |
| Filesystem | normal NTFS, writable | no immutable-root constraint to work around |

8GB VRAM is not enough to fine-tune a 4B model in full precision or even fp16 LoRA
with comfortable headroom, but it's enough for **QLoRA**: 4-bit NF4 base weights
(~2.5 GB) + LoRA adapter + optimizer states + activations fits with room to spare.
`train_lora.py` auto-detects CUDA and takes this path automatically; CPU remains the
fallback when no GPU is found.

### Three honest options for the training step

1. **CPU (SteamOS box)** — works, no new system packages, venv on python3.13. Slow:
   expect hours for a few hundred examples on a 4B at rank 8–16. Perfectly fine for a
   corpus this size, which is small by design.
2. **GPU (this Windows box)** — RTX 4060 8GB via QLoRA (4-bit NF4 + bitsandbytes).
   Minutes instead of hours for a corpus this size, and no immutable-root or ROCm
   headaches since it's plain CUDA on Windows. **Now the fast default when training
   is run from this machine.**
3. **Rented GPU** — upload `corpus.jsonl`, train, download the adapter. Still an
   option if neither local box is available, but with a real 8GB CUDA card in the
   fleet this is now the least necessary of the three.

**Recommendation:** train on the Windows box's RTX 4060 (option 2) when available —
it's materially faster and the QLoRA memory math comfortably fits 8GB for a corpus
this size. Fall back to CPU on the SteamOS box (option 1) when that's the only
machine at hand; the corpus is deliberately small and the point is a
personality/domain adapter, not a capability jump, so CPU training is still adequate,
just slower.

## Setup

SteamOS/Linux:

```bash
python3.13 -m venv ~/.local/share/screenmagnet/loravenv
source ~/.local/share/screenmagnet/loravenv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install transformers peft datasets accelerate
```

Windows (this box):

```
py -3.13 -m venv %LOCALAPPDATA%\screenmagnet\loravenv
%LOCALAPPDATA%\screenmagnet\loravenv\Scripts\activate
pip install torch --index-url https://download.pytorch.org/whl/cu126
pip install transformers peft datasets accelerate bitsandbytes
```

Verified working versions on this box: torch 2.13.0+cu126, bitsandbytes 0.50.0, transformers
5.14.1, peft 0.20.0, datasets 5.0.1, accelerate 1.14.0.

Then (either box):

```bash
python train_lora.py --check          # verify env, count corpus, no training
python train_lora.py                  # actually train (auto GPU QLoRA / CPU fallback)
```

## Corpus format

One JSON object per line:

```json
{"ts": "...", "project": "ScreenMagnet", "step": "...", "detail": "...",
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
