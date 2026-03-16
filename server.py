"""MCP server for reading and editing Jupyter notebooks (.ipynb files).

File-based — no running Jupyter server required. Operates directly on the
.ipynb JSON structure, stripping outputs and metadata noise so LLM context
stays focused on code and markdown.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("jupyter-notebook-mcp")


def _load_notebook(path: str) -> dict:
    """Load and validate a notebook file."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"Notebook not found: {p}")
    if p.suffix != ".ipynb":
        raise ValueError(f"Not a notebook file: {p}")
    with open(p) as f:
        return json.load(f)


def _save_notebook(path: str, nb: dict) -> None:
    """Write notebook back to disk."""
    p = Path(path).expanduser().resolve()
    with open(p, "w") as f:
        json.dump(nb, f, indent=1, ensure_ascii=False)
        f.write("\n")


def _cell_source(cell: dict) -> str:
    """Extract cell source as a single string."""
    src = cell.get("source", "")
    if isinstance(src, list):
        return "".join(src)
    return src


def _cell_id(cell: dict, index: int) -> str:
    """Get cell ID, falling back to index."""
    return cell.get("id", str(index))


def _source_hash(source: str) -> str:
    """Short hash of cell source for edit verification."""
    return hashlib.sha256(source.encode()).hexdigest()[:12]


def _find_cell(nb: dict, cell_id: str) -> tuple[int, dict]:
    """Find a cell by ID or index. Returns (index, cell)."""
    # Try as integer index first
    try:
        idx = int(cell_id)
        cells = nb.get("cells", [])
        if 0 <= idx < len(cells):
            return idx, cells[idx]
    except ValueError:
        pass

    # Search by cell ID
    for i, cell in enumerate(nb.get("cells", [])):
        if cell.get("id") == cell_id:
            return i, cell

    raise ValueError(f"Cell not found: {cell_id}")


@mcp.tool()
def notebook_create(path: str, cells: list[dict]) -> str:
    """Create a new notebook from a list of cell definitions.

    Each cell dict should have:
        - source: The cell content (code or markdown)
        - cell_type: "code" or "markdown" (default: "code")
        - id: Optional cell ID

    Args:
        path: Path for the new .ipynb file
        cells: List of cell dicts with 'source' and optional 'cell_type'/'id'
    """
    p = Path(path).expanduser().resolve()
    if p.exists():
        raise FileExistsError(f"Notebook already exists: {p}")
    if p.suffix != ".ipynb":
        raise ValueError(f"Path must end in .ipynb: {p}")

    nb_cells = []
    for i, cell_def in enumerate(cells):
        source = cell_def.get("source", "")
        cell_type = cell_def.get("cell_type", "code")
        cell_id = cell_def.get("id")

        lines = source.split("\n")
        cell = {
            "cell_type": cell_type,
            "source": [line + "\n" for line in lines[:-1]] + [lines[-1]],
            "metadata": {},
        }
        if cell_id:
            cell["id"] = cell_id
        if cell_type == "code":
            cell["outputs"] = []
            cell["execution_count"] = None

        nb_cells.append(cell)

    nb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python"},
        },
        "cells": nb_cells,
    }

    _save_notebook(path, nb)
    return f"Created notebook {p} with {len(nb_cells)} cells"


@mcp.tool()
def notebook_list_cells(path: str) -> str:
    """List all cells in a notebook with their index, ID, type, and first line.

    Returns a compact overview without cell contents — use this to orient
    before reading specific cells.

    Args:
        path: Path to the .ipynb file
    """
    nb = _load_notebook(path)
    lines = []
    for i, cell in enumerate(nb.get("cells", [])):
        cid = _cell_id(cell, i)
        ctype = cell.get("cell_type", "unknown")
        src = _cell_source(cell).strip()
        first_line = src.split("\n")[0][:120] if src else "(empty)"
        lines.append(f"[{i}] ({ctype}) id={cid}  {first_line}")
    return "\n".join(lines)


@mcp.tool()
def notebook_read_cell(path: str, cell_id: str) -> str:
    """Read the source of a single cell. No outputs, no metadata — just code or markdown.

    Args:
        path: Path to the .ipynb file
        cell_id: Cell ID or integer index
    """
    nb = _load_notebook(path)
    idx, cell = _find_cell(nb, cell_id)
    ctype = cell.get("cell_type", "unknown")
    cid = _cell_id(cell, idx)
    src = _cell_source(cell)
    h = _source_hash(src)
    return f"Cell [{idx}] ({ctype}) id={cid} hash={h}\n\n{src}"


@mcp.tool()
def notebook_read_cell_output(path: str, cell_id: str) -> str:
    """Read the output of a single cell. Use sparingly — outputs can be large.

    Args:
        path: Path to the .ipynb file
        cell_id: Cell ID or integer index
    """
    nb = _load_notebook(path)
    idx, cell = _find_cell(nb, cell_id)
    outputs = cell.get("outputs", [])
    if not outputs:
        return f"Cell [{idx}]: no outputs"

    parts = []
    for out in outputs:
        otype = out.get("output_type", "unknown")
        if otype == "stream":
            text = out.get("text", "")
            if isinstance(text, list):
                text = "".join(text)
            parts.append(text)
        elif otype in ("execute_result", "display_data"):
            data = out.get("data", {})
            if "text/plain" in data:
                text = data["text/plain"]
                if isinstance(text, list):
                    text = "".join(text)
                parts.append(text)
            if "image/png" in data:
                parts.append("[image/png output]")
            if "text/html" in data:
                parts.append("[text/html output]")
        elif otype == "error":
            parts.append(
                f"ERROR: {out.get('ename', '')}: {out.get('evalue', '')}"
            )
        else:
            parts.append(f"[{otype}]")

    return f"Cell [{idx}] output:\n\n" + "\n".join(parts)


@mcp.tool()
def notebook_edit_cell(
    path: str, cell_id: str, new_source: str, source_hash: str,
    cell_type: str | None = None,
) -> str:
    """Replace the source of a single cell.

    Requires source_hash from a prior notebook_read_cell call. This ensures
    you have read the cell before editing it and that it hasn't changed since.

    Args:
        path: Path to the .ipynb file
        cell_id: Cell ID or integer index
        new_source: The new cell source code/markdown
        source_hash: Hash from notebook_read_cell (prevents blind edits)
        cell_type: Optionally change cell type ("code" or "markdown")
    """
    nb = _load_notebook(path)
    idx, cell = _find_cell(nb, cell_id)
    old_source = _cell_source(cell)
    expected_hash = _source_hash(old_source)

    if source_hash != expected_hash:
        raise ValueError(
            f"Hash mismatch for cell [{idx}]: expected {expected_hash}, "
            f"got {source_hash}. Read the cell first with notebook_read_cell."
        )

    # Store source as list of lines (notebook convention)
    lines = new_source.split("\n")
    cell["source"] = [line + "\n" for line in lines[:-1]] + [lines[-1]]

    if cell_type and cell_type in ("code", "markdown", "raw"):
        cell["cell_type"] = cell_type

    # Clear outputs since source changed
    if cell.get("cell_type") == "code":
        cell["outputs"] = []
        cell["execution_count"] = None

    _save_notebook(path, nb)
    new_hash = _source_hash(new_source)
    return f"Updated cell [{idx}] (id={_cell_id(cell, idx)}) hash={new_hash}"


@mcp.tool()
def notebook_search(path: str, pattern: str, include_outputs: bool = False) -> str:
    """Search cell sources (and optionally outputs) for a regex pattern.

    Returns matching cell IDs and the matching lines — much cheaper than
    reading the whole notebook.

    Args:
        path: Path to the .ipynb file
        pattern: Regex pattern to search for
        include_outputs: Also search cell outputs (default: False)
    """
    nb = _load_notebook(path)
    regex = re.compile(pattern, re.IGNORECASE)
    results = []

    for i, cell in enumerate(nb.get("cells", [])):
        cid = _cell_id(cell, i)
        ctype = cell.get("cell_type", "unknown")
        src = _cell_source(cell)

        matches = []
        for line_num, line in enumerate(src.split("\n"), 1):
            if regex.search(line):
                matches.append(f"  L{line_num}: {line.rstrip()}")

        if include_outputs and cell.get("cell_type") == "code":
            for out in cell.get("outputs", []):
                text = ""
                if out.get("output_type") == "stream":
                    text = out.get("text", "")
                elif out.get("output_type") in ("execute_result", "display_data"):
                    text = out.get("data", {}).get("text/plain", "")
                if isinstance(text, list):
                    text = "".join(text)
                for line in text.split("\n"):
                    if regex.search(line):
                        matches.append(f"  [output]: {line.rstrip()}")

        if matches:
            results.append(f"[{i}] ({ctype}) id={cid}\n" + "\n".join(matches))

    if not results:
        return f"No matches for '{pattern}'"
    return "\n\n".join(results)


@mcp.tool()
def notebook_add_cell(
    path: str,
    source: str,
    cell_type: str = "code",
    position: int = -1,
) -> str:
    """Add a new cell to the notebook.

    Args:
        path: Path to the .ipynb file
        source: Cell source code/markdown
        cell_type: "code", "markdown", or "raw" (default: "code")
        position: Index to insert at (-1 = end)
    """
    nb = _load_notebook(path)
    cells = nb.setdefault("cells", [])

    lines = source.split("\n")
    new_cell = {
        "cell_type": cell_type,
        "source": [line + "\n" for line in lines[:-1]] + [lines[-1]],
        "metadata": {},
    }
    if cell_type == "code":
        new_cell["outputs"] = []
        new_cell["execution_count"] = None

    if position < 0 or position >= len(cells):
        cells.append(new_cell)
        idx = len(cells) - 1
    else:
        cells.insert(position, new_cell)
        idx = position

    _save_notebook(path, nb)
    return f"Added {cell_type} cell at position [{idx}]"


@mcp.tool()
def notebook_delete_cell(path: str, cell_id: str) -> str:
    """Delete a cell from the notebook.

    Args:
        path: Path to the .ipynb file
        cell_id: Cell ID or integer index
    """
    nb = _load_notebook(path)
    idx, cell = _find_cell(nb, cell_id)
    nb["cells"].pop(idx)
    _save_notebook(path, nb)
    return f"Deleted cell [{idx}] (id={_cell_id(cell, idx)})"


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
