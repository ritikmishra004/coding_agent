from mcp.server import MCPServer

mcp = MCPServer("My MCP Server")

@mcp.tool()
def add_numbers(a:int,b:int)->int:
    """Add two numbers."""
    return a+b

if __name__ == "__main__":
    mcp.run()