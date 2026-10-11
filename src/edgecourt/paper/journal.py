"""Journal append-only (JSONL, chaîné par empreinte). On n'édite ni ne supprime jamais une ligne.

kinds : prediction (mode backtest|prospective), result, settlement. Une écriture déjà présente (même id) est ignorée.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .. import config
from ..data.store import now_utc

GENESIS = "0" * 64


class Journal:
    def __init__(self, origin: str):
        self.path: Path = config.origin_dir(origin) / "journal.jsonl"
        self.ids: set[str] = set()
        self.last = GENESIS
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self.ids.add(rec["id"])
                    self.last = rec["hash"]

    def append_many(self, records: list[dict]) -> int:
        n = 0
        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            for rec in records:
                if rec["id"] in self.ids:
                    continue
                rec = {**rec, "written_at": now_utc().isoformat(timespec="seconds"), "prev": self.last}
                rec["hash"] = hashlib.sha256(json.dumps(rec, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
                fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
                self.ids.add(rec["id"])
                self.last = rec["hash"]
                n += 1
        return n

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]

    def verify(self) -> bool:
        prev = GENESIS
        for rec in self.read():
            h = rec.pop("hash")
            if rec["prev"] != prev or hashlib.sha256(json.dumps(rec, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest() != h:
                return False
            prev = h
        return True


def make_id(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:24]


def config_hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:12]
