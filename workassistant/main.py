import asyncio
import sys
from agno.agent import Agent
from workassistant.config import AGENT_NAME, AGENT_MODEL
from workassistant.tools.project_tools import (
    scan_projects,
    list_projects,
    add_project_location,
    git_log,
    git_diff_summary
)
from workassistant.tools.journal_tools import (
    add_journal_entry,
    search_journal,
    get_recent_journal_entries,
    get_journal_summary
)

# Check if web mode is requested
WEB_MODE = len(sys.argv) > 1 and sys.argv[1] == '--web'

if WEB_MODE:
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
    import uvicorn

# OpenAI pricing (as of 2024)
PRICING = {
    "gpt-4o": {"input": 0.005, "output": 0.015},  # per 1M tokens
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "gpt-4": {"input": 0.03, "output": 0.06},
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
}

def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate cost based on model and token usage."""
    model_name = model.split(":")[-1] if ":" in model else model
    pricing = PRICING.get(model_name, {"input": 0.01, "output": 0.03})
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return input_cost + output_cost

def format_cost(cost: float) -> str:
    """Format cost for display."""
    if cost < 0.01:
        return f"${cost:.4f}"
    return f"${cost:.2f}"

AGENT_INSTRUCTIONS = """You are a Personal Work Assistant that helps track projects, maintain work journals, and answer questions about work history.

## Your Capabilities

### Project Management
- Scan project locations to discover Git repositories and plain folders
- Track project metadata including language, last commits, branches
- List and search through tracked projects
- View Git commit history and diffs

### Journal Management
- Create structured journal entries with project references
- Support both free-form and guided journal entry modes
- Search journal entries by date, project, tags, or keywords
- Generate summaries of work done over time periods

### Historical Queries
- Answer questions about past work using journal entries and Git history
- Find when specific features were worked on
- Track blockers and their resolutions
- Identify patterns in work across projects

## Guidelines

1. **Be Proactive**: When users mention working on something, offer to create a journal entry
2. **Ask Follow-ups**: For journal entries, ask clarifying questions to enrich the entry
3. **Cross-reference**: When answering historical queries, check both journal entries and Git logs
4. **Be Concise**: Provide clear, actionable responses

## Tool Usage

- Use `scan_projects` to discover new projects in configured locations
- Use `list_projects` to see what projects are tracked
- Use `git_log` and `git_diff_summary` for Git repository details (only for git repos)
- Use `add_journal_entry` to create journal entries
- Use `search_journal` to find past work
- Use `add_project_location` to add new project root directories

Always be helpful, context-aware, and focused on making work tracking effortless.
"""

# Global agent instance
agent = None

def get_agent():
    """Get or create agent instance."""
    global agent
    if agent is None:
        agent = Agent(
            name=AGENT_NAME,
            model=AGENT_MODEL,
            instructions=AGENT_INSTRUCTIONS,
            enable_agentic_memory=False,
            learning=False,
            add_history_to_context=False,
            tools=[
                scan_projects,
                list_projects,
                add_project_location,
                git_log,
                git_diff_summary,
                add_journal_entry,
                search_journal,
                get_recent_journal_entries,
                get_journal_summary,
            ],
            markdown=True,
        )
    return agent

if WEB_MODE:
    app = FastAPI(title="Work Assistant", version="0.1.0")
    
    class ChatRequest(BaseModel):
        message: str
    
    class ChatResponse(BaseModel):
        response: str
        input_tokens: int
        output_tokens: int
        total_tokens: int
        cost: str
        model: str
    
    HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Work Assistant</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        
        .container {
            width: 100%;
            max-width: 900px;
            background: white;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            overflow: hidden;
            display: flex;
            flex-direction: column;
            height: 90vh;
        }
        
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            text-align: center;
        }
        
        .header h1 {
            font-size: 24px;
            margin-bottom: 5px;
        }
        
        .header p {
            font-size: 14px;
            opacity: 0.9;
        }
        
        .chat-container {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
            background: #f8f9fa;
        }
        
        .message {
            margin-bottom: 20px;
            animation: fadeIn 0.3s ease-in;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .message.user {
            display: flex;
            justify-content: flex-end;
        }
        
        .message.assistant {
            display: flex;
            justify-content: flex-start;
        }
        
        .message-content {
            max-width: 70%;
            padding: 12px 16px;
            border-radius: 12px;
            line-height: 1.5;
        }
        
        .message.user .message-content {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        
        .message.assistant .message-content {
            background: white;
            color: #333;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        }
        
        .metrics {
            font-size: 12px;
            color: #666;
            margin-top: 8px;
            padding: 8px 12px;
            background: #e9ecef;
            border-radius: 8px;
            display: inline-block;
        }
        
        .input-container {
            padding: 20px;
            background: white;
            border-top: 1px solid #e9ecef;
        }
        
        .input-wrapper {
            display: flex;
            gap: 10px;
        }
        
        #user-input {
            flex: 1;
            padding: 12px 16px;
            border: 2px solid #e9ecef;
            border-radius: 8px;
            font-size: 14px;
            outline: none;
            transition: border-color 0.3s;
        }
        
        #user-input:focus {
            border-color: #667eea;
        }
        
        #send-button {
            padding: 12px 24px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s;
        }
        
        #send-button:hover {
            transform: scale(1.05);
        }
        
        #send-button:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }
        
        .suggestions {
            display: flex;
            gap: 8px;
            margin-bottom: 12px;
            flex-wrap: wrap;
        }
        
        .suggestion {
            padding: 6px 12px;
            background: #f0f0f0;
            border: none;
            border-radius: 16px;
            font-size: 12px;
            cursor: pointer;
            transition: background 0.2s;
        }
        
        .suggestion:hover {
            background: #e0e0e0;
        }
        
        .loading {
            display: none;
            text-align: center;
            padding: 20px;
            color: #666;
        }
        
        .loading.active {
            display: block;
        }
        
        .typing-indicator {
            display: inline-block;
        }
        
        .typing-indicator span {
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #667eea;
            margin: 0 2px;
            animation: typing 1.4s infinite;
        }
        
        .typing-indicator span:nth-child(2) {
            animation-delay: 0.2s;
        }
        
        .typing-indicator span:nth-child(3) {
            animation-delay: 0.4s;
        }
        
        @keyframes typing {
            0%, 60%, 100% { transform: translateY(0); }
            30% { transform: translateY(-10px); }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 Work Assistant</h1>
            <p>Your personal project and journal assistant</p>
        </div>
        
        <div class="chat-container" id="chat-container">
            <div class="message assistant">
                <div class="message-content">
                    Hello! I'm your Work Assistant. I can help you:
                    <ul style="margin-left: 20px; margin-top: 10px;">
                        <li>📁 Track and scan your projects</li>
                        <li>📝 Create and search journal entries</li>
                        <li>🔍 Query your work history</li>
                        <li>📊 View Git logs and diffs</li>
                    </ul>
                </div>
            </div>
        </div>
        
        <div class="loading" id="loading">
            <div class="typing-indicator">
                <span></span><span></span><span></span>
            </div>
        </div>
        
        <div class="input-container">
            <div class="suggestions">
                <button class="suggestion" onclick="sendSuggestion('List my projects')">📁 List my projects</button>
                <button class="suggestion" onclick="sendSuggestion('Add journal entry: I worked on authentication')">📝 Add journal entry</button>
                <button class="suggestion" onclick="sendSuggestion('Search journal for API')">🔍 Search journal</button>
                <button class="suggestion" onclick="sendSuggestion('What did I work on yesterday?')">🤔 What did I work on?</button>
            </div>
            <div class="input-wrapper">
                <input type="text" id="user-input" placeholder="Type your message..." onkeypress="handleKeyPress(event)">
                <button id="send-button" onclick="sendMessage()">Send</button>
            </div>
        </div>
    </div>
    
    <script>
        const chatContainer = document.getElementById('chat-container');
        const userInput = document.getElementById('user-input');
        const sendButton = document.getElementById('send-button');
        const loading = document.getElementById('loading');
        
        function addMessage(content, isUser, metrics = null) {
            const messageDiv = document.createElement('div');
            messageDiv.className = `message ${isUser ? 'user' : 'assistant'}`;
            
            let html = `<div class="message-content">${content}</div>`;
            
            if (metrics && !isUser) {
                html += `
                    <div class="metrics">
                        📊 Tokens: ${metrics.total_tokens.toLocaleString()} 
                        (in: ${metrics.input_tokens.toLocaleString()}, out: ${metrics.output_tokens.toLocaleString()})
                        | 💰 Cost: ${metrics.cost}
                    </div>
                `;
            }
            
            messageDiv.innerHTML = html;
            chatContainer.appendChild(messageDiv);
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }
        
        async function sendMessage() {
            const message = userInput.value.trim();
            if (!message) return;
            
            userInput.value = '';
            sendButton.disabled = true;
            loading.classList.add('active');
            
            addMessage(message, true);
            
            try {
                const response = await fetch('/chat', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ message }),
                });
                
                const data = await response.json();
                
                loading.classList.remove('active');
                addMessage(data.response, false, {
                    input_tokens: data.input_tokens,
                    output_tokens: data.output_tokens,
                    total_tokens: data.total_tokens,
                    cost: data.cost
                });
            } catch (error) {
                loading.classList.remove('active');
                addMessage('Sorry, something went wrong. Please try again.', false);
            }
            
            sendButton.disabled = false;
            userInput.focus();
        }
        
        function sendSuggestion(text) {
            userInput.value = text;
            sendMessage();
        }
        
        function handleKeyPress(event) {
            if (event.key === 'Enter') {
                sendMessage();
            }
        }
    </script>
</body>
</html>
    """
    
    @app.get("/", response_class=HTMLResponse)
    async def get_chat_ui():
        return HTMLResponse(content=HTML_TEMPLATE)
    
    @app.post("/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest):
        agent_instance = get_agent()
        response = await agent_instance.arun(request.message)
        
        # Extract metrics
        input_tokens = getattr(response.metrics, 'input_tokens', 0) if response.metrics else 0
        output_tokens = getattr(response.metrics, 'output_tokens', 0) if response.metrics else 0
        total_tokens = getattr(response.metrics, 'total_tokens', 0) if response.metrics else 0
        
        cost = calculate_cost(response.model, input_tokens, output_tokens)
        
        return ChatResponse(
            response=response.content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost=format_cost(cost),
            model=response.model
        )
    
    async def run_web():
        """Run the web server."""
        print(f"🚀 Starting Work Assistant Web UI...")
        print(f"📱 Open http://localhost:8000 in your browser")
        print(f"⚡ Press Ctrl+C to stop")
        print()
        config = uvicorn.Config(app, host="0.0.0.0", port=8000)
        server = uvicorn.Server(config)
        await server.serve()

async def main():
    """Main entry point for the Work Assistant application."""
    
    if WEB_MODE:
        await run_web()
        return
    
    agent_instance = get_agent()
    
    print(f"Starting {AGENT_NAME}...")
    print("=" * 60)
    print("Personal Work Assistant is ready!")
    print("I can help you:")
    print("  - Track your projects (Git repos and plain folders)")
    print("  - Maintain a daily work journal")
    print("  - Answer questions about your work history")
    print("=" * 60)
    print()
    print("💡 Tip: Use 'python -m workassistant.main --web' for a nice web UI")
    print()
    print("Type your message below (press Ctrl+C to exit):")
    print("-" * 60)
    
    # Simple CLI interface
    try:
        while True:
            user_input = input("\nYou: ")
            if user_input.strip().lower() in ['exit', 'quit']:
                break
            
            response = await agent_instance.arun(user_input)
            print(f"\n{AGENT_NAME}: {response.content}")
            
            # Display token usage and cost if available
            if hasattr(response, 'metrics') and response.metrics:
                metrics = response.metrics
                input_tokens = getattr(metrics, 'input_tokens', 0)
                output_tokens = getattr(metrics, 'output_tokens', 0)
                total_tokens = getattr(metrics, 'total_tokens', 0)
                
                if total_tokens > 0:
                    cost = calculate_cost(response.model, input_tokens, output_tokens)
                    print(f"\n{'─' * 60}")
                    print(f"📊 Token Usage: {total_tokens:,} (input: {input_tokens:,}, output: {output_tokens:,})")
                    print(f"💰 Estimated Cost: {format_cost(cost)}")
                    print(f"{'─' * 60}")
    except KeyboardInterrupt:
        print("\n\nGoodbye!")

if __name__ == "__main__":
    asyncio.run(main())
