from openai import OpenAI
from dotenv import load_dotenv
import os
from pathlib import Path
import json
import subprocess

load_dotenv(override=True)

providers = {
    "groq": {
        "api_key": os.getenv("GROQ_API_KEY"),
        "base_url": "https://api.groq.com/openai/v1",
        "model": "openai/gpt-oss-120b"
    },
    "gemini": {
        "api_key": os.getenv("GOOGLE_API_KEY"),
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-2.5-flash"
    },
    "nvidia": {
        "api_key": os.getenv("NVIDIA_API_KEY"),
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "openai/gpt-oss-120b"
    }
}


def get_client(provider_name):
    # providers dictionary se current provider ki settings nikal rahe hain
    provider = providers[provider_name]
    # Us provider ke API key aur base URL se OpenAI-compatible client bana rahe hain
    return OpenAI(
        api_key=provider["api_key"],
        base_url=provider["base_url"]
    )


def get_llm_response(messages, tools, start_provider=None):
    # LLM providers ki priority
    provider_order = ["groq", "gemini", "nvidia"]
    # Agar koi provider already selected hai,
    # to wahi se try karna start karenge
    if start_provider:
        start_index = provider_order.index(start_provider)
        provider_order = provider_order[start_index:] + provider_order[:start_index]
    # Providers ko one-by-one try karenge
    for provider_name in provider_order:
        try:
            # Current provider ka client create hoga
            client = get_client(provider_name)
            # Current provider ko request bhej rahe hain
            response = client.chat.completions.create(
                model=providers[provider_name]["model"],
                messages=messages,
                tools=tools,
                tool_choice="auto"
            )
            print(f"Using provider: {provider_name}")
            # Response + client + provider name return
            return response, client, provider_name
        except Exception as e:
            # Current provider fail hua to next provider try hoga
            print(f"{provider_name} failed: {e}")
    # Sab providers fail ho gaye
    raise Exception("All LLM providers failed.")

def list_files():
    files = []
    for path in Path(".").iterdir():
        if path.name in [".cenv", "__pycache__", ".git", ".env"]:
            continue
        files.append(path.name)
    return files


def read_file(file_path):
    path = Path(file_path)
    if not path.is_file():
        return f"{file_path} is not a file."
    with open(path, "r") as file:
        return file.read()


def edit_file(file_path, old_text, new_text):
    path = Path(file_path)
    if not path.is_file():
        return f"{file_path} is not a file."
    content = path.read_text()
    if old_text not in content:
        return f"Text not found in {file_path}."
    content = content.replace(old_text, new_text, 1)
    path.write_text(content)
    return f"{file_path} updated successfully."


def run_command(command):
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True
    )
    return result.stdout + result.stderr


def write_file(file_path, content):
    with open(file_path, "w") as file:
        file.write(content)
    return f"{file_path} created successfully."


tool_registry = {
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "run_command": run_command
}


tools = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List all files and folders in the current project directory.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the complete contents of a file in the current project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path of the file to read."
                    }
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a file. The first parameter MUST be named file_path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "MUST be the exact file path. Use the key name 'file_path', not 'path'."
                    },
                    "content": {
                        "type": "string",
                        "description": "The content to write into the file."
                    }
                },
                "required": ["file_path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a terminal command in the current project directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The terminal command to execute."
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace specific text in an existing file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path of the file to edit."
                    },
                    "old_text": {
                        "type": "string",
                        "description": "The exact text that should be replaced."
                    },
                    "new_text": {
                        "type": "string",
                        "description": "The new text that should replace the old text."
                    }
                },
                "required": ["file_path", "old_text", "new_text"]
            }
        }
    }
]


messages = []

while True:
    user_input = input("You: ")

    if user_input.lower() == "exit":
        break

    messages.append({
        "role": "user",
        "content": user_input
    })

    response, client, provider_name = get_llm_response(
        messages,
        tools
    )

    while response.choices[0].message.tool_calls:
        messages.append(response.choices[0].message)

        for tool_call in response.choices[0].message.tool_calls:
            tool_name = tool_call.function.name
            arguments = json.loads(tool_call.function.arguments)

            tool_function = tool_registry[tool_name]
            result = tool_function(**arguments)

            if not isinstance(result, str):
                result = json.dumps(result)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result
            })

        response, client, provider_name = get_llm_response(
            messages,
            tools,
            start_provider=provider_name
        )
    messages.append(response.choices[0].message)

    print(response.choices[0].message.content)