# LLM Radar Benchmark Suite

Standardized test prompts and scoring criteria for classifying free LLMs.

## Dimensions

### 1. Tool Use (function calling)

**Purpose:** Can the model invoke tools with correct schema?

**Test Prompt:**
```
You are a helpful assistant with access to tools. Use the get_weather tool to check the weather in Cairo.

Available tools:
{
  "name": "get_weather",
  "parameters": {
    "city": {"type": "string", "description": "City name"},
    "units": {"type": "enum", "values": ["celsius", "fahrenheit"]}
  }
}
```

**Scoring:**
- 100: Correct tool call with valid parameters
- 70: Tool call with minor parameter issues
- 40: Mentions tool but doesn't call
- 0: Ignores tools entirely

### 2. Arabic Quality

**Purpose:** Does the model handle Arabic (Egyptian/MSA) well?

**Test Prompt:**
```
اكتب لي رد بالعربي المصري على الرسالة التالية: "يا صاحبي إزيك، عامل إيه؟ عايز أكلمك في موضوع مهم"
```

**Scoring:**
- 100: Natural Egyptian Arabic, culturally appropriate
- 70: MSA but correct and natural
- 40: Mixed/forced Arabic with errors
- 0: Refuses or responds in English only

### 3. Instruction Following

**Purpose:** Does the model follow complex multi-step instructions?

**Test Prompt:**
```
Do exactly these steps:
1. Write a Python function that adds two numbers
2. Add type hints
3. Write a docstring in Arabic
4. Include one test case
5. Do NOT include any other text in your response
```

**Scoring:**
- 100: All 5 steps followed exactly
- 70: 4 steps followed
- 40: 2-3 steps followed
- 0: Ignores constraints

### 4. JSON Mode

**Purpose:** Can the model output valid JSON on demand?

**Test Prompt:**
```
Return a JSON object with these exact keys: {"name": "string", "age": number, "city": "string"}. Return ONLY the JSON, no other text.
```

**Scoring:**
- 100: Valid JSON, exact schema, no extra text
- 70: Valid JSON with minor schema deviation
- 40: JSON embedded in text
- 0: Invalid JSON or refuses

### 5. Latency

**Purpose:** How fast does the model respond?

**Measurement:** Time to first token (TTFT) and total generation time for a standard 100-token response.

**Scoring:**
- 100: < 500ms TTFT
- 70: 500ms - 1s
- 40: 1s - 3s
- 0: > 3s or timeout

### 6. Reliability

**Purpose:** Does the model respond consistently without errors?

**Measurement:** 5 consecutive requests, track success rate.

**Scoring:**
- 100: 5/5 success
- 70: 4/5
- 40: 3/5
- 0: < 3/5

### 7. Multi-turn Coherence

**Purpose:** Does the model remember context across turns?

**Test:**
```
Turn 1: "My name is Ahmed and I live in Cairo"
Turn 2: "What's my name?"
Turn 3: "Where do I live?"
```

**Scoring:**
- 100: All answers correct
- 70: 2/3 correct
- 40: 1/3 correct
- 0: All wrong

## Tier Thresholds

| Tier | Min Score | Use Case |
|------|-----------|----------|
| S | ≥85 all dimensions | Primary agent delegation |
| A | ≥70 all dimensions | Subagent mechanical work |
| B | ≥50 all dimensions | Batch/low-priority |
| Rejected | <50 any dimension | Excluded from workflow |

## Task-Specific Weights

Different tasks weight dimensions differently:

| Task Type | Tool Use | Arabic | Instructions | JSON | Latency | Reliability | Multi-turn |
|-----------|----------|--------|--------------|------|---------|-------------|------------|
| Coding | 30% | 5% | 20% | 25% | 10% | 5% | 5% |
| Arabic Chat | 5% | 40% | 15% | 5% | 10% | 10% | 15% |
| Data Processing | 20% | 5% | 25% | 30% | 10% | 5% | 5% |
| Research | 15% | 10% | 20% | 10% | 15% | 15% | 15% |
| Routing | 25% | 5% | 25% | 20% | 10% | 10% | 5% |
