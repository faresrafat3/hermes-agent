# LLM Radar Catalog

Machine-readable catalog of verified free LLM providers with benchmark-backed tier assignments for agent delegation routing.

## Tier System

| Tier | Min Score | Use Case | Agent Type |
|------|-----------|----------|------------|
| **S** | ≥85 all dimensions | Primary agent delegation | Main agents (Research Scout, Historian, etc.) |
| **A** | ≥70 all dimensions | Subagent mechanical work | Simple subagents, batch workers |
| **B** | ≥50 all dimensions | Batch/low-priority | Background tasks, non-critical |
| **Rejected** | <50 any dimension | Excluded from workflow | None |

## How Agents Use This Catalog

### Delegation Decision Tree

```
Task arrives → What type?
├── Coding/Technical → Filter: tool_use ≥ 80%, tier S or A
├── Arabic Chat → Filter: arabic ≥ 80%, tier S
├── Data Processing → Filter: json_mode ≥ 80%, tier S or A
├── Research → Filter: multi_turn ≥ 70%, tier S
└── Mechanical → Filter: latency < 1000ms, tier A or B
```

### Routing Logic

```python
import json

def select_provider(task_type: str, min_tier: str = "A") -> dict | None:
    """Select best provider for a task type."""
    catalog = json.load(open("skills/llm-radar/data/catalog.json"))
    
    tier_rank = {"S": 3, "A": 2, "B": 1, "rejected": 0}
    min_rank = tier_rank.get(min_tier, 0)
    
    task_weights = {
        "coding": {"tool_use": 0.3, "json_mode": 0.25, "instruction_following": 0.2, "latency": 0.1, "reliability": 0.1, "multi_turn": 0.05},
        "arabic_chat": {"arabic": 0.4, "multi_turn": 0.2, "instruction_following": 0.15, "reliability": 0.1, "latency": 0.1, "tool_use": 0.05},
        "data_processing": {"json_mode": 0.3, "instruction_following": 0.25, "tool_use": 0.2, "latency": 0.1, "reliability": 0.1, "multi_turn": 0.05},
        "research": {"multi_turn": 0.2, "instruction_following": 0.2, "tool_use": 0.15, "arabic": 0.1, "reliability": 0.15, "latency": 0.1, "json_mode": 0.1},
        "mechanical": {"latency": 0.3, "reliability": 0.25, "tool_use": 0.2, "instruction_following": 0.15, "json_mode": 0.05, "multi_turn": 0.05, "arabic": 0.0},
    }
    
    weights = task_weights.get(task_type, task_weights["mechanical"])
    
    best = None
    best_score = -1
    
    for provider in catalog["providers"]:
        if tier_rank.get(provider.get("tier", "rejected"), 0) < min_rank:
            continue
        
        scores = provider.get("benchmark_results", {})
        weighted_score = sum(scores.get(dim, 0) * weight for dim, weight in weights.items())
        
        if weighted_score > best_score:
            best_score = weighted_score
            best = provider
    
    return best
```

## Current Catalog

_No providers verified yet. Run benchmarks to populate._

## Provider Entry Schema

```json
{
  "name": "groq",
  "model": "llama-3.3-70b-specdec",
  "status": "ok",
  "tier": "S",
  "average_score": 92.5,
  "benchmark_results": {
    "tool_use": 95,
    "arabic": 70,
    "instruction_following": 90,
    "json_mode": 100,
    "latency": 100,
    "reliability": 100,
    "multi_turn": 85
  },
  "best_for": ["coding", "routing", "mechanical"],
  "not_for": ["arabic_chat"],
  "rate_limits": {
    "rpm": 30,
    "rpd": 14400,
    "tpm": 6000
  },
  "last_verified": "2026-08-26T12:00:00Z",
  "latency_ms": 450
}
```

## Adding a New Provider

1. Add API key to `~/.hermes/.env`
2. Run: `python skills/llm-radar/scripts/run_benchmark.py --provider <name> --model <id> --update-catalog`
3. Review tier assignment in `data/catalog.json`
4. Commit the updated catalog

## Maintenance

- Re-verify providers weekly (free tiers change frequently)
- Run full suite before major workflow changes
- Remove providers that consistently fail health checks
- Update task weights based on real-world performance data
