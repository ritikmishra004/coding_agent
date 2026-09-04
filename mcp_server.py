from mcp.server.fastmcp import FastMCP

mcp = FastMCP("My MCP Server")

@mcp.tool()
def add_numbers(a:int,b:int)->int:
    """Add two numbers."""
    return a + b

if __name__ == "__main__":
    mcp.run()