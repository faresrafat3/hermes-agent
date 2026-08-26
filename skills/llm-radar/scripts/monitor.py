#!/usr/bin/env python3
"""LLM Radar - Key Validator & Channel Monitor."""

import json
import os
import time
import re
from datetime import datetime
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = SKILL_DIR / "data"
DISCOVERED_DIR = DATA_DIR / "discovered"
CATALOG_PATH = DATA_DIR / "catalog.json"

# Patterns for API key extraction
KEY_PATTERNS = {
    "groq": r"gsk_[A-Za-z0-9_-]{40,}",
    "openrouter": r"sk-or-v1-[A-Za-z0-9]{48}",
    "openai": r"sk-[A-Za-z0-9]{48}",
    "anthropic": r"sk-ant-[A-Za-z0-9_-]{40,}",
    "gemini": r"AIza[A-Za-z0-9_-]{35}",
    "generic_sk": r"sk-[A-Za-z0-9_-]{30,}",
    "generic_bearer": r"bearer_[A-Za-z0-9_-]{20,}",
    "bearer_token": r"Bearer [A-Za-z0-9._-]{20,}",
}

# Known providers and their base URLs
PROVIDER_URLS = {
    "gorouter": "https://gorouter.app/v1",
    "tabi": "https://tabitoken.com/v1",
    "tokenharbor": "https://tokenharbor.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "gmi_cloud": "https://console.gmicloud.ai/v1",
    "b_ai": "https://chat.b.ai/v1",
    "true_sota": "https://true-sota.com/v1",
    "ineed": "https://ineed.web.id/v1",
}


def extract_keys(text: str) -> list:
    """Extract API keys from text using known patterns."""
    keys = []
    for provider, pattern in KEY_PATTERNS.items():
        matches = re.findall(pattern, text)
        for match in matches:
            keys.append({
                "provider": provider,
                "key": match[:20] + "..." + match[-8:],  # Masked
                "full_key": match,
                "extracted_at": datetime.utcnow().isoformat(),
            })
    return keys


def extract_free_models(text: str) -> list:
    """Extract free model mentions from text."""
    model_patterns = [
        r"([a-z0-9_-]+)/([a-z0-9._-]+):free",
        r"([a-z0-9_-]+)/([a-z0-9._-]+)\s*\(free\)",
        r"free:\s*([a-z0-9_./-]+)",
    ]
    models = []
    for pattern in model_patterns:
        matches = re.findall(pattern, text.lower())
        for match in matches:
            if isinstance(match, tuple):
                models.append(f"{match[0]}/{match[1]}")
            else:
                models.append(match)
    return list(set(models))


def extract_providers(text: str) -> list:
    """Extract provider/base URL mentions from text."""
    providers = []
    url_pattern = r"https?://[^\s]+"
    urls = re.findall(url_pattern, text)
    
    known_keywords = {
        "gorouter": "gorouter",
        "tabi": "tabi",
        "tokenharbor": "tokenharbor",
        "openrouter": "openrouter",
        "gmicloud": "gmi_cloud",
        "gmi cloud": "gmi_cloud",
        "b.ai": "b_ai",
        "true-sota": "true_sota",
        "true sota": "true_sota",
        "ineed": "ineed",
        "tencent": "tencent",
    }
    
    text_lower = text.lower()
    for keyword, provider in known_keywords.items():
        if keyword in text_lower:
            providers.append(provider)
    
    return list(set(providers)), urls


def validate_key(provider: str, key: str, base_url: str = None) -> dict:
    """Validate an API key by making a test request."""
    import requests
    
    if not base_url:
        base_url = PROVIDER_URLS.get(provider, "")
    
    if not base_url:
        return {"valid": False, "error": "No base URL for provider"}
    
    headers = {"Authorization": f"Bearer {key}"}
    
    # Try common endpoints
    endpoints = [
        f"{base_url}/models",
        f"{base_url}/v1/models",
        base_url,
    ]
    
    for endpoint in endpoints:
        try:
            resp = requests.get(endpoint, headers=headers, timeout=10)
            if resp.status_code == 200:
                return {
                    "valid": True,
                    "endpoint": endpoint,
                    "models_count": len(resp.json().get("data", [])) if "models" in endpoint else "unknown",
                    "latency_ms": resp.elapsed.total_seconds() * 1000,
                }
            elif resp.status_code == 401:
                return {"valid": False, "error": "Invalid key (401)"}
            elif resp.status_code == 403:
                return {"valid": False, "error": "Forbidden (403)"}
            elif resp.status_code == 429:
                return {"valid": False, "error": "Rate limited (429)"}
        except requests.exceptions.Timeout:
            continue
        except Exception as e:
            continue
    
    return {"valid": False, "error": "All endpoints failed"}


def monitor_channel(channel_name: str, messages: list) -> dict:
    """Process messages from a monitored channel."""
    findings = {
        "channel": channel_name,
        "processed_at": datetime.utcnow().isoformat(),
        "message_count": len(messages),
        "keys_found": [],
        "models_found": [],
        "providers_found": [],
        "urls_found": [],
    }
    
    for msg in messages:
        text = msg.get("text", "")
        if not text:
            continue
        
        # Extract keys
        keys = extract_keys(text)
        findings["keys_found"].extend(keys)
        
        # Extract free models
        models = extract_free_models(text)
        findings["models_found"].extend(models)
        
        # Extract providers
        providers, urls = extract_providers(text)
        findings["providers_found"].extend(providers)
        findings["urls_found"].extend(urls)
    
    # Deduplicate
    findings["models_found"] = list(set(findings["models_found"]))
    findings["providers_found"] = list(set(findings["providers_found"]))
    findings["urls_found"] = list(set(findings["urls_found"]))
    
    return findings


def save_findings(findings: dict, filename: str = None):
    """Save findings to the discovered directory."""
    DISCOVERED_DIR.mkdir(parents=True, exist_ok=True)
    
    if not filename:
        filename = f"{findings['channel']}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    
    filepath = DISCOVERED_DIR / filename
    with open(filepath, "w") as f:
        json.dump(findings, f, indent=2)
    
    return filepath


def generate_report(findings: dict) -> str:
    """Generate a human-readable report from findings."""
    lines = [
        f"# LLM Radar Report: {findings['channel']}",
        f"**Generated:** {findings['processed_at']}",
        f"**Messages processed:** {findings['message_count']}",
        "",
        "## 🔑 API Keys Found",
    ]
    
    if findings["keys_found"]:
        for key in findings["keys_found"]:
            lines.append(f"- **{key['provider']}**: `{key['key']}`")
    else:
        lines.append("- None")
    
    lines.extend(["", "## 🆓 Free Models"])
    if findings["models_found"]:
        for model in findings["models_found"]:
            lines.append(f"- `{model}`")
    else:
        lines.append("- None")
    
    lines.extend(["", "## 🏢 Providers Mentioned"])
    if findings["providers_found"]:
        for provider in findings["providers_found"]:
            lines.append(f"- {provider}")
    else:
        lines.append("- None")
    
    lines.extend(["", "## 🔗 URLs"])
    if findings["urls_found"]:
        for url in findings["urls_found"][:20]:  # Limit
            lines.append(f"- {url}")
    else:
        lines.append("- None")
    
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="LLM Radar - Channel Monitor")
    parser.add_argument("--channel", type=str, help="Channel to monitor")
    parser.add_argument("--validate", action="store_true", help="Validate discovered keys")
    parser.add_argument("--report", action="store_true", help="Generate report")
    parser.add_argument("--discover", action="store_true", help="List discovered files")
    
    args = parser.parse_args()
    
    if args.discover:
        files = list(DISCOVERED_DIR.glob("*.json"))
        print(f"Discovered files: {len(files)}")
        for f in sorted(files):
            print(f"  {f.name}")
    
    elif args.report:
        files = sorted(DISCOVERED_DIR.glob("*.json"))
        if files:
            latest = files[-1]
            with open(latest) as f:
                findings = json.load(f)
            report = generate_report(findings)
            print(report)
    
    elif args.validate:
        print("Key validation requires API access. Use the Hermes MCP tools to validate.")
        print("Discovered keys location: skills/llm-radar/data/discovered/")
