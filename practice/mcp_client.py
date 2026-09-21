import asyncio
from mcp import Client,StdioServerParameters


server = StdioServerParameters(
    command="python",
    args=["mcp_server.py"]
)


async def main():
    async with Client(server) as client:

        #===========================TOOLS===========================
        tools = await client.list_tools()

        print("Available tools:")

        for tool in tools.tools:
            print(tool.name)

        print()

        result = await client.call_tool(
            "list_files",
            {}
        )

        print("list_files result:",result)

        result = await client.call_tool(
            "add_numbers",
            {
                "a":20,
                "b":30
            }
        )

        print("add_numbers result:",result)


        try:
            result = await client.call_tool(
                "test_retry_error",
                {}
            )

            print("test_retry_error result:",result)

        except Exception as e:
            print("test_retry_error exception:",type(e).__name__,str(e))

        #=========================RESOURCES=========================
        resources = await client.list_resources()

        print("\nResources:")

        for resource in resources.resources:
            print(resource.uri)

        result = await client.read_resource("project://files")

        print("project://files:",result)

        #===========================PROMPTS==========================
        prompts = await client.list_prompts()

        print("\nPrompts:")

        for prompt in prompts.prompts:
            print(prompt.name)

        result = await client.get_prompt(
            "coding_assistant",
            {
                "task":"Create a Python hello world file."
            }
        )

        print("coding_assistant:",result)


if __name__ == "__main__":
    asyncio.run(main())
