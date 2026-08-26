#!/usr/bin/env python3
"""LLM Radar - Benchmark runner for free LLM providers."""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

PROVIDER_ADAPTERS = {}


def register_adapter(name):
    """Decorator to register a provider adapter."""
    def decorator(cls):
        PROVIDER_ADAPTERS[name] = cls
        return cls
    return decorator


class BaseAdapter:
    """Base class for provider adapters."""
    
    def __init__(self, config: dict):
        self.config = config
        self.name = config["name"]
        self.model = config["model"]
    
    def chat(self, messages: list, tools: list | None = None) -> dict:
        """Send a chat completion request. Returns {"content": str, "tool_calls": list, "latency_ms": float}."""
        raise NotImplementedError
    
    def healthcheck(self) -> dict:
        """Quick health check. Returns {"ok": bool, "latency_ms": float, "error": str}."""
        try:
            start = time.time()
            result = self.chat([{"role": "user", "content": "Say hello in one word."}])
            latency = (time.time() - start) * 1000
            return {"ok": True, "latency_ms": latency, "error": None}
        except Exception as e:
            return {"ok": False, "latency_ms": 0, "error": str(e)}


@register_adapter("groq")
class GroqAdapter(BaseAdapter):
    """Groq adapter using OpenAI-compatible API."""
    
    def __init__(self, config: dict):
        super().__init__(config)
        self.base_url = "https://api.groq.com/openai/v1"
        self.api_key = os.environ.get("GROQ_API_KEY", "")
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        except ImportError:
            raise RuntimeError("openai package required: pip install openai")
    
    def chat(self, messages: list, tools: list | None = None) -> dict:
        start = time.time()
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 1000,
        }
        if tools:
            kwargs["tools"] = tools
        
        response = self.client.chat.completions.create(**kwargs)
        latency = (time.time() - start) * 1000
        
        tool_calls = []
        if response.choices[0].message.tool_calls:
            for tc in response.choices[0].message.tool_calls:
                tool_calls.append({
                    "function": tc.function.name,
                    "arguments": json.loads(tc.function.arguments)
                })
        
        return {
            "content": response.choices[0].message.content or "",
            "tool_calls": tool_calls,
            "latency_ms": latency,
        }


@register_adapter("gemini")
class GeminiAdapter(BaseAdapter):
    """Google AI Studio (Gemini) adapter."""
    
    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = os.environ.get("GEMINI_API_KEY", "")
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"
    
    def chat(self, messages: list, tools: list | None = None) -> dict:
        import requests
        
        start = time.time()
        
        # Convert OpenAI format to Gemini format
        contents = []
        for msg in messages:
            if msg["role"] == "system":
                contents.append({"role": "user", "parts": [{"text": msg["content"]}]})
            elif msg["role"] == "user":
                contents.append({"role": "user", "parts": [{"text": msg["content"]}]})
            elif msg["role"] == "assistant":
                contents.append({"role": "model", "parts": [{"text": msg["content"]}]})
        
        payload = {
            "contents": contents,
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1000},
        }
        
        url = f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        latency = (time.time() - start) * 1000
        
        text = ""
        if "candidates" in data and data["candidates"]:
            text = data["candidates"][0].get("content", {}).get("parts", [{}])[0].get("text", "")
        
        return {"content": text, "tool_calls": [], "latency_ms": latency}


@register_adapter("openrouter")
class OpenRouterAdapter(BaseAdapter):
    """OpenRouter adapter."""
    
    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "")
        self.base_url = "https://openrouter.ai/api/v1"
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        except ImportError:
            raise RuntimeError("openai package required: pip install openai")
    
    def chat(self, messages: list, tools: list | None = None) -> dict:
        start = time.time()
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 1000,
        }
        if tools:
            kwargs["tools"] = tools
        
        response = self.client.chat.completions.create(**kwargs)
        latency = (time.time() - start) * 1000
        
        tool_calls = []
        if response.choices[0].message.tool_calls:
            for tc in response.choices[0].message.tool_calls:
                tool_calls.append({
                    "function": tc.function.name,
                    "arguments": json.loads(tc.function.arguments)
                })
        
        return {
            "content": response.choices[0].message.content or "",
            "tool_calls": tool_calls,
            "latency_ms": latency,
        }


@register_adapter("mistral")
class MistralAdapter(BaseAdapter):
    """Mistral AI adapter."""
    
    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = os.environ.get("MISTRAL_API_KEY", "")
        self.base_url = "https://api.mistral.ai/v1"
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        except ImportError:
            raise RuntimeError("openai package required: pip install openai")
    
    def chat(self, messages: list, tools: list | None = None) -> dict:
        start = time.time()
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 1000,
        }
        if tools:
            kwargs["tools"] = tools
        
        response = self.client.chat.completions.create(**kwargs)
        latency = (time.time() - start) * 1000
        
        tool_calls = []
        if response.choices[0].message.tool_calls:
            for tc in response.choices[0].message.tool_calls:
                tool_calls.append({
                    "function": tc.function.name,
                    "arguments": json.loads(tc.function.arguments)
                })
        
        return {
            "content": response.choices[0].message.content or "",
            "tool_calls": tool_calls,
            "latency_ms": latency,
        }


@register_adapter("cloudflare")
class CloudflareAdapter(BaseAdapter):
    """Cloudflare Workers AI adapter."""
    
    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = os.environ.get("CLOUDFLARE_API_KEY", "")
        self.account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
        self.base_url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/ai/run"
    
    def chat(self, messages: list, tools: list | None = None) -> dict:
        import requests
        
        start = time.time()
        
        # Cloudflare uses a simpler format
        prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
        
        response = requests.post(
            f"{self.base_url}/{self.model}",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"prompt": prompt, "max_tokens": 1000},
            timeout=30,
        )
        response.raise_for_status()
        
        data = response.json()
        latency = (time.time() - start) * 1000
        
        text = data.get("result", {}).get("response", "")
        return {"content": text, "tool_calls": [], "latency_ms": latency}


# Default provider configurations
DEFAULT_PROVIDERS = [
    {
        "name": "groq",
        "model": "llama-3.3-70b-specdec",
        "env_key": "GROQ_API_KEY",
        "available": False,
    },
    {
        "name": "gemini",
        "model": "gemini-2.0-flash",
        "env_key": "GEMINI_API_KEY",
        "available": False,
    },
    {
        "name": "openrouter",
        "model": "meta-llama/llama-3.1-70b-instruct:free",
        "env_key": "OPENROUTER_API_KEY",
        "available": False,
    },
    {
        "name": "mistral",
        "model": "mistral-small-latest",
        "env_key": "MISTRAL_API_KEY",
        "available": False,
    },
    {
        "name": "cloudflare",
        "model": "@cf/meta/llama-3.1-70b-instruct",
        "env_key": "CLOUDFLARE_API_KEY",
        "available": False,
    },
]


def discover_providers() -> list:
    """Find which providers have valid API keys."""
    available = []
    for provider in DEFAULT_PROVIDERS:
        if os.environ.get(provider["env_key"]):
            provider["available"] = True
            available.append(provider)
    return available


def run_benchmark(adapter: BaseAdapter, dimension: str) -> dict:
    """Run a single benchmark dimension."""
    
    if dimension == "tool_use":
        messages = [
            {"role": "user", "content": "You are a helpful assistant with access to tools. Use the get_weather tool to check the weather in Cairo. Available tools: {\"name\": \"get_weather\", \"parameters\": {\"city\": {\"type\": \"string\"}, \"units\": {\"type\": \"enum\", \"values\": [\"celsius\", \"fahrenheit\"]}}}"}
        ]
        tools = [{
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get current weather",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "City name"},
                        "units": {"type": "string", "enum": ["celsius", "fahrenheit"]}
                    },
                    "required": ["city"]
                }
            }
        }]
        result = adapter.chat(messages, tools=tools)
        
        score = 0
        if result["tool_calls"]:
            tc = result["tool_calls"][0]
            if tc["function"] == "get_weather" and "city" in tc["arguments"]:
                score = 100
            elif tc["function"] == "get_weather":
                score = 70
        elif "get_weather" in result["content"].lower():
            score = 40
        
        return {"score": score, "result": result}
    
    elif dimension == "arabic":
        messages = [
            {"role": "user", "content": "اكتب لي رد بالعربي المصري على الرسالة التالية: \"يا صاحبي إزيك، عامل إيه؟ عايز أكلمك في موضوع مهم\""}
        ]
        result = adapter.chat(messages)
        content = result["content"]
        
        # Heuristic scoring for Arabic
        egyptian_markers = ["إزيك", "عامل إيه", "يا صاحبي", "طيب", "تمام", "أهو", "أها", "كده"]
        arabic_chars = sum(1 for c in content if '\u0600' <= c <= '\u06FF')
        arabic_ratio = arabic_chars / max(len(content), 1)
        
        score = 0
        if arabic_ratio > 0.5:
            egyptian_count = sum(1 for m in egyptian_markers if m in content)
            if egyptian_count >= 2:
                score = 100
            elif egyptian_count >= 1:
                score = 85
            else:
                score = 70
        elif arabic_ratio > 0.2:
            score = 40
        
        return {"score": score, "result": result}
    
    elif dimension == "instruction_following":
        messages = [
            {"role": "user", "content": "Do exactly these steps:\n1. Write a Python function that adds two numbers\n2. Add type hints\n3. Write a docstring in Arabic\n4. Include one test case\n5. Do NOT include any other text in your response"}
        ]
        result = adapter.chat(messages)
        content = result["content"]
        
        score = 0
        has_function = "def " in content
        has_type_hints = "->" in content or ": int" in content or ": float" in content
        has_arabic_docstring = any(c for c in content if '\u0600' <= c <= '\u06FF') and '"""' in content
        has_test = "assert" in content or "test" in content.lower()
        no_extra_text = content.count("\n\n") < 3
        
        steps_followed = sum([has_function, has_type_hints, has_arabic_docstring, has_test, no_extra_text])
        
        if steps_followed == 5:
            score = 100
        elif steps_followed == 4:
            score = 70
        elif steps_followed >= 2:
            score = 40
        
        return {"score": score, "result": result}
    
    elif dimension == "json_mode":
        messages = [
            {"role": "user", "content": 'Return a JSON object with these exact keys: {"name": "string", "age": number, "city": "string"}. Return ONLY the JSON, no other text.'}
        ]
        result = adapter.chat(messages)
        content = result["content"].strip()
        
        score = 0
        try:
            data = json.loads(content)
            if isinstance(data, dict) and "name" in data and "age" in data and "city" in data:
                if isinstance(data["name"], str) and isinstance(data["age"], (int, float)) and isinstance(data["city"], str):
                    score = 100
                else:
                    score = 70
            else:
                score = 40
        except json.JSONDecodeError:
            # Try to extract JSON from text
            import re
            match = re.search(r'\{[^}]+\}', content)
            if match:
                try:
                    json.loads(match.group())
                    score = 40
                except:
                    pass
        
        return {"score": score, "result": result}
    
    elif dimension == "latency":
        messages = [{"role": "user", "content": "Write a short paragraph about the importance of fast response times in AI systems."}]
        result = adapter.chat(messages)
        
        latency = result["latency_ms"]
        if latency < 500:
            score = 100
        elif latency < 1000:
            score = 70
        elif latency < 3000:
            score = 40
        else:
            score = 0
        
        return {"score": score, "result": result, "latency_ms": latency}
    
    elif dimension == "reliability":
        successes = 0
        total = 5
        for i in range(total):
            try:
                messages = [{"role": "user", "content": f"Count to {i+1}."}]
                result = adapter.chat(messages)
                if result["content"]:
                    successes += 1
            except Exception:
                pass
        
        score = int((successes / total) * 100)
        # Adjust to our scale
        if score == 100:
            score = 100
        elif score >= 80:
            score = 70
        elif score >= 60:
            score = 40
        else:
            score = 0
        
        return {"score": score, "successes": successes, "total": total}
    
    elif dimension == "multi_turn":
        # Turn 1
        adapter.chat([{"role": "user", "content": "My name is Ahmed and I live in Cairo"}])
        # Turn 2
        result2 = adapter.chat([{"role": "user", "content": "What's my name?"}])
        # Turn 3
        result3 = adapter.chat([{"role": "user", "content": "Where do I live?"}])
        
        correct = 0
        if "ahmed" in result2["content"].lower():
            correct += 1
        if "cairo" in result3["content"].lower():
            correct += 1
        
        if correct == 2:
            score = 100
        elif correct == 1:
            score = 70
        else:
            score = 40
        
        return {"score": score, "correct": correct}
    
    return {"score": 0, "error": "Unknown dimension"}


def classify_tier(scores: dict) -> str:
    """Assign tier based on benchmark scores."""
    min_score = min(scores.values())
    
    if min_score >= 85:
        return "S"
    elif min_score >= 70:
        return "A"
    elif min_score >= 50:
        return "B"
    else:
        return "rejected"


def run_all_benchmarks(provider_configs: list, args) -> dict:
    """Run all benchmarks on all providers."""
    results = {
        "timestamp": datetime.utcnow().isoformat(),
        "providers": [],
    }
    
    for config in provider_configs:
        name = config["name"]
        print(f"\n{'='*60}")
        print(f"Benchmarking: {name}/{config['model']}")
        print(f"{'='*60}")
        
        adapter_class = PROVIDER_ADAPTERS.get(name)
        if not adapter_class:
            print(f"  No adapter for {name}, skipping")
            continue
        
        try:
            adapter = adapter_class(config)
        except Exception as e:
            print(f"  Failed to initialize: {e}")
            continue
        
        # Health check first
        health = adapter.healthcheck()
        print(f"  Health check: {'OK' if health['ok'] else 'FAIL'} ({health['latency_ms']:.0f}ms)")
        
        if not health["ok"]:
            results["providers"].append({
                "name": name,
                "model": config["model"],
                "status": "unhealthy",
                "error": health["error"],
            })
            continue
        
        # Run benchmarks
        dimensions = ["tool_use", "arabic", "instruction_following", "json_mode", "latency", "reliability", "multi_turn"]
        scores = {}
        
        for dim in dimensions:
            if args.throttle:
                time.sleep(1)
            try:
                bench_result = run_benchmark(adapter, dim)
                scores[dim] = bench_result["score"]
                print(f"  {dim}: {bench_result['score']}")
            except Exception as e:
                print(f"  {dim}: ERROR - {e}")
                scores[dim] = 0
        
        tier = classify_tier(scores)
        avg_score = sum(scores.values()) / len(scores) if scores else 0
        
        provider_result = {
            "name": name,
            "model": config["model"],
            "status": "ok",
            "tier": tier,
            "average_score": round(avg_score, 1),
            "benchmark_results": scores,
            "last_verified": datetime.utcnow().isoformat(),
            "latency_ms": health["latency_ms"],
        }
        
        results["providers"].append(provider_result)
        print(f"  TIER: {tier} (avg: {avg_score:.1f})")
    
    return results


def update_catalog(results: dict):
    """Update the catalog JSON file."""
    catalog_path = Path(__file__).resolve().parent.parent / "data" / "catalog.json"
    
    # Load existing catalog if present
    if catalog_path.exists():
        with open(catalog_path) as f:
            catalog = json.load(f)
    else:
        catalog = {"version": 1, "providers": []}
    
    # Update with new results
    for provider in results.get("providers", []):
        existing = next((p for p in catalog["providers"] if p["name"] == provider["name"]), None)
        if existing:
            existing.update(provider)
        else:
            catalog["providers"].append(provider)
    
    catalog["last_updated"] = datetime.utcnow().isoformat()
    
    with open(catalog_path, "w") as f:
        json.dump(catalog, f, indent=2)
    
    print(f"\nCatalog updated: {catalog_path}")


def main():
    parser = argparse.ArgumentParser(description="LLM Radar - Benchmark free LLM providers")
    parser.add_argument("--all", action="store_true", help="Run all benchmarks on all providers")
    parser.add_argument("--provider", type=str, help="Target a specific provider")
    parser.add_argument("--model", type=str, help="Target a specific model")
    parser.add_argument("--healthcheck", action="store_true", help="Quick health check only")
    parser.add_argument("--discover", action="store_true", help="Discover available providers")
    parser.add_argument("--update-catalog", action="store_true", help="Update catalog with results")
    parser.add_argument("--output", choices=["json", "text"], default="text", help="Output format")
    parser.add_argument("--throttle", action="store_true", help="Add delay between requests")
    parser.add_argument("--validate", action="store_true", help="Validate catalog integrity")
    
    args = parser.parse_args()
    
    if args.discover:
        available = discover_providers()
        print(f"Available providers: {len(available)}")
        for p in available:
            print(f"  - {p['name']}/{p['model']}")
        return
    
    if args.validate:
        catalog_path = Path(__file__).resolve().parent.parent / "data" / "catalog.json"
        if not catalog_path.exists():
            print("No catalog found")
            return
        with open(catalog_path) as f:
            catalog = json.load(f)
        print(f"Catalog: {len(catalog['providers'])} providers")
        for p in catalog["providers"]:
            print(f"  {p['name']}: tier={p.get('tier', '?')}, verified={p.get('last_verified', '?')}")
        return
    
    # Discover available providers
    available = discover_providers()
    
    if args.provider:
        available = [p for p in available if p["name"] == args.provider]
        if args.model:
            for p in available:
                p["model"] = args.model
    
    if not available:
        print("No providers available. Set API keys in environment.")
        return
    
    if args.healthcheck:
        for config in available:
            adapter_class = PROVIDER_ADAPTERS.get(config["name"])
            if adapter_class:
                adapter = adapter_class(config)
                health = adapter.healthcheck()
                print(f"{config['name']}: {'OK' if health['ok'] else 'FAIL'} ({health['latency_ms']:.0f}ms)")
        return
    
    if args.all or not args.healthcheck:
        results = run_all_benchmarks(available, args)
        
        if args.update_catalog:
            update_catalog(results)
        
        if args.output == "json":
            print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
