"""Plain-Python runner for CI and for reviewers without Prefect installed.

Equivalent to the DAG, minus the orchestrator:

    python -m flows.local_runner
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.config import load_settings  # noqa: E402
from src.pipeline import run_pipeline  # noqa: E402


def main() -> int:
    settings = load_settings()
    context = run_pipeline(settings)
    manifest_path = Path(context.artifacts_dir) / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    print(f"run_id          : {context.run_id}")
    print(f"gold rows       : {context.stage_counts.get('publish', 0):,}")
    print(f"gate B          : {manifest['validation']['gold']['passed']}/"
          f"{manifest['validation']['gold']['passed'] + manifest['validation']['gold']['failed']} expectations passed")
    print(f"bias breaches   : {manifest['bias']['breaches']}")
    print(f"manifest        : {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
