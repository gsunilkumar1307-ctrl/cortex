from __future__ import annotations

from typing import Any, Callable

from .adapter import MCPToolAdapter
from .filesystem_adapter import MCPFilesystemToolAdapter
from .filesystem_jail import FilesystemPathJail
from .filesystem_policy import FilesystemPermissionPolicy
from .fetch_policy import FetchSecurityPolicy
from .playwright_policy import PlaywrightSecurityPolicy
from .manager import MCPServerManager
from .models import MCPToolDefinition

try:
    from backend.tools.registry import ToolDefinition, ToolRegistry
except ImportError:
    from tools.registry import ToolDefinition, ToolRegistry


class MCPRegistryBridge:
    """
    Bridges discovered MCP tools into Cortex's authoritative ToolRegistry.
    Handles dynamic registration, conflict resolution, alias mapping,
    specialized server adapters (e.g. MCPFilesystemToolAdapter, MCPFetchToolAdapter),
    and duplicate registration prevention on reconnection.
    """

    def __init__(
        self,
        manager: MCPServerManager,
        tool_registry: ToolRegistry,
        filesystem_jail: FilesystemPathJail | None = None,
        filesystem_policy: FilesystemPermissionPolicy | None = None,
        fetch_policy: FetchSecurityPolicy | None = None,
        playwright_policy: PlaywrightSecurityPolicy | None = None,
    ) -> None:
        self.manager = manager
        self.tool_registry = tool_registry
        self.filesystem_jail = filesystem_jail
        self.filesystem_policy = filesystem_policy
        self.fetch_policy = fetch_policy or FetchSecurityPolicy()
        self.playwright_policy = playwright_policy or PlaywrightSecurityPolicy()
        self._registered_tools: dict[str, str] = {}  # tool_canonical_name -> server_name
        self._registered_aliases: dict[str, str] = {}  # alias_name -> server_name

    def sync_all_tools(self) -> int:
        """Syncs all discovered tools from all managed servers into ToolRegistry."""
        count = 0
        definitions = self.manager.get_tool_definitions()
        for defn in definitions:
            self._register_single_tool(defn)
            count += 1
        return count

    def sync_tools(self) -> int:
        """Alias for sync_all_tools for orchestrator compatibility."""
        return self.sync_all_tools()

    def sync_server_tools(self, server_name: str) -> int:
        """Syncs discovered tools from a specific server into ToolRegistry."""
        count = 0
        definitions = self.manager.get_tool_definitions(server_name)
        for defn in definitions:
            self._register_single_tool(defn)
            count += 1
        return count

    def _create_adapter(self, defn: MCPToolDefinition, namespaced_name: str) -> MCPToolAdapter:
        """Instantiates the appropriate tool adapter depending on server type."""
        if defn.server_name == "filesystem":
            return MCPFilesystemToolAdapter(
                definition=defn,
                manager=self.manager,
                namespaced_name=namespaced_name,
                jail=self.filesystem_jail,
                policy=self.filesystem_policy,
            )
        elif defn.server_name == "fetch":
            from .fetch_adapter import MCPFetchToolAdapter
            return MCPFetchToolAdapter(
                definition=defn,
                manager=self.manager,
                namespaced_name=namespaced_name,
                policy=self.fetch_policy,
            )
        elif defn.server_name == "agent-browser":
            from .agent_browser_adapter import MCPAgentBrowserToolAdapter
            return MCPAgentBrowserToolAdapter(
                definition=defn,
                manager=self.manager,
                namespaced_name=namespaced_name,
                policy=self.playwright_policy,
            )
        elif defn.server_name == "playwright":
            from .playwright_adapter import MCPPlaywrightToolAdapter
            return MCPPlaywrightToolAdapter(
                definition=defn,
                manager=self.manager,
                namespaced_name=namespaced_name,
                policy=self.playwright_policy,
            )
        return MCPToolAdapter(defn, self.manager, namespaced_name=namespaced_name)

    def _register_single_tool(self, defn: MCPToolDefinition) -> None:
        """Registers an MCP tool as an MCPToolAdapter in ToolRegistry."""
        canonical_name = f"mcp__{defn.server_name}__{defn.name}"

        # 1. Instantiate the appropriate adapter
        adapter = self._create_adapter(defn, canonical_name)

        # 2. Register into instances dictionary in ToolRegistry
        self.tool_registry.register_instance(canonical_name, adapter)

        # 3. Register ToolDefinition metadata in ToolRegistry
        tool_def = ToolDefinition(
            name=canonical_name,
            description=f"[MCP:{defn.server_name}] {defn.description}",
            expected_state_desc=f"MCP tool '{defn.name}' on server '{defn.server_name}' completed with verified output.",
            parameters=defn.input_schema,
        )
        self.tool_registry.register(tool_def)

        # 4. If the tool name does not collide with a native tool, register an alias
        # E.g., if "read_file" -> "mcp_read_file"
        alias_name = f"mcp_{defn.name}"
        alias_adapter = self._create_adapter(defn, alias_name)
        self.tool_registry.register_instance(alias_name, alias_adapter)
        if not self.tool_registry.get(alias_name):
            alias_def = ToolDefinition(
                name=alias_name,
                description=f"[MCP] {defn.description}",
                expected_state_desc=tool_def.expected_state_desc,
                parameters=defn.input_schema,
            )
            self.tool_registry.register(alias_def)
            self._registered_aliases[alias_name] = defn.server_name

        # 5. Direct registration for official agent_browser tools into ToolRegistry
        if defn.server_name == "agent-browser":
            direct_name = defn.name
            direct_adapter = self._create_adapter(defn, direct_name)
            self.tool_registry.register_instance(direct_name, direct_adapter)
            if not self.tool_registry.get(direct_name):
                direct_def = ToolDefinition(
                    name=direct_name,
                    description=f"[AgentBrowser] {defn.description}",
                    expected_state_desc=tool_def.expected_state_desc,
                    parameters=defn.input_schema,
                )
                self.tool_registry.register(direct_def)
                self._registered_aliases[direct_name] = defn.server_name

            # Map primary Cortex browser execution aliases to agent-browser
            if defn.name == "agent_browser_open":
                browser_adapter = self._create_adapter(defn, "browser_tool")
                self.tool_registry.register_instance("browser_tool", browser_adapter)
                nav_adapter = self._create_adapter(defn, "mcp_browser_navigate")
                self.tool_registry.register_instance("mcp_browser_navigate", nav_adapter)
            elif defn.name == "agent_browser_snapshot":
                snap_adapter = self._create_adapter(defn, "mcp_browser_snapshot")
                self.tool_registry.register_instance("mcp_browser_snapshot", snap_adapter)
            elif defn.name == "agent_browser_click":
                click_adapter = self._create_adapter(defn, "mcp_browser_click")
                self.tool_registry.register_instance("mcp_browser_click", click_adapter)
            elif defn.name in ("agent_browser_fill", "agent_browser_type"):
                type_adapter = self._create_adapter(defn, "mcp_browser_type")
                self.tool_registry.register_instance("mcp_browser_type", type_adapter)
            elif defn.name == "agent_browser_close":
                close_adapter = self._create_adapter(defn, "mcp_browser_close")
                self.tool_registry.register_instance("mcp_browser_close", close_adapter)

        # 6. For Playwright MCP (legacy fallback if enabled), register browser_tool
        if defn.server_name == "playwright" and defn.name == "browser_navigate":
            browser_adapter = self._create_adapter(defn, "browser_tool")
            self.tool_registry.register_instance("browser_tool", browser_adapter)

        self._registered_tools[canonical_name] = defn.server_name

    def unregister_server_tools(self, server_name: str) -> int:
        """Removes all registered tools associated with a server."""
        removed = 0
        for canonical_name, srv in list(self._registered_tools.items()):
            if srv == server_name:
                if canonical_name in self.tool_registry._instances:
                    del self.tool_registry._instances[canonical_name]
                if canonical_name in self.tool_registry._tools:
                    del self.tool_registry._tools[canonical_name]
                self._registered_tools.pop(canonical_name, None)
                removed += 1

        for alias_name, srv in list(self._registered_aliases.items()):
            if srv == server_name:
                if alias_name in self.tool_registry._instances:
                    del self.tool_registry._instances[alias_name]
                if alias_name in self.tool_registry._tools:
                    del self.tool_registry._tools[alias_name]
                self._registered_aliases.pop(alias_name, None)

        return removed
