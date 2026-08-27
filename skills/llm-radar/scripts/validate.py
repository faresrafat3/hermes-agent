#!/usr/bin/env python3
"""LLM Radar - Real-time Channel Monitor & Key Validator."""

import json
import os
import re
import time
import requests
from datetime import datetime
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = SKILL_DIR / "data"
DISCOVERED_DIR = DATA_DIR / "discovered"
CATALOG_PATH = DATA_DIR / "catalog.json"

# Regex patterns
KEY_PATTERNS = {
    "openai": r"sk-[A-Za-z0-9]{48}",
    "groq": r"gsk_[A-Za-z0-9_-]{40,}",
    "openrouter": r"sk-or-v1-[A-Za-z0-9]{48}",
    "anthropic": r"sk-ant-[A-Za-z0-9_-]{40,}",
    "gemini": r"AIza[A-Za-z0-9_-]{35}",
    "generic_sk": r"sk-[A-Za-z0-9_-]{30,}",
    "thk_live": r"thk_live_[A-Za-z0-9_-]{40,}",
}

URL_PATTERN = r"https?://[^\s\"]+"
MODEL_PATTERN = r"([a-z0-9._-]+):free"


def extract_keys(text: str) -> list:
    """Extract API keys from text."""
    keys = []
    for provider, pattern in KEY_PATTERNS.items():
        for match in re.findall(pattern, text):
            keys.append({
                "provider": provider,
                "key": match[:15] + "..." + match[-8:],
                "full_key": match,
                "extracted_at": datetime.utcnow().isoformat(),
            })
    return keys


def extract_urls(text: str) -> list:
    """Extract URLs that look like API endpoints."""
    urls = re.findall(URL_PATTERN, text)
    # Filter for API-like URLs
    api_urls = []
    for url in urls:
        if any(kw in url.lower() for kw in ["api", "v1", "chat", "openai", "empero", "harbor", "gorouter", "tabi", "gmi"]):
            api_urls.append(url)
    return api_urls


def extract_free_models(text: str) -> list:
    """Extract :free model mentions."""
    return list(set(re.findall(MODEL_PATTERN, text.lower())))


def test_api_endpoint(base_url: str, key: str = "free", model: str = None) -> dict:
    """Test if an API endpoint actually works."""
    result = {
        "base_url": base_url,
        "key": key[:10] + "..." if len(key) > 10 else key,
        "models_work": False,
        "chat_work": False,
        "models": [],
        "chat_error": None,
        "latency_ms": 0,
    }
    
    start = time.time()
    
    # Test /models endpoint
    try:
        resp = requests.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        result["models_work"] = resp.status_code == 200
        if resp.status_code == 200:
            data = resp.json()
            result["data"] = data
            if isinstance(data, dict) and "data" in data:
                result["models"] = [m.get("id", "?") for m in data["data"]]
            elif isinstance(data, list):
                result["models"] = [m.get("id", "?") for m in data]
    except Exception as e:
        result["models_error"] = str(e)
    
    # Test /chat/completions endpoint
    if model and result["models_work"]:
        try:
            resp = requests.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 10},
                timeout=15,
            )
            result["chat_work"] = resp.status_code == 200
            if resp.status_code != 200:
                result["chat_error"] = f"{resp.status_code}: {resp.text[:100]}"
        except Exception as e:
            result["chat_error"] = str(e)
    
    result["latency_ms"] = round((time.time() - start) * 1000, 1)
    return result


def quick_validate(text: str) -> dict:
    """Quick validation of keys/URLs found in text."""
    results = {"keys": [], "urls": [], "summary": {"working": 0, "partial": 0, "dead": 0}}
    
    # Extract and test URLs
    urls = extract_urls(text)
    for url in urls:
        # Normalize URL
        if not url.endswith("/v1") and not url.endswith("/v1/"):
            test_url = url if url.endswith("/") else url + "/"
            if "/v1" not in test_url:
                test_url += "v1"
        else:
            test_url = url
        
        # Try with "free" key first
        test = test_api_endpoint(test_url, "free")
        results["urls"].append(test)
        
        if test["chat_work"]:
            results["summary"]["working"] += 1
        elif test["models_work"]:
            results["summary"]["partial"] += 1
        else:
            results["summary"]["dead"] += 1
    
    # Extract and test keys
    keys = extract_keys(text)
    for key_info in keys:
        # Skip thk_live keys (TokenHarbor - known expired)
        if key_info["provider"] == "thk_live":
            continue
        results["keys"].append(key_info)
    
    return results


def save_results(results: dict, source: str):
    """Save validation results."""
    DISCOVERED_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filepath = DISCOVERED_DIR / f"validation_{source}_{timestamp}.json"
    with open(filepath, "w") as f:
        json.dump(results, f, indent=2, default=str)
    return filepath


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="LLM Radar - Quick Validator")
    parser.add_argument("--text", type=str, help="Text to validate")
    parser.add_argument("--url", type=str, help="API URL to test")
    parser.add_argument("--key", type=str, default="free", help="API key to test")
    parser.add_argument("--model", type=str, help="Model to test")
    parser.add_argument("--file", type=str, help="File with text to validate")
    
    args = parser.parse_args()
    
    if args.url:
        result = test_api_endpoint(args.url, args.key, args.model)
        print(json.dumps(result, indent=2))
    
    elif args.text:
        results = quick_validate(args.text)
        print(json.dumps(results, indent=2, default=str))
    
    elif args.file:
        with open(args.file) as f:
            text = f.read()
        results = quick_validate(text)
        print(json.dumps(results, indent=2, default=str))
    
    else:
        print("Provide --text, --url, or --file")
