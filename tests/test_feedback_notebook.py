from __future__ import annotations

import ast
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = REPO_ROOT / "notebooks" / "feedback_generator.ipynb"


def test_feedback_notebook_is_a_stripped_inspection_wrapper() -> None:
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    code = "\n".join(
        "".join(cell.get("source", []))
        for cell in notebook["cells"]
        if cell.get("cell_type") == "code"
    )

    imported: set[str] = set()
    for cell in notebook["cells"]:
        if cell.get("cell_type") == "code":
            assert cell.get("execution_count") is None
            assert cell.get("outputs") == []
            tree = ast.parse("".join(cell.get("source", [])))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])

    assert "dx_chat_entropy" in imported
    assert "openai" not in imported
    assert "OpenAI(" not in code
    assert "chat.completions" not in code
    assert "responses.create" not in code
    assert "generate_overall_gen_prompt" not in code
    assert "generate_diff_spec_prompt" not in code
