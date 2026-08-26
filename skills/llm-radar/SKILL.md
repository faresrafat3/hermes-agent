---
name: llm-radar
description: "Classify, benchmark, and route free LLMs into agent workflow tiers."
version: 0.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [llm, benchmark, catalog, routing, free-llm, providers]
    related_skills: [hermes-agent, hermes-provider-debugging, hermes-multi-key-provider-pools]
---

# LLM Radar

Classify free LLMs through standardized benchmarks, assign tiers, and expose a structured catalog that agents can use for delegation routing.

## When to Use

- A new free LLM provider/key becomes available and needs vetting before entering the workflow
- An agent needs to pick the right LLM for a task (mechanical vs. architecture vs. Arabic chat)
- An existing provider's status has changed (rate limits, model retirement, quality drift)
- You want to compare free tiers across providers for a specific task type
- You need to document strengths/weaknesses for delegation decisions

**Don't use for:**
- Paid providers with established SLAs — those go directly into config.yaml
- Local Ollama models — those are covered by `hermes-provider-debugging`
- One-off model tests without classification intent

## Prerequisites

- Python 3.10+ with `openai` package (for OpenAI-compatible providers)
- `requests` for direct REST APIs
- Provider API keys stored as env vars (never in catalog files)
- Each provider key must be pre-configured in `~/.hermes/.env` or exported to env

### Required Env Vars (per provider)

See `references/catalog.md` for the full env var list. Common ones:
- `GROQ_API_KEY`
- `GEMINI_API_KEY` (Google AI Studio)
- `OPENROUTER_API_KEY`
- `MISTRAL_API_KEY`
- `GITHUB_TOKEN` (for GitHub Models)
- `CLOUDFLARE_API_KEY` + `CLOUDFLARE_ACCOUNT_ID`

## How to Run

### Full Benchmark Run

```bash
python skills/llm-radar/scripts/run_benchmark.py --all
```

### Single Provider

```bash
python skills/llm-radar/scripts/run_benchmark.py --provider groq --model llama-3.3-70b
```

### Verify a Provider (health check only)

```bash
python skills/llm-radar/scripts/run_benchmark.py --provider groq --healthcheck
```

### Update Catalog

```bash
python skills/llm-radar/scripts/run_benchmark.py --update-catalog
```

## Quick Reference

| Command | Purpose |
|---------|---------|
| `--all` | Full benchmark suite on all enabled providers |
| `--provider <name>` | Target one provider |
| `--model <id>` | Target one model |
| `--healthcheck` | Quick latency + availability check |
| `--update-catalog` | Merge results into catalog JSON |
| `--tier <s\|a\|b\|rejected>` | Filter by tier |
| `--task <type>` | Filter by best_for task |

## Procedure

### 1. Discover Available Providers

Run health checks on all known providers to see which have valid keys:

```bash
python skills/llm-radar/scripts/run_benchmark.py --discover
```

This returns a list of providers with valid credentials and their available models.

### 2. Run Benchmarks

Execute the standardized test suite (see `references/benchmark-suite.md`):

```bash
python skills/llm-radar/scripts/run_benchmark.py --all --output json
```

Each benchmark produces a score 0-100 per dimension.

### 3. Review Classification

The script assigns tiers based on aggregate scores:
- **S-Tier** (≥85): Agent-safe, tool-use verified, Arabic OK → primary agents
- **A-Tier** (70-84): Solid for mechanical work → subagents
- **B-Tier** (50-69): Limited but usable → batch, low-priority
- **Rejected** (<50): Fails core tests → excluded from workflow

### 4. Publish to Catalog

Once a provider passes, update the machine-readable catalog:

```bash
python skills/llm-radar/scripts/run_benchmark.py --update-catalog
```

This writes to `data/catalog.json` and regenerates `references/catalog.md`.

### 5. Use for Delegation

When an agent needs to route a task, read `data/catalog.json`:

```python
import json
catalog = json.load(open("skills/llm-radar/data/catalog.json"))
# Filter by task type and tier
candidates = [p for p in catalog["providers"] 
              if "coding" in p["best_for"] and p["tier"] in ("s", "a")]
```

## Pitfalls

- **Free tier drift:** Providers change limits without notice. Re-run benchmarks weekly.
- **Key leakage:** Never commit API keys. The catalog stores only provider/model metadata, never credentials.
- **Rate limit contamination:** Running benchmarks aggressively can exhaust daily limits. Use `--throttle` flag.
- **Provider API changes:** An adapter breaking doesn't mean the provider is dead — check if it's an API version change.
- **Arabic scoring:** Arabic quality is subjective. Use the standardized Arabic prompt set and score blindly when possible.

## Verification

After running benchmarks:

1. Check `data/catalog.json` has the expected providers with tiers
2. Verify each provider's `last_verified` timestamp is today
3. Confirm the `benchmark_results` object has all 7 dimensions scored
4. Ensure `best_for` and `not_for` arrays are populated
5. Run `python skills/llm-radar/scripts/run_benchmark.py --validate` to check catalog integrity
