import os
from fastmcp import FastMCP

mcp = FastMCP(name="My MCP Server")

@mcp.tool
def add(a: int, b: int) -> int:
    """Adds two numbers."""
    return a + b

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))  # Get PORT env var or default to 8080

    mcp.run(
        transport="http",      # Use HTTP transport (recommended for cloud)
        host="0.0.0.0",        # Listen on all network interfaces
        port=port,             # Use dynamic port
        path="/mcp"            # Exposed endpoint path
    )

