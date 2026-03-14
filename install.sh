#!/bin/bash
# Install jupyter-notebook-mcp for Claude Code
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

claude mcp add jupyter -s user -- python "$SCRIPT_DIR/server.py"

echo "Installed. Restart Claude Code to use the jupyter MCP tools."
