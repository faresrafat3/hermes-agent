"""Hermes Adaptive Memory Matrix (HAMM).

Provides 5-tier memory taxonomy and zero-pollution side-quest distillation:
- Tier 0: Immutable Constitution (CONSTITUTION.md)
- Tier 1: Core Architecture Specs (SPEC_MEMORY.db)
- Tier 2: Distilled Value Assets (distilled_assets.json)
- Tier 3: Compartmentalized Side-Quests (sidequests/<domain>.db)
- Tier 4: Ephemeral Scratchpad
"""

from __future__ import annotations

import os
import json
import sqlite3
from pathlib import Path
from typing import Dict, Any, List, Optional


class AdaptiveMemoryMatrix:
    """Manages segregated memory spaces and automated value distillation."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir or os.getenv("HERMES_HOME", Path.home() / ".hermes"))
        self.sidequests_dir = self.base_dir / "sidequests"
        self.assets_file = self.base_dir / "distilled_assets.json"
        self.sidequests_dir.mkdir(parents=True, exist_ok=True)
        self._init_assets_store()

    def _init_assets_store(self) -> None:
        if not self.assets_file.exists():
            self.assets_file.write_text(
                json.dumps(
                    {
                        "version": "1.0.0",
                        "discovered_llm_endpoints": [],
                        "extracted_skills": ["llm-radar"],
                        "promoted_algorithms": [],
                        "last_distilled_at": None,
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

    def record_sidequest_entry(self, domain: str, raw_payload: Dict[str, Any]) -> int:
        """Store raw, verbose side-quest records in an isolated DB without polluting core context."""
        domain_db = self.sidequests_dir / f"{domain}.db"
        with sqlite3.connect(domain_db) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sidequest_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    payload TEXT NOT NULL
                )
                """
            )
            cursor = conn.execute(
                "INSERT INTO sidequest_logs (payload) VALUES (?)",
                (json.dumps(raw_payload, ensure_ascii=False),),
            )
            return cursor.lastrowid or 0

    def distill_asset(self, asset_type: str, clean_item: Dict[str, Any]) -> bool:
        """Promote high-value distilled asset into the core distilled_assets.json registry."""
        assets = json.loads(self.assets_file.read_text(encoding="utf-8"))
        if asset_type == "llm_endpoint":
            existing = [x.get("url") for x in assets.get("discovered_llm_endpoints", [])]
            if clean_item.get("url") not in existing:
                assets.setdefault("discovered_llm_endpoints", []).append(clean_item)
        elif asset_type == "skill":
            skill_name = clean_item.get("name")
            if skill_name and skill_name not in assets.get("extracted_skills", []):
                assets.setdefault("extracted_skills", []).append(skill_name)
        elif asset_type == "algorithm":
            assets.setdefault("promoted_algorithms", []).append(clean_item)

        assets["last_distilled_at"] = os.times().elapsed
        self.assets_file.write_text(json.dumps(assets, indent=2, ensure_ascii=False), encoding="utf-8")
        return True

    def get_clean_core_context(self) -> Dict[str, Any]:
        """Returns ONLY purified assets for active core reasoning, shielding from sidequest noise."""
        assets = json.loads(self.assets_file.read_text(encoding="utf-8"))
        return {
            "distilled_skills": assets.get("extracted_skills", []),
            "healthy_endpoints": [
                x for x in assets.get("discovered_llm_endpoints", []) if x.get("status") != "dead"
            ],
        }


if __name__ == "__main__":
    matrix = AdaptiveMemoryMatrix()
    print("Adaptive Memory Matrix Initialized at:", matrix.base_dir)
    print("Core Clean Context:", matrix.get_clean_core_context())
