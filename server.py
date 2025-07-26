from fastmcp import FastMCP

mcp = FastMCP(name="My MCP Server")

@mcp.tool
def add(a: int, b: int) -> int:
    """Adds two numbers."""
    return a + b

if __name__ == "__main__":
    # Use HTTP for production/cloud compatibility.
    mcp.run(
        transport="http",      # Use HTTP transport (recommended for cloud)
        host="0.0.0.0",        # Listen on all network interfaces
        port=8000,             # Set to any open port
        path="/mcp"            # Exposed endpoint path
    )
