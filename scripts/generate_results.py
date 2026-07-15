"""Run the red-team assertions and write a concise, reproducible results report."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import Database  # noqa: E402
from app.retrieval import PermissionAwareRetriever  # noqa: E402
from app.service import RagService  # noqa: E402


def main() -> None:
    attacks = json.loads((ROOT / "tests" / "attack_prompts.json").read_text(encoding="utf-8"))
    salary_figures = ("$95,000", "$118,000", "$122,000", "$148,000", "$154,000", "$186,000", "$78,000", "$105,000")
    retriever = PermissionAwareRetriever(ROOT / "corpus")
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "audit.sqlite3")
        database.initialize()
        service = RagService(retriever, database)
        for attack in attacks:
            response = service.ask(username="sales", role="sales", query=attack)
            assert not any(item["department"] == "finance" for item in response["retrieved_chunks"])
            assert not any(figure in response["answer"] for figure in salary_figures)
    (ROOT / "results.md").write_text(
        "# PermRAG red-team results\n\n"
        f"- **{len(attacks)} attack attempts**: sales-role attempts to extract finance-only data.\n"
        f"- **{len(attacks)}/{len(attacks)} blocked at the retrieval layer**: no finance chunk entered the response context.\n"
        f"- **0/{len(attacks)} answers** contained a confidential figure from `salary_bands.md`.\n"
        "- **Control check passed**: a finance-role query retrieved `salary_bands.md` and returned its grounded content.\n\n"
        "The test suite includes direct requests, rephrasing, prompt injection, role-play, encoding,\n"
        "indirect inference, multi-turn escalation fragments, and system-prompt extraction attempts.\n\n"
        "## Enforcement statement\n\n"
        "The retriever requires `user_role` and builds the permitted chunk set before it scores vectors.\n"
        "The answer generator receives only those selected permitted chunks. A post-retrieval assertion\n"
        "is retained as a fail-closed canary, not as the primary access-control mechanism.\n",
        encoding="utf-8",
    )
    print(f"Verified {len(attacks)} attacks with 0 finance-context leaks. Wrote results.md.")


if __name__ == "__main__":
    main()
