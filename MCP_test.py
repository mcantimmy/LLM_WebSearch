import anthropic
import requests
import json
import os
from dotenv import load_dotenv
# Load environment variables from .env file
load_dotenv()

class MCPTool:
    def __init__(self, name, description, server_url):
        self.name = name
        self.description = description
        self.server_url = server_url
    
    def execute(self, method, params):
        request_data = {
            "method": method,
            "params": params,
            "jsonrpc": "2.0",
            "id": 1
        }
        
        response = requests.post(
            self.server_url,
            json=request_data,
            headers={"Content-Type": "application/json"}
        )
        
        return response.json()

# Setup Claude client
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# Configure MCP tools
tools = [
    MCPTool(
        name="file_system",
        description="Access files on the local system",
        server_url="http://localhost:8080/files"
    ),
    MCPTool(
        name="database",
        description="Query a SQL database",
        server_url="http://localhost:8081/query"
    )
]

def call_claude_with_tools(prompt, tools_to_use):
    """Call Claude with MCP tools available"""
    
    tool_configs = [{
        "name": tool.name,
        "description": tool.description
    } for tool in tools_to_use]
    
    # First message to Claude with tools available
    message = client.messages.create(
        model="claude-3-7-sonnet-20250219",
        max_tokens=1000,
        system="You are an assistant with access to tools. Use the tools when appropriate.",
        messages=[
            {"role": "user", "content": prompt}
        ],
        tools=tool_configs
    )
    
    # Process tool calls if any
    while message.tool_use:
        tool_calls = message.tool_use
        tool_responses = []
        
        for tool_call in tool_calls:
            # Find the tool to use
            tool = next(t for t in tools if t.name == tool_call["name"])
            
            # Execute the tool
            result = tool.execute(
                tool_call["parameters"].get("method", ""),
                tool_call["parameters"].get("params", {})
            )
            
            tool_responses.append({
                "tool_call_id": tool_call["id"],
                "output": json.dumps(result)
            })
        
        # Continue the conversation with tool results
        message = client.messages.create(
            model="claude-3-7-sonnet-20250219",
            max_tokens=1000,
            system="You are an assistant with access to tools. Use the tools when appropriate.",
            messages=[
                {"role": "user", "content": prompt},
                message,
                {"role": "assistant", "content": message.content, "tool_use": message.tool_use},
                {"role": "user", "tool_results": tool_responses}
            ],
            tools=tool_configs
        )
    
    return message.content

# Example usage
result = call_claude_with_tools(
    "Please read the file quarterly_report.txt and summarize the key findings",
    [tools[0]]  # Only using the file_system tool
)