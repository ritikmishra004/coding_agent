from mcp.server import MCPServer
from pathlib import Path
import subprocess
import shlex
import json


mcp = MCPServer("Coding Agent MCP Server")


# CHANGE:
# Expected tool errors ko normal string result ke roop mein bhej rahe hain.
# Raw exception raise karne par MCP SDK usko UnexpectedToolError mein wrap kar deta hai
# aur original exception type client ko reliable way mein nahi milta.
# Is marker ko graph.py decode karke original Python exception reconstruct karega.
MCP_ERROR_PREFIX = "__MCP_ERROR_TYPE__:"


def mcp_error(error:Exception)->str:
    return (
        f"{MCP_ERROR_PREFIX}"
        f"{type(error).__name__}:"
        f"{str(error)}"
    )


@mcp.tool()
def list_files()->list[str]:
    """List all files and folders in the current project directory."""
    try:
        files = []

        for path in Path(".").iterdir():
            if path.name in [".cenv","__pycache__",".git",".env","checkpoints.db"]:
                continue
            files.append(path.name)

        return files

    except (PermissionError,FileNotFoundError) as e:
        return mcp_error(e)


@mcp.tool()
def read_file(file_path:str)->str:
    """Read the complete contents of a file."""
    try:
        return Path(file_path).read_text()

    except (FileNotFoundError,PermissionError,IsADirectoryError) as e:
        return mcp_error(e)


@mcp.tool()
def write_file(file_path:str,content:str)->str:
    """Create or overwrite a file with the provided content."""
    try:
        with open(file_path,"w") as file:
            file.write(content)

        return f"{file_path} created successfully."

    except (FileNotFoundError,PermissionError,IsADirectoryError) as e:
        return mcp_error(e)


@mcp.tool()
def edit_file(file_path:str,old_text:str,new_text:str)->str:
    """Replace specific existing text in a file."""
    path = Path(file_path)

    if not path.is_file():
        return mcp_error(
            FileNotFoundError(f"{file_path} does not exist.")
        )

    try:
        content = path.read_text()

        if old_text not in content:
            return f"{file_path} text not found in it"

        content = content.replace(old_text,new_text,1)
        path.write_text(content)

        return f"{file_path} updated successfully"

    except (FileNotFoundError,PermissionError,IsADirectoryError) as e:
        return mcp_error(e)


ALLOWED_COMMANDS = {
    "ls","pwd","cat","find","grep",
    "git status","git diff","git log","git branch","git switch",
    "python","python3","pip","pytest","npm","npx","rm","mkdir","touch"
}


def allowed_command(command:str)->bool:
    try:
        parts = shlex.split(command)

        if not parts:
            return False

        base_command = parts[0]

        if base_command == "git":
            if len(parts) < 2:
                return False

            return f"git {parts[1]}" in {
                "git status","git diff","git log","git branch","git switch"
            }

        return base_command in ALLOWED_COMMANDS

    except ValueError:
        return False


@mcp.tool()
def command_run(command:str)->str:
    """Run a terminal command in the current project directory."""
    try:
        if not allowed_command(command):
            return (
                f"Command rejected by security policy: {command}\n"
                "Do not retry this command or perform an alternative action "
                "to achieve the same operation."
            )

        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True
        )

        output = result.stdout + result.stderr

        if output:
            return output

        return f"✅ Command executed successfully: {command}"

    except (FileNotFoundError,PermissionError,TimeoutError,ConnectionError) as e:
        return mcp_error(e)


@mcp.tool()
def test_retry_error()->str:
    """Testing tool for retry error handling."""
    return mcp_error(
        TimeoutError("Temporary timeout for testing retry logic.")
    )


@mcp.tool()
def add_numbers(a:int,b:int)->int:
    """Add two numbers."""
    return a+b


# =========================== RESOURCES ===========================

@mcp.resource("project://files")
def project_files()->str:
    """Return the current project file list as JSON."""
    files = []

    for path in Path(".").iterdir():
        if path.name in [".cenv","__pycache__",".git",".env","checkpoints.db"]:
            continue
        files.append(path.name)

    return json.dumps(files)


@mcp.resource("file://{file_path}")
def file_resource(file_path:str)->str:
    """Read a project file as an MCP resource."""
    path = Path(file_path)

    if not path.is_file():
        return mcp_error(
            FileNotFoundError(f"{file_path} does not exist.")
        )

    return path.read_text()


# ============================ PROMPTS ============================

@mcp.prompt()
def coding_assistant(task:str)->str:
    """Create a reusable coding-agent prompt for a task."""
    return (
        "You are a coding agent.\n\n"
        f"User task:\n{task}\n\n"
        "Use the available MCP tools when you need to inspect, modify, "
        "or execute project files."
    )


if __name__ == "__main__":
    mcp.run()
