# jupyter-notebook-mcp

MCP server for reading and editing Jupyter notebooks (`.ipynb` files). Operates directly on the file — no running Jupyter server required.

## Why

LLMs choke on raw `.ipynb` JSON. Cell sources are wrapped in arrays of line-strings, outputs contain huge base64 images and training logs, and metadata is everywhere. A 200-line notebook becomes a 5000-line JSON blob.

This server exposes notebook cells as clean text, so an LLM can list cells, read specific ones, search across sources, and edit — all without ingesting the full file.

### Context savings

Measured against real notebooks with training logs, evaluation outputs, and plots:

| Operation | Raw `.ipynb` | MCP tool | Reduction |
|-----------|-------------|----------|-----------|
| Orient (list cells) | 111K chars | 1.1K chars | **~100x** |
| Read one cell | 111K chars | ~500 chars | **~200x** |
| Search | 111K chars | matches only | **~500x** |

Notebooks with large outputs (plots, training logs) see even bigger savings — up to **630x** for `list_cells` on output-heavy notebooks.

## Tools

| Tool | Description |
|------|-------------|
| `notebook_list_cells` | List all cells with index, ID, type, and first line |
| `notebook_read_cell` | Read source of a single cell (no outputs) |
| `notebook_read_cell_output` | Read output of a single cell |
| `notebook_edit_cell` | Replace cell source (clears outputs) |
| `notebook_search` | Regex search across cell sources (optionally outputs) |
| `notebook_add_cell` | Add a new code or markdown cell |
| `notebook_delete_cell` | Delete a cell by ID or index |

## Install for Claude Code

```bash
git clone https://github.com/cohen990/jupyter-notebook-mcp.git
cd jupyter-notebook-mcp
./install.sh
```

Then restart Claude Code.

The install script runs `claude mcp add` to register the server. You can also do it manually:

```bash
claude mcp add jupyter -s user -- python /path/to/jupyter-notebook-mcp/server.py
```

## Usage with other MCP clients

The server uses stdio transport. Any MCP-compatible client can connect:

```bash
python server.py
```

## Vibe coded

This project was fully vibe coded with [Claude Code](https://claude.com/claude-code).

## License

MIT
