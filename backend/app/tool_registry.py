from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    id: str
    toolkit: str
    name: str
    description: str
    icon: str
    color: str


TOOLS = (
    ToolDefinition(
        "gmail",
        "gmail",
        "Gmail",
        "Read, search, and send emails",
        "mail-outline",
        "#EA4335",
    ),
    ToolDefinition(
        "calendar",
        "googlecalendar",
        "Google Calendar",
        "Create and manage daily events",
        "calendar-outline",
        "#4285F4",
    ),
    ToolDefinition(
        "drive",
        "googledrive",
        "Google Drive",
        "Search, read, and organize files in Drive",
        "folder-open-outline",
        "#0F9D58",
    ),
    ToolDefinition(
        "docs",
        "googledocs",
        "Google Docs",
        "Create, read, and edit documents & notes",
        "document-text-outline",
        "#2563EB",
    ),
    ToolDefinition(
        "sheets",
        "googlesheets",
        "Google Sheets",
        "Track expenses, budgets, and spreadsheets",
        "grid-outline",
        "#10B981",
    ),
    ToolDefinition(
        "youtube",
        "youtube",
        "YouTube",
        "Search videos, channels, and playlists",
        "logo-youtube",
        "#FF0000",
    ),
    ToolDefinition(
        "slack",
        "slack",
        "Slack",
        "Read channels and send workspace messages",
        "chatbubbles-outline",
        "#4A154B",
    ),
    ToolDefinition(
        "notion",
        "notion",
        "Notion",
        "Manage notes, pages, and databases",
        "book-outline",
        "#1E2022",
    ),
    ToolDefinition(
        "github",
        "github",
        "GitHub",
        "Review repositories, issues, and PRs",
        "logo-github",
        "#24292E",
    ),
)

TOOLS_BY_ID = {tool.id: tool for tool in TOOLS}
TOOL_ID_BY_TOOLKIT = {tool.toolkit.lower(): tool.id for tool in TOOLS}


def get_tool(tool_id: str) -> ToolDefinition:
    try:
        return TOOLS_BY_ID[tool_id]
    except KeyError as error:
        raise ValueError(f"Unsupported tool: {tool_id}") from error