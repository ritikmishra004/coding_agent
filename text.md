ritikmishra@Unknown_06:60:f7:73:0c:e9 Coding-Agent %  source /Users/ritikmishra/Desktop/Coding-Agent/.cenv/bin/activate
(.cenv) ritikmishra@Unknown_06:60:f7:73:0c:e9 Coding-Agent % python -u "/Users/ritikmishra/Desktop/Coding-Agent/graph.py"

MCP resources discovered:
- project://files


MCP tools discovered:
- mcp_list_files
- mcp_read_file
- mcp_write_file
- mcp_edit_file
- mcp_command_run
- mcp_test_retry_error
- mcp_add_numbers

You: exit
(.cenv) ritikmishra@Unknown_06:60:f7:73:0c:e9 Coding-Agent % python -u "/Users/ritikmishra/Desktop/Coding-Agent/graph.py"

MCP resources discovered:
- project://files


Project resource:
meta={'io.modelcontextprotocol/serverInfo': {'name': 'Coding Agent MCP Server', 'version': ''}} ttl_ms=0 cache_scope='private' contents=[TextResourceContents(uri='project://files', mime_type='text/plain', meta=None, text='["text.md", "test_agent.py", ".pytest_cache", "graph.py", "checkpoints.db-shm", "test.py", "checkpoints.db-wal", "test_calculator.py", "understand.py", "starting_graph.py", ".gitignore", "calculator.py", "app.py", "mcp_client.py", "test_2.py", "graph_w_mcpWrapper.py", "mcp_server.py"]')] result_type='complete'

MCP tools discovered:
- mcp_list_files
- mcp_read_file
- mcp_write_file
- mcp_edit_file
- mcp_command_run
- mcp_test_retry_error
- mcp_add_numbers

You: 



# LLM answer

content='The capital of India is **New Delhi**.' additional_kwargs={} response_metadata={'finish_reason': 'STOP', 'model_name': 'gemini-2.5-flash', 'safety_ratings': [], 'model_provider': 'google_genai'} id='lc_run--01a0a4e4-b2ec-7283-97fc-9dcdbe7b025e-0' tool_calls=[] invalid_tool_calls=[] usage_metadata={'input_tokens': 8, 'output_tokens': 30, 'total_tokens': 38, 'input_token_details': {'cache_read': 0}, 'output_token_details': {'reasoning': 21}}
(lenv) ritikmishra@Unknown_06:60:f7:73:0c:e9 Gen_AI % 


# tool call
content=''
additional_kwargs={}
response_metadata={
    'finish_reason': 'STOP',
    'model_name': 'gemini-2.5-flash',
    'model_provider': 'google_genai'
}
id='lc_run--abc123'
tool_calls=[
    {
        'name': 'get_weather',
        'args': {
            'city': 'Delhi'
        },
        'id': 'call_123',
        'type': 'tool_call'
    }
]
invalid_tool_calls=[]
usage_metadata={
    'input_tokens': 20,
    'output_tokens': 10,
    'total_tokens': 30
}

# tool message

ToolMessage(
    content='Delhi temperature is 32°C',
    tool_call_id='call_123'
)

# mcp schema 
{
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Path of the file"
        },
        "content": {
            "type": "string",
            "description": "Content of the file"
        },
        "overwrite": {
            "type": "boolean",
            "description": "Overwrite if file exists"
        }
    },
    "required": ["path", "content"]
}

#####
{
    'properties': {
        'path': {
            'description': 'Path of the file',
            'title': 'Path',
            'type': 'string'
        },
        'content': {
            'description': 'Content of the file',
            'title': 'Content',
            'type': 'string'
        },
        'overwrite': {
            'default': None,
            'description': 'Overwrite if file exists',
            'title': 'Overwrite',
            'type': 'boolean'
        }
    },
    'required': [
        'path',
        'content'
    ],
    'title': 'create_fileInput',
    'type': 'object'
}

## json rpc
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "tools": [
      {
        "name": "create_file",
        "description": "Create a file with the given content",
        "inputSchema": {
          "type": "object",
          "properties": {
            "path": {
              "type": "string",
              "description": "Path of the file"
            },
            "content": {
              "type": "string",
              "description": "Content of the file"
            },
            "overwrite": {
              "type": "boolean",
              "description": "Overwrite existing file"
            }
          },
          "required": [
            "path",
            "content"
          ]
        }
      }
    ]
  }
}