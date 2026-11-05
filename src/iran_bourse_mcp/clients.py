"""Install snippets and (safe) auto-install for MCP-capable agents and IDEs.

One table drives the ``config``/``install`` commands, the README and the website
(``scripts/gen_site_data.py`` exports it), so the instructions cannot drift apart.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

SERVER_NAME = "iran-bourse"
GIT_SOURCE = "git+https://github.com/msmahdinejad/iran-bourse-mcp"
ENTRY_POINT = "iran-bourse-mcp"


def source() -> str:
    """Where ``uvx`` should fetch the package from: PyPI, unless ``IRAN_BOURSE_SOURCE`` names another source (for example ``GIT_SOURCE``)."""
    return os.environ.get("IRAN_BOURSE_SOURCE", "pypi")


def launch(src: str | None = None) -> tuple[str, list[str]]:
    src = src or source()
    if src == "pypi":
        return "uvx", [ENTRY_POINT]
    return "uvx", ["--from", src, ENTRY_POINT]


def shell_command(src: str | None = None) -> str:
    cmd, args = launch(src)
    return " ".join([cmd, *(shlex.quote(a) for a in args)])


def stdio_entry(src: str | None = None, *, with_type: bool = False) -> dict[str, Any]:
    cmd, args = launch(src)
    entry: dict[str, Any] = {"command": cmd, "args": args}
    if with_type:
        entry = {"type": "stdio", **entry}
    return entry


@dataclass(frozen=True)
class Client:
    id: str
    label: str
    group: str  # cli | ide | desktop | framework
    note: str = ""
    docs: str = ""
    # how it is configured
    config_key: str | None = None  # JSON top-level key holding the servers
    type_field: bool = False  # entries need "type": "stdio"
    paths: dict[str, str] = field(default_factory=dict)  # os -> path (supports ~ and %APPDATA%)
    auto_install: bool = False  # `install` may merge into the JSON file
    command: str | None = None  # a one-liner that registers the server (when the client has a CLI)

    def config_path(self) -> Path | None:
        raw = self.paths.get(_os_key()) or self.paths.get("all")
        if not raw:
            return None
        return Path(os.path.expandvars(os.path.expanduser(raw)))


def _os_key() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _clients() -> list[Client]:
    mcp_cmd = shell_command()
    return [
        Client(
            "claude-code", "Claude Code", "cli",
            docs="https://docs.claude.com/en/docs/claude-code/mcp",
            command=f"claude mcp add {SERVER_NAME} -- {mcp_cmd}",
            note="Add `--scope user` to make it available in every project.",
        ),
        Client(
            "claude-desktop", "Claude Desktop", "desktop", config_key="mcpServers", auto_install=True,
            docs="https://modelcontextprotocol.io/quickstart/user",
            paths={
                "windows": "%APPDATA%/Claude/claude_desktop_config.json",
                "macos": "~/Library/Application Support/Claude/claude_desktop_config.json",
                "linux": "~/.config/Claude/claude_desktop_config.json",
            },
            note="Restart Claude Desktop after editing the file.",
        ),
        Client(
            "codex", "OpenAI Codex CLI", "cli",
            docs="https://developers.openai.com/codex/mcp",
            command=f"codex mcp add {SERVER_NAME} -- {mcp_cmd}",
            paths={"all": "~/.codex/config.toml"},
            note="`uvx --version` must work in the shell that starts Codex. For scripted `codex exec` runs use the config.toml form (required = true), "
                 "or `uv tool install` the package so the server starts in about a second.",
        ),
        Client(
            "gemini-cli", "Gemini CLI", "cli", config_key="mcpServers", auto_install=True,
            docs="https://github.com/google-gemini/gemini-cli/blob/main/docs/tools/mcp-server.md",
            paths={"all": "~/.gemini/settings.json"},
        ),
        Client(
            "cursor", "Cursor", "ide", config_key="mcpServers", auto_install=True,
            docs="https://cursor.com/docs/mcp",
            paths={"all": "~/.cursor/mcp.json"},
            note="Restart Cursor after editing. A one-click install link is available (see `config cursor`).",
        ),
        Client(
            "vscode", "VS Code (GitHub Copilot)", "ide", config_key="servers", type_field=True,
            docs="https://code.visualstudio.com/docs/copilot/customization/mcp-servers",
            paths={"all": ".vscode/mcp.json"},
            note="Project-level file. Top-level key is `servers`, not `mcpServers`.",
        ),
        Client(
            "windsurf", "Windsurf", "ide", config_key="mcpServers", auto_install=True,
            docs="https://docs.windsurf.com/windsurf/cascade/mcp",
            paths={"all": "~/.codeium/windsurf/mcp_config.json"},
            note="Newer releases may relocate the file; open it from Cascade's MCP panel if this path is missing.",
        ),
        Client(
            "cline", "Cline", "ide", config_key="mcpServers",
            docs="https://docs.cline.bot/mcp/configuring-mcp-servers",
            note="Open the MCP Servers panel, choose *Configure MCP Servers*, and paste the entry into the JSON it opens.",
        ),
        Client(
            "roo-code", "Roo Code", "ide", config_key="mcpServers",
            docs="https://docs.roocode.com/features/mcp/using-mcp-in-roo",
            paths={"all": ".roo/mcp.json"},
            note="Project file shown; the global file is opened from the MCP settings view.",
        ),
        Client(
            "kiro", "Kiro", "ide", config_key="mcpServers", auto_install=True,
            docs="https://kiro.dev/docs/mcp/",
            paths={"all": "~/.kiro/settings/mcp.json"},
        ),
        Client(
            "qwen-code", "Qwen Code", "cli", config_key="mcpServers", auto_install=True,
            docs="https://qwenlm.github.io/qwen-code-docs/en/users/features/mcp/",
            paths={"all": "~/.qwen/settings.json"},
        ),
        Client(
            "jetbrains", "JetBrains AI Assistant", "ide", config_key="mcpServers",
            docs="https://www.jetbrains.com/help/ai-assistant/mcp.html",
            note="Settings > Tools > AI Assistant > Model Context Protocol (MCP) > Add, then paste the JSON.",
        ),
        Client(
            "zed", "Zed", "ide", config_key="context_servers",
            docs="https://zed.dev/docs/ai/mcp",
            paths={"all": "~/.config/zed/settings.json"},
            note="Older Zed versions expect `command` as an object: {\"path\": ..., \"args\": [...]}.",
        ),
        Client(
            "opencode", "OpenCode", "cli", config_key="mcp",
            docs="https://opencode.ai/docs/mcp-servers",
            paths={"all": "~/.config/opencode/opencode.json"},
            note="OpenCode uses `command` as one array and `type: local`.",
        ),
        Client(
            "goose", "Goose", "cli",
            docs="https://block.github.io/goose/docs/getting-started/using-extensions",
            note="Or run `goose configure` > Add Extension > Command-line Extension and enter the command below.",
        ),
        Client(
            "amp", "Amp", "cli", config_key="amp.mcpServers",
            docs="https://ampcode.com/manual/mcp",
            paths={"all": "~/.config/amp/settings.json"},
        ),
        Client(
            "generic", "Any MCP client (stdio)", "framework",
            note="Command: `uvx`, arguments as shown. Works in every client that can launch a stdio MCP server.",
        ),
    ]


def all_clients() -> list[Client]:
    return _clients()


def get_client(client_id: str) -> Client:
    for client in _clients():
        if client.id == client_id:
            return client
    names = ", ".join(c.id for c in _clients())
    raise KeyError(f"Unknown client {client_id!r}. Choose one of: {names}")


# --------------------------------------------------------------------------- snippets
def entry_for(client: Client, src: str | None = None) -> dict[str, Any]:
    """The server entry in the shape this client expects."""
    cmd, args = launch(src)
    if client.id == "opencode":
        return {"type": "local", "command": [cmd, *args], "enabled": True}
    if client.id == "vscode":
        return stdio_entry(src, with_type=True)
    return stdio_entry(src)


def cursor_deeplink(src: str | None = None) -> str:
    payload = json.dumps(stdio_entry(src), separators=(",", ":")).encode()
    return f"cursor://anysphere.cursor-deeplink/mcp/install?name={SERVER_NAME}&config={base64.b64encode(payload).decode()}"


def vscode_deeplink(src: str | None = None, *, insiders: bool = False) -> str:
    config = json.dumps({"name": SERVER_NAME, **stdio_entry(src, with_type=True)}, separators=(",", ":"))
    return f"{'vscode-insiders' if insiders else 'vscode'}:mcp/install?{quote(config)}"


def goose_deeplink(src: str | None = None) -> str:
    cmd, args = launch(src)
    parts = [f"cmd={quote(cmd)}", *(f"arg={quote(a, safe='')}" for a in args)]
    parts += [f"id={SERVER_NAME}", "name=Iran%20Bourse", "description=" + quote("Tehran Stock Exchange and Codal data")]
    return "goose://extension?" + "&".join(parts)


def snippet(client_id: str, src: str | None = None) -> str:
    """Human-readable setup text for a client (what ``config <client>`` prints)."""
    client = get_client(client_id)
    cmd, args = launch(src)
    lines: list[str] = []

    if client.command:
        lines += ["# Run once in your terminal:", client.command, ""]
    if client_id == "codex":
        toml_args = ", ".join(json.dumps(a) for a in args)
        lines += [
            f"# or add to {client.paths['all']}:", f"[mcp_servers.{SERVER_NAME}]", f'command = "{cmd}"', f"args = [{toml_args}]",
            "startup_timeout_sec = 60  # the first start downloads the packages",
            "required = true           # `codex exec` waits for the server instead of starting its first turn without the tools",
            "",
        ]
    elif client_id == "goose":
        lines += ["# One-click link:", goose_deeplink(src), "", "# or in `goose configure`, use this command:", shell_command(src), ""]
    elif client_id == "generic":
        lines += [f"command: {cmd}", f"args: {json.dumps(args)}", "", "# JSON form used by most clients:",
                  json.dumps({"mcpServers": {SERVER_NAME: stdio_entry(src)}}, indent=2), ""]
    elif client.config_key:
        body: Any = {client.config_key: {SERVER_NAME: entry_for(client, src)}}
        path = client.config_path()
        if path is not None:
            lines.append(f"# Put this in {path}:")
        lines.append(json.dumps(body, indent=2))
        lines.append("")
    if client_id == "cursor":
        lines += ["# One-click install (paste in a browser):", cursor_deeplink(src), ""]
    if client_id == "vscode":
        lines += ["# One-click install:", vscode_deeplink(src), "", "# or from a terminal:",
                  f"code --add-mcp '{json.dumps({'name': SERVER_NAME, **stdio_entry(src, with_type=True)}, separators=(',', ':'))}'", ""]
    if client.note:
        lines.append(f"# Note: {client.note}")
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------- auto install
class InstallError(RuntimeError):
    pass


def install(client_id: str, *, src: str | None = None, dry_run: bool = False, path: Path | None = None) -> str:
    """Merge the server into the client's JSON config file. Never overwrites unreadable files."""
    client = get_client(client_id)
    if not client.auto_install or not client.config_key:
        raise InstallError(
            f"Automatic install is not offered for {client.label}. Run `iran-bourse-mcp config {client_id}` "
            "and follow the printed steps."
        )
    target = path or client.config_path()
    if target is None:
        raise InstallError(f"No known config path for {client.label} on this OS.")

    data: dict[str, Any] = {}
    if target.exists():
        raw = target.read_text(encoding="utf-8")
        if raw.strip():
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise InstallError(
                    f"{target} is not plain JSON ({exc.msg} at line {exc.lineno}). Not touching it. "
                    f"Add the entry manually: iran-bourse-mcp config {client_id}"
                ) from exc
        if not isinstance(data, dict):
            raise InstallError(f"{target} does not contain a JSON object. Not touching it.")

    servers = data.setdefault(client.config_key, {})
    if not isinstance(servers, dict):
        raise InstallError(f"{target}: '{client.config_key}' is not an object. Not touching it.")
    already = SERVER_NAME in servers
    servers[SERVER_NAME] = entry_for(client, src)
    rendered = json.dumps(data, indent=2, ensure_ascii=False) + "\n"

    action = "update" if already else "add"
    if dry_run:
        return f"[dry run] would {action} '{SERVER_NAME}' in {target}:\n{rendered}"

    target.parent.mkdir(parents=True, exist_ok=True)
    backup = ""
    if target.exists():
        stamp = dt.datetime.now().strftime("%Y%m%d%H%M%S")
        backup_path = target.with_name(f"{target.name}.bak-{stamp}")
        backup_path.write_bytes(target.read_bytes())
        backup = f" (backup: {backup_path.name})"
    target.write_text(rendered, encoding="utf-8")
    return f"{'Updated' if already else 'Added'} '{SERVER_NAME}' in {target}{backup}. Restart {client.label} to load it."


# --------------------------------------------------------------------------- frameworks & shell
def frameworks(src: str | None = None) -> list[dict[str, str]]:
    """Ready-to-paste snippets for Python agent frameworks and for agents that have no MCP support."""
    cmd, args = launch(src)
    arg_list = json.dumps(args)
    runner = shell_command(src)
    return [
        {
            "id": "openai-agents", "label": "OpenAI Agents SDK", "language": "python",
            "snippet": (
                "from agents import Agent\nfrom agents.mcp import MCPServerStdio\n\n"
                f'async with MCPServerStdio(params={{"command": "{cmd}", "args": {arg_list}}}) as bourse:\n'
                '    agent = Agent(name="Analyst", instructions="Answer with exchange data.", mcp_servers=[bourse])\n'
            ),
        },
        {
            "id": "langchain", "label": "LangChain", "language": "python",
            "snippet": (
                "from langchain_mcp_adapters.client import MultiServerMCPClient\n\n"
                "client = MultiServerMCPClient({\n"
                f'    "{SERVER_NAME}": {{"transport": "stdio", "command": "{cmd}", "args": {arg_list}}}\n'
                "})\ntools = await client.get_tools()\n"
            ),
        },
        {
            "id": "claude-agent-sdk", "label": "Claude Agent SDK", "language": "python",
            "snippet": (
                "from claude_agent_sdk import ClaudeAgentOptions\n\n"
                f'options = ClaudeAgentOptions(mcp_servers={{"{SERVER_NAME}": {{"command": "{cmd}", "args": {arg_list}}}}})\n'
            ),
        },
        {
            "id": "shell", "label": "No MCP support? Use the shell", "language": "bash",
            "snippet": (
                "# Any agent that can run commands can use every tool:\n"
                f"{runner} tools\n"
                f"{runner} call quote symbol=فولاد --compact\n"
                f"{runner} call top_movers kind=buy_queue limit=5 --compact\n"
            ),
        },
    ]
