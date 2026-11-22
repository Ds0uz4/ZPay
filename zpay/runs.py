"""In-memory run registry with an append-only audit trail persisted to artifacts/<run>/audit.jsonl."""
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .rag import EvidencePool


class Run:
    def __init__(self, run_input: dict) -> None:
        self.id = uuid.uuid4().hex[:10]
        self.input = run_input
        self.status = "running"
        self.events: list[dict] = []
        self.pool = EvidencePool()
        self.lock = threading.Lock()
        self.dir: Path = config.ARTIFACTS_DIR / "runs" / self.id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.created = time.time()

    def emit(self, type_: str, **data) -> None:
        with self.lock:
            self.events.append({"i": len(self.events), "type": type_, **data})

    def audit(self, event: str, **data) -> None:
        record = {"ts": datetime.now(timezone.utc).isoformat(), "run": self.id, "event": event, **data}
        with self.lock, (self.dir / "audit.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def llm_log(self, agent: str, system: str, user: str, output: str) -> None:
        self.audit("llm_call", agent=agent, system=system, prompt=user, output=output, model=config.LM_MODEL)

    def read_audit(self) -> list[dict]:
        path = self.dir / "audit.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


RUNS: dict[str, Run] = {}
