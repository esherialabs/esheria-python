from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tomllib

from api.clients.esheria_regulatory.config import EsheriaClientConfig
from api.clients.esheria_regulatory.version import CLI_USER_AGENT, MCP_USER_AGENT, PACKAGE_VERSION, PYTHON_USER_AGENT
from api.mcp.esheria_mcp.tools import ALL_TOOL_NAMES, DIRECTORY_TOOL_NAMES, READ_TOOL_NAMES


ROOT = Path(__file__).resolve().parents[1]


def test_release_metadata_and_provenance_agree() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    registry = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    provenance = json.loads((ROOT / "RELEASE_PROVENANCE.json").read_text(encoding="utf-8"))

    assert project["name"] == "esheria"
    assert project["version"] == PACKAGE_VERSION == registry["version"] == provenance["package_version"]
    assert project["license"] == "Apache-2.0"
    assert project["urls"]["Source"] == "https://github.com/esherialabs/esheria-python"
    assert registry["name"] == "io.github.esherialabs/esheria"
    assert "<!-- mcp-name: io.github.esherialabs/esheria -->" in (ROOT / "README.md").read_text(encoding="utf-8")
    publisher = registry["_meta"]["io.modelcontextprotocol.registry/publisher-provided"]
    assert publisher["documentationUrl"] == "https://docs.esheria.ai/agent-tools/mcp"
    assert publisher["privacyPolicyUrl"] == "https://esheria.ai/privacy"
    assert publisher["termsOfServiceUrl"] == "https://esheria.ai/terms"
    assert publisher["toolCatalogs"] == {
        "hostedOAuthReadOnly": 20,
        "dataTokenReadLike": 29,
        "operatorMaximum": 37,
    }
    assert isinstance(provenance["publishable"], bool)
    assert provenance["publishable"] is provenance["source_tree_clean"]


def test_scoped_mcp_catalog_counts_are_stable() -> None:
    assert len(DIRECTORY_TOOL_NAMES) == 20
    assert len(READ_TOOL_NAMES) == 29
    assert len(ALL_TOOL_NAMES) == 37


def test_public_client_user_agents_are_versioned_and_distinct() -> None:
    assert EsheriaClientConfig().user_agent == PYTHON_USER_AGENT == f"esheria-python/{PACKAGE_VERSION}"
    assert CLI_USER_AGENT == f"esheria-cli/{PACKAGE_VERSION}"
    assert MCP_USER_AGENT == f"esheria-mcp/{PACKAGE_VERSION}"
    assert len({PYTHON_USER_AGENT, CLI_USER_AGENT, MCP_USER_AGENT}) == 3


def test_installed_command_modules_expose_help_without_credentials() -> None:
    commands = (
        [sys.executable, "-m", "api.cli.esheria", "--version"],
        [sys.executable, "-m", "api.cli.esheria", "mcp", "serve", "--help"],
        [sys.executable, "-m", "api.mcp.esheria_mcp", "--help"],
    )
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_public_tree_excludes_private_monorepo_domains() -> None:
    forbidden = {"dashboard", "docs", "infra", "pipeline", "regulatory_data_model", "regulations"}
    assert not ({path.name for path in ROOT.iterdir()} & forbidden)
