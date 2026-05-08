import asyncio
import sys
from agno.agent import Agent
from workassistant.config import AGENT_NAME, AGENT_MODEL, LOG_DIR, LOG_LEVEL, CHAT_CONTEXT_WINDOW_SIZE
from workassistant.logging_config import setup_logging

# Setup logging immediately
setup_logging(log_dir=LOG_DIR, log_level=LOG_LEVEL)
from workassistant.tools.project_tools import (
    scan_projects,
    check_scan_status,
    list_projects,
    add_project_location,
    git_log,
    git_diff_summary
)
from workassistant.tools.cost_tools import (
    get_scan_cost_summary,
    get_api_cost_history,
    get_project_cost_breakdown
)
from workassistant.tools.graph_tools import (
    build_project_graph,
    get_project_graph_report
)
from workassistant.tools.log_tools import (
    get_logs,
    get_available_log_files
)
from workassistant.tools.journal_tools import (
    add_journal_entry,
    search_journal,
    get_recent_journal_entries,
    get_journal_summary
)
from workassistant.tools.quick_query_tools import (
    count_repos_at_location,
    list_repos_fast,
    check_if_repo,
    get_cached_project_stats,
    search_projects_by_name,
    get_project_locations
)
from workassistant.tools.lightweight_scan_tools import (
    get_repo_basic_info,
    get_repo_commit_count,
    get_repos_with_recent_activity,
    detect_repo_language,
    compare_repo_sizes
)

# Check if web mode is requested
WEB_MODE = len(sys.argv) > 1 and sys.argv[1] == '--web'

if WEB_MODE:
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
    import uvicorn
    from workassistant.api.scan_routes import router as scan_router
    from workassistant.api.graph_routes import router as graph_router

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

def generate_conversation_title(message: str) -> str:
    """Generate a concise title from the first message of a conversation."""
    # Remove common prefixes
    message = message.strip()
    prefixes_to_remove = ["can you", "please", "i want to", "i need to", "help me"]
    for prefix in prefixes_to_remove:
        if message.lower().startswith(prefix):
            message = message[len(prefix):].strip()
    
    # Capitalize first letter
    if message:
        message = message[0].upper() + message[1:]
    
    # Truncate if too long
    if len(message) > 100:
        message = message[:97] + "..."
    
    # Remove trailing punctuation
    while message and message[-1] in [".", "?", "!"]:
        message = message[:-1]
    
    return message or "New Conversation"

async def load_conversation_context(conversation_id: int, session):
    """Load recent conversation history for context."""
    from sqlalchemy import select
    from workassistant.models.chat_message import ChatMessage
    
    result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(CHAT_CONTEXT_WINDOW_SIZE)
    )
    messages = result.scalars().all()
    
    # Reverse to get chronological order
    messages = list(reversed(messages))
    
    # Format as conversation history
    context_parts = []
    for msg in messages:
        role = "User" if msg.is_user else "Assistant"
        context_parts.append(f"{role}: {msg.content}")
    
    return "\n\n".join(context_parts)

AGENT_INSTRUCTIONS = """You are a Personal Work Assistant that helps track projects, maintain work journals, and answer questions about work history.

## Core Principle: Speed First

Always use the FASTEST tool that can answer the user's question. Don't trigger heavy scans for simple queries.

## Tool Selection Strategy (3-Tier System)

### Tier 1: INSTANT Queries (0-100ms) - Use FIRST
**When to use**: Simple questions about repos, counts, names, cached data
- `count_repos_at_location(path)` - "How many repos at X?" → Instant filesystem count
- `list_repos_fast(path)` - "List repos at X" → Quick repo names without metadata
- `check_if_repo(path)` - "Is X a git repo?" → Instant check
- `get_cached_project_stats(path)` - "How many projects?" → From database (instant)
- `search_projects_by_name(pattern)` - "Find project named X" → Database search
- `get_project_locations()` - "What locations are configured?" → Database query

### Tier 2: LIGHTWEIGHT Queries (100ms-2s) - Use for basic git info
**When to use**: Need git metadata but not deep analysis
- `get_repo_basic_info(path)` - Branch, last commit message, remotes (no AI)
- `get_repo_commit_count(path, branch, since_days)` - Count commits without analyzing
- `get_repos_with_recent_activity(path, days)` - Find active repos in last N days
- `detect_repo_language(path)` - Detect language from files (no git needed)
- `compare_repo_sizes(path)` - Compare repos by commit count

### Tier 3: DEEP Scan (seconds to minutes) - Use ONLY when necessary
**When to use**: Need AI analysis, commit summaries, indexing, or full metadata
- `scan_projects(path)` - Full scan with AI commit analysis, indexing, graphs
- `check_scan_status(job_id)` - Monitor background scan progress
- `list_projects()` - Get fully scanned projects from database
- `git_log(project, limit)` - Detailed commit history
- `git_diff_summary(project, commit)` - Detailed diff analysis

## Query Examples

❌ WRONG: "How many repos at /path?" → scan_projects()
✅ RIGHT: "How many repos at /path?" → count_repos_at_location()

❌ WRONG: "What's the last commit in repo X?" → scan_projects()
✅ RIGHT: "What's the last commit in repo X?" → get_repo_basic_info()

❌ WRONG: "List all repos" → scan_projects()
✅ RIGHT: "List all repos" → get_cached_project_stats() OR list_repos_fast()

✅ CORRECT: "Analyze commits and generate insights" → scan_projects()

## Other Tools

**Journal Management**:
- `add_journal_entry`, `search_journal`, `get_recent_journal_entries`, `get_journal_summary`

**Cost Tracking**:
- `get_scan_cost_summary`, `get_api_cost_history`, `get_project_cost_breakdown`

**Knowledge Graphs**:
- `build_project_graph`, `get_project_graph_report`

**Logging**:
- `get_logs`, `get_available_log_files`

## Guidelines

1. **Speed First**: Always choose the fastest tool that answers the question
2. **Be Proactive**: Offer to create journal entries when users mention work
3. **Cross-reference**: Check both journal entries and Git logs for historical queries
4. **Be Concise**: Clear, actionable responses
5. **Explain Tiers**: If using a slow tool, explain why (e.g., "Running full scan for AI analysis...")

Always be helpful, context-aware, and focused on making work tracking effortless and FAST.
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
                # Tier 1: Instant queries (no git operations)
                count_repos_at_location,
                list_repos_fast,
                check_if_repo,
                get_cached_project_stats,
                search_projects_by_name,
                get_project_locations,
                # Tier 2: Lightweight queries (basic git metadata)
                get_repo_basic_info,
                get_repo_commit_count,
                get_repos_with_recent_activity,
                detect_repo_language,
                compare_repo_sizes,
                # Tier 3: Full scanning and management
                scan_projects,
                check_scan_status,
                list_projects,
                add_project_location,
                git_log,
                git_diff_summary,
                # Journal tools
                add_journal_entry,
                search_journal,
                get_recent_journal_entries,
                get_journal_summary,
                # Cost tracking
                get_scan_cost_summary,
                get_api_cost_history,
                get_project_cost_breakdown,
                # Knowledge graphs
                build_project_graph,
                get_project_graph_report,
                # Logging
                get_logs,
                get_available_log_files,
            ],
            markdown=True,
        )
    return agent

if WEB_MODE:
    app = FastAPI(title="Work Assistant", version="0.1.0")
    app.include_router(scan_router)
    app.include_router(graph_router)
    
    class ChatRequest(BaseModel):
        message: str
        conversation_id: int = None
        parent_message_id: int = None
    
    class ChatResponse(BaseModel):
        response: str
        input_tokens: int
        output_tokens: int
        total_tokens: int
        cost: str
        model: str
        conversation_id: int = None
        created_at: str = None
    
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
            max-width: 1200px;
            background: white;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            overflow: hidden;
            display: flex;
            flex-direction: row;
            height: 90vh;
        }
        
        .main-content {
            flex: 1;
            display: flex;
            flex-direction: column;
            min-width: 0;
        }
        
        .sidebar {
            width: 320px;
            background: #f8f9fa;
            border-left: 1px solid #e9ecef;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            transition: transform 0.3s ease;
        }
        
        .sidebar.collapsed {
            width: 0;
            transform: translateX(100%);
        }
        
        .sidebar-header {
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .sidebar-header h3 {
            font-size: 18px;
            margin: 0;
        }
        
        .sidebar-close {
            background: none;
            border: none;
            color: white;
            font-size: 24px;
            cursor: pointer;
            padding: 0;
            width: 30px;
            height: 30px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        .sidebar-search {
            padding: 15px;
            border-bottom: 1px solid #e9ecef;
        }
        
        .sidebar-search input {
            width: 100%;
            padding: 10px 15px;
            border: 2px solid #e9ecef;
            border-radius: 8px;
            font-size: 14px;
            outline: none;
            transition: border-color 0.3s;
        }
        
        .sidebar-search input:focus {
            border-color: #667eea;
        }
        
        .sidebar-content {
            flex: 1;
            overflow-y: auto;
            padding: 15px;
        }
        
        .feature-category {
            margin-bottom: 20px;
        }
        
        .feature-category-title {
            font-size: 14px;
            font-weight: 600;
            color: #495057;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .feature-card {
            background: white;
            border: 1px solid #e9ecef;
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 8px;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .feature-card:hover {
            border-color: #667eea;
            box-shadow: 0 2px 8px rgba(102, 126, 234, 0.2);
            transform: translateY(-1px);
        }
        
        .feature-card-title {
            font-size: 14px;
            font-weight: 600;
            color: #333;
            margin-bottom: 4px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .feature-card-description {
            font-size: 12px;
            color: #666;
            margin-bottom: 8px;
        }
        
        .feature-card-example {
            font-size: 11px;
            color: #667eea;
            background: #f0f3ff;
            padding: 6px 8px;
            border-radius: 4px;
            font-style: italic;
        }
        
        .feature-badge {
            font-size: 10px;
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: 600;
        }
        
        .badge-instant {
            background: #d4edda;
            color: #155724;
        }
        
        .badge-lightweight {
            background: #fff3cd;
            color: #856404;
        }
        
        .badge-deep {
            background: #f8d7da;
            color: #721c24;
        }
        
        .toggle-sidebar {
            position: fixed;
            right: 20px;
            top: 50%;
            transform: translateY(-50%);
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            padding: 12px 16px;
            cursor: pointer;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
            z-index: 1000;
            font-size: 16px;
            transition: all 0.3s;
        }
        
        .toggle-sidebar:hover {
            transform: translateY(-50%) scale(1.05);
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
        
        .message-time {
            font-size: 11px;
            color: #888;
            margin-top: 6px;
            padding: 4px 8px;
            background: rgba(0, 0, 0, 0.05);
            border-radius: 4px;
            display: inline-block;
        }
        
        .message.user .message-time {
            background: rgba(255, 255, 255, 0.2);
            color: rgba(255, 255, 255, 0.9);
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
        
        .scan-panel {
            display: none;
            margin: 10px 20px;
            padding: 14px 16px;
            background: #f0f4ff;
            border: 1px solid #c7d4ff;
            border-radius: 10px;
            font-size: 13px;
        }
        .scan-panel.active { display: block; }
        .scan-panel h4 { margin: 0 0 8px; color: #4a5568; font-size: 13px; }
        .progress-bar-track {
            background: #dde3f3;
            border-radius: 6px;
            height: 8px;
            margin-bottom: 8px;
            overflow: hidden;
        }
        .progress-bar-fill {
            background: linear-gradient(90deg, #667eea, #764ba2);
            height: 100%;
            border-radius: 6px;
            transition: width 0.4s ease;
            width: 0%;
        }
        .scan-metrics { display: flex; gap: 14px; flex-wrap: wrap; color: #555; margin-bottom: 6px; }
        .scan-metrics span { font-size: 12px; }
        .scan-status-text { font-size: 12px; color: #555; margin-bottom: 6px; }
        .scan-cancel-btn {
            background: #e53e3e; color: white; border: none; border-radius: 6px;
            padding: 4px 12px; font-size: 12px; cursor: pointer;
        }
        .scan-cancel-btn:hover { background: #c53030; }

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
    <button class="toggle-sidebar" onclick="toggleSidebar()">📚 Features</button>
    
    <div class="container">
        <div class="main-content">
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
            <div id="scan-panel" class="scan-panel">
                <h4>🔍 Scan in Progress</h4>
                <div class="progress-bar-track"><div id="scan-progress-fill" class="progress-bar-fill"></div></div>
                <div id="scan-status-text" class="scan-status-text">Initializing...</div>
                <div class="scan-metrics">
                    <span>Projects: <b id="scan-projects">0/0</b></span>
                    <span>Commits: <b id="scan-commits">0</b></span>
                    <span>Phase: <b id="scan-phase">discovery</b></span>
                    <span>Cost: <b id="scan-cost">$0.000000</b></span>
                </div>
                <button class="scan-cancel-btn" onclick="cancelActiveScan()">Cancel Scan</button>
            </div>
            <div class="suggestions">
                <button class="suggestion" onclick="sendSuggestion('List my projects')">📁 List my projects</button>
                <button class="suggestion" onclick="sendSuggestion('Add journal entry: I worked on authentication')">📝 Add journal entry</button>
                <button class="suggestion" onclick="sendSuggestion('Search journal for API')">🔍 Search journal</button>
                <button class="suggestion" onclick="sendSuggestion('What did I work on yesterday?')">🤔 What did I work on?</button>
                <button class="suggestion" onclick="sendSuggestion('Build a knowledge graph for my project')">🕸️ Knowledge Graph</button>
            </div>
            <div class="input-wrapper">
                <input type="text" id="user-input" placeholder="Type your message..." onkeypress="handleKeyPress(event)">
                <button id="send-button" onclick="sendMessage()">Send</button>
            </div>
        </div>
        </div>
        
        <div class="sidebar" id="sidebar">
            <div class="sidebar-header">
                <h3>📚 Features</h3>
                <button class="sidebar-close" onclick="toggleSidebar()">×</button>
            </div>
            <div class="sidebar-search">
                <input type="text" id="feature-search" placeholder="Search features..." oninput="filterFeatures()">
            </div>
            <div class="sidebar-content" id="feature-content">
                <!-- Features will be populated by JavaScript -->
            </div>
        </div>
    </div>
    
    <script>
        const chatContainer = document.getElementById('chat-container');
        const userInput = document.getElementById('user-input');
        const sendButton = document.getElementById('send-button');
        const loading = document.getElementById('loading');
        
        function addMessage(content, isUser, metrics = null, timestamp = null) {
            const messageDiv = document.createElement('div');
            messageDiv.className = `message ${isUser ? 'user' : 'assistant'}`;
            
            let html = `<div class="message-content">${content}</div>`;
            
            // Add timestamp if provided
            if (timestamp) {
                const date = new Date(timestamp);
                const localDate = date.toLocaleDateString(undefined, { 
                    month: 'short', 
                    day: 'numeric', 
                    year: 'numeric' 
                });
                const localTime = date.toLocaleTimeString(undefined, { 
                    hour: '2-digit', 
                    minute: '2-digit' 
                });
                html += `<div class="message-time">🕐 ${localDate} at ${localTime}</div>`;
            }
            
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
            
            // Add user message with current timestamp
            const userTimestamp = new Date().toISOString();
            addMessage(message, true, null, userTimestamp);
            
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
                }, data.created_at);
                
                // Check for job_id in response to auto-start scan monitor
                if (typeof data.response === 'string') {
                    const m = data.response.match(/job_id["\\s:]+([0-9a-f-]{36})/i);
                    if (m) {
                        if (activeScanMonitor) activeScanMonitor.stop();
                        activeScanMonitor = new ScanProgressMonitor(m[1]);
                        activeScanMonitor.start();
                    }
                }
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
        
        async function loadChatHistory() {
            try {
                const response = await fetch('/chat/history?limit=100');
                const messages = await response.json();
                messages.forEach(msg => {
                    const metrics = msg.is_user ? null : {
                        input_tokens: msg.input_tokens,
                        output_tokens: msg.output_tokens,
                        total_tokens: msg.total_tokens,
                        cost: msg.cost
                    };
                    addMessage(msg.content, msg.is_user, metrics, msg.created_at);
                });
            } catch (error) {
                console.error('Failed to load chat history:', error);
            }
        }
        
        // Load chat history on page load
        loadChatHistory();
        
        userInput.addEventListener('keypress', handleKeyPress);
        sendButton.addEventListener('click', sendMessage);
        
        // ---- Feature Discovery System ----
        const features = [
            {
                category: "⚡ Instant Queries (Tier 1)",
                tier: "instant",
                features: [
                    {
                        title: "Count Repos",
                        description: "Count git repositories at a location",
                        example: "How many repos at /path/to/projects?",
                        icon: "🔢"
                    },
                    {
                        title: "List Repos Fast",
                        description: "Quick repo listing without git metadata",
                        example: "List all repos in my work directory",
                        icon: "📋"
                    },
                    {
                        title: "Check if Repo",
                        description: "Instant git repository detection",
                        example: "Is /path/to/project a git repository?",
                        icon: "✅"
                    },
                    {
                        title: "Cached Stats",
                        description: "Get cached project statistics",
                        example: "Show me project statistics from database",
                        icon: "📊"
                    },
                    {
                        title: "Search Projects",
                        description: "Search projects by name pattern",
                        example: "Find projects named 'auth'",
                        icon: "🔍"
                    },
                    {
                        title: "Project Locations",
                        description: "List configured project locations",
                        example: "Show me all configured project locations",
                        icon: "📍"
                    }
                ]
            },
            {
                category: "🔍 Lightweight Queries (Tier 2)",
                tier: "lightweight",
                features: [
                    {
                        title: "Repo Basic Info",
                        description: "Get basic git metadata",
                        example: "What's the last commit in repo X?",
                        icon: "ℹ️"
                    },
                    {
                        title: "Commit Count",
                        description: "Count commits without analyzing",
                        example: "How many commits in the authentication service?",
                        icon: "📈"
                    },
                    {
                        title: "Recent Activity",
                        description: "Find recently active repositories",
                        example: "Which repos had activity this week?",
                        icon: "🕐"
                    },
                    {
                        title: "Detect Language",
                        description: "Detect project programming language",
                        example: "What language is this project written in?",
                        icon: "💻"
                    },
                    {
                        title: "Compare Sizes",
                        description: "Compare repos by commit count",
                        example: "Compare my projects by size",
                        icon: "⚖️"
                    }
                ]
            },
            {
                category: "🔬 Deep Scans (Tier 3)",
                tier: "deep",
                features: [
                    {
                        title: "Full Scan",
                        description: "Complete project scan with AI analysis",
                        example: "Scan my entire workspace with AI analysis",
                        icon: "🔬"
                    },
                    {
                        title: "Knowledge Graph",
                        description: "Build interactive knowledge graph",
                        example: "Build a knowledge graph for my project",
                        icon: "🕸️"
                    }
                ]
            },
            {
                category: "📝 Journal Management",
                tier: "lightweight",
                features: [
                    {
                        title: "Add Entry",
                        description: "Create structured journal entry",
                        example: "Add journal entry: I worked on authentication",
                        icon: "➕"
                    },
                    {
                        title: "Search Journal",
                        description: "Search through journal entries",
                        example: "Search journal for API",
                        icon: "🔍"
                    },
                    {
                        title: "Recent Entries",
                        description: "Get recent journal entries",
                        example: "Show me recent journal entries",
                        icon: "📑"
                    },
                    {
                        title: "Work Summary",
                        description: "Generate work period summaries",
                        example: "What did I work on this week?",
                        icon: "📊"
                    }
                ]
            },
            {
                category: "💰 Cost Tracking",
                tier: "lightweight",
                features: [
                    {
                        title: "Scan Cost Summary",
                        description: "Recent scan cost summary",
                        example: "Show me recent scan costs",
                        icon: "💵"
                    },
                    {
                        title: "Cost History",
                        description: "Time-series cost trends",
                        example: "Show cost trends over time",
                        icon: "📈"
                    },
                    {
                        title: "Project Costs",
                        description: "Per-project cost breakdown",
                        example: "Break down costs by project",
                        icon: "📊"
                    }
                ]
            },
            {
                category: "📊 Git Operations",
                tier: "lightweight",
                features: [
                    {
                        title: "Git Log",
                        description: "Get detailed commit history",
                        example: "Show me recent commits for project X",
                        icon: "📜"
                    },
                    {
                        title: "Git Diff",
                        description: "Analyze commit differences",
                        example: "Show diff for commit abc123",
                        icon: "🔀"
                    }
                ]
            }
        ];
        
        function renderFeatures(featureList = features) {
            const content = document.getElementById('feature-content');
            content.innerHTML = '';
            
            featureList.forEach(category => {
                const categoryDiv = document.createElement('div');
                categoryDiv.className = 'feature-category';
                categoryDiv.innerHTML = `
                    <div class="feature-category-title">${category.category}</div>
                `;
                
                category.features.forEach(feature => {
                    const card = document.createElement('div');
                    card.className = 'feature-card';
                    card.innerHTML = `
                        <div class="feature-card-title">
                            <span>${feature.icon}</span>
                            ${feature.title}
                            <span class="feature-badge badge-${feature.tier}">${feature.tier}</span>
                        </div>
                        <div class="feature-card-description">${feature.description}</div>
                        <div class="feature-card-example">"${feature.example}"</div>
                    `;
                    card.onclick = () => {
                        sendSuggestion(feature.example);
                    };
                    categoryDiv.appendChild(card);
                });
                
                content.appendChild(categoryDiv);
            });
        }
        
        function toggleSidebar() {
            const sidebar = document.getElementById('sidebar');
            const toggleBtn = document.querySelector('.toggle-sidebar');
            sidebar.classList.toggle('collapsed');
            
            if (sidebar.classList.contains('collapsed')) {
                toggleBtn.textContent = '📚 Features';
            } else {
                toggleBtn.textContent = '✕';
            }
        }
        
        function filterFeatures() {
            const searchTerm = document.getElementById('feature-search').value.toLowerCase();
            
            if (!searchTerm) {
                renderFeatures(features);
                return;
            }
            
            const filtered = features.map(category => ({
                ...category,
                features: category.features.filter(feature => 
                    feature.title.toLowerCase().includes(searchTerm) ||
                    feature.description.toLowerCase().includes(searchTerm) ||
                    feature.example.toLowerCase().includes(searchTerm)
                )
            })).filter(category => category.features.length > 0);
            
            renderFeatures(filtered);
        }
        
        // Initialize features on page load
        renderFeatures();
        
        // Auto-open sidebar on first visit
        if (!localStorage.getItem('sidebarVisited')) {
            setTimeout(() => {
                toggleSidebar();
                localStorage.setItem('sidebarVisited', 'true');
            }, 1000);
        }

        // ---- Scan Progress Monitor ----
        let activeScanMonitor = null;

        class ScanProgressMonitor {
            constructor(jobId) {
                this.jobId = jobId;
                this.ws = null;
                this.pollTimer = null;
                this.done = false;
            }

            start() {
                this._showPanel();
                this._connectWS();
                this.pollTimer = setInterval(() => this._poll(), 3000);
            }

            _connectWS() {
                const proto = location.protocol === 'https:' ? 'wss' : 'ws';
                this.ws = new WebSocket(`${proto}://${location.host}/api/scan/ws/${this.jobId}`);
                this.ws.onmessage = (e) => { try { this._update(JSON.parse(e.data)); } catch(_) {} };
                this.ws.onerror = () => { /* fallback to polling */ };
            }

            async _poll() {
                if (this.done) return;
                try {
                    const r = await fetch(`/api/scan/status/${this.jobId}`);
                    const d = await r.json();
                    this._update(d);
                } catch(_) {}
            }

            _update(d) {
                if (!d || d.error) return;
                const pct = d.progress_percent || 0;
                document.getElementById('scan-progress-fill').style.width = pct + '%';
                document.getElementById('scan-phase').textContent = d.phase || '';
                document.getElementById('scan-projects').textContent =
                    `${d.projects_processed||0}/${d.projects_total||'?'}`;
                document.getElementById('scan-commits').textContent = d.commits_processed || 0;
                const cost = d.ai_cost_usd !== undefined ? `$${Number(d.ai_cost_usd).toFixed(6)}` : '$0.000000';
                document.getElementById('scan-cost').textContent = cost;
                const cur = d.current_project ? ` — ${d.current_project}` : '';
                document.getElementById('scan-status-text').textContent =
                    `${d.phase || 'scanning'}${cur}  (${pct}%)`;
                if (d.status === 'completed') { this._finish('Scan completed!'); }
                if (d.status === 'failed')    { this._finish('Scan failed: ' + (d.error_message || '')); }
                if (d.status === 'cancelled') { this._finish('Scan cancelled.'); }
            }

            _finish(msg) {
                this.done = true;
                this.stop();
                document.getElementById('scan-status-text').textContent = msg;
                setTimeout(() => this._hidePanel(), 5000);
            }

            stop() {
                if (this.ws) { try { this.ws.close(); } catch(_) {} }
                if (this.pollTimer) { clearInterval(this.pollTimer); }
            }

            async cancel() {
                await fetch(`/api/scan/cancel/${this.jobId}`, { method: 'POST' });
                this._finish('Cancelling...');
            }

            _showPanel() { document.getElementById('scan-panel').classList.add('active'); }
            _hidePanel() { document.getElementById('scan-panel').classList.remove('active'); }
        }

        function cancelActiveScan() {
            if (activeScanMonitor) activeScanMonitor.cancel();
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
        from datetime import datetime, timezone
        from workassistant.models.ai_api_call import AIApiCall
        from workassistant.models.chat_message import ChatMessage
        from workassistant.models.conversation import Conversation
        from workassistant.database import async_session_maker
        from sqlalchemy import select
        
        request_time = datetime.now(timezone.utc)
        
        # Load conversation context if conversation_id is provided
        conversation_context = ""
        if request.conversation_id:
            async with async_session_maker() as session:
                conversation_context = await load_conversation_context(request.conversation_id, session)
        
        # Prepend context to message if available
        message_to_send = request.message
        if conversation_context:
            message_to_send = f"Previous conversation context:\n\n{conversation_context}\n\n---\n\nCurrent message: {request.message}"
        
        agent_instance = get_agent()
        response = await agent_instance.arun(message_to_send)
        response_time = datetime.now(timezone.utc)
        
        # Extract metrics
        input_tokens = getattr(response.metrics, 'input_tokens', 0) if response.metrics else 0
        output_tokens = getattr(response.metrics, 'output_tokens', 0) if response.metrics else 0
        total_tokens = getattr(response.metrics, 'total_tokens', 0) if response.metrics else 0
        
        cost = calculate_cost(response.model, input_tokens, output_tokens)
        duration_ms = int((response_time - request_time).total_seconds() * 1000)
        
        # Log API call to database
        conversation_id = None
        try:
            async with async_session_maker() as session:
                # Handle conversation
                if request.conversation_id:
                    # Use existing conversation
                    conversation_id = request.conversation_id
                    # Update conversation timestamp
                    result = await session.execute(
                        select(Conversation).where(Conversation.id == conversation_id)
                    )
                    conversation = result.scalar_one_or_none()
                    if conversation:
                        conversation.updated_at = response_time
                else:
                    # Create new conversation
                    title = generate_conversation_title(request.message)
                    conversation = Conversation(
                        title=title,
                        created_at=request_time,
                        updated_at=response_time
                    )
                    session.add(conversation)
                    await session.flush()
                    conversation_id = conversation.id
                
                # Save user message
                user_msg = ChatMessage(
                    conversation_id=conversation_id,
                    parent_message_id=request.parent_message_id,
                    is_user=True,
                    content=request.message,
                    created_at=request_time
                )
                session.add(user_msg)
                
                # Save assistant message
                assistant_msg = ChatMessage(
                    conversation_id=conversation_id,
                    is_user=False,
                    content=response.content,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    cost_usd=format_cost(cost),
                    model=response.model,
                    created_at=response_time
                )
                session.add(assistant_msg)
                
                # Save API call
                api_call = AIApiCall(
                    model=response.model,
                    operation="chat_message",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    cost_usd=cost,
                    request_timestamp=request_time,
                    response_timestamp=response_time,
                    duration_ms=duration_ms,
                    success=True,
                    error_message=None
                )
                session.add(api_call)
                await session.commit()
        except Exception as e:
            import logging
            logging.error(f"Failed to log chat message/API call: {e}")
        
        return ChatResponse(
            response=response.content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost=format_cost(cost),
            model=response.model,
            conversation_id=conversation_id,
            created_at=response_time.isoformat() if response_time else None
        )
    
    @app.get("/chat/history")
    async def get_chat_history(limit: int = 50):
        """Get recent chat history."""
        from sqlalchemy import select
        from workassistant.models.chat_message import ChatMessage
        from workassistant.database import async_session_maker
        
        async with async_session_maker() as session:
            result = await session.execute(
                select(ChatMessage)
                .order_by(ChatMessage.created_at.asc())
                .limit(limit)
            )
            messages = result.scalars().all()
            
            return [
                {
                    "id": msg.id,
                    "conversation_id": msg.conversation_id,
                    "parent_message_id": msg.parent_message_id,
                    "is_user": msg.is_user,
                    "content": msg.content,
                    "input_tokens": msg.input_tokens,
                    "output_tokens": msg.output_tokens,
                    "total_tokens": msg.total_tokens,
                    "cost": msg.cost_usd,
                    "model": msg.model,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None
                }
                for msg in messages
            ]
    
    @app.get("/conversations")
    async def list_conversations(
        limit: int = 50,
        search: str = None,
        start_date: str = None,
        end_date: str = None
    ):
        """List all conversations with optional search and filtering."""
        from sqlalchemy import select, or_
        from workassistant.models.conversation import Conversation
        from workassistant.database import async_session_maker
        from datetime import datetime
        
        async with async_session_maker() as session:
            query = select(Conversation)
            
            # Apply search filter
            if search:
                search_pattern = f"%{search}%"
                query = query.where(
                    or_(
                        Conversation.title.ilike(search_pattern),
                        Conversation.summary.ilike(search_pattern)
                    )
                )
            
            # Apply date range filter
            if start_date:
                try:
                    start_dt = datetime.fromisoformat(start_date)
                    query = query.where(Conversation.created_at >= start_dt)
                except ValueError:
                    pass
            
            if end_date:
                try:
                    end_dt = datetime.fromisoformat(end_date)
                    query = query.where(Conversation.created_at <= end_dt)
                except ValueError:
                    pass
            
            result = await session.execute(
                query.order_by(Conversation.updated_at.desc()).limit(limit)
            )
            conversations = result.scalars().all()
            
            return [
                {
                    "id": conv.id,
                    "title": conv.title,
                    "summary": conv.summary,
                    "created_at": conv.created_at.isoformat() if conv.created_at else None,
                    "updated_at": conv.updated_at.isoformat() if conv.updated_at else None
                }
                for conv in conversations
            ]
    
    @app.get("/conversations/{conversation_id}/messages")
    async def get_conversation_messages(
        conversation_id: int,
        search: str = None,
        limit: int = 100
    ):
        """Get all messages for a specific conversation with optional search."""
        from sqlalchemy import select
        from workassistant.models.chat_message import ChatMessage
        from workassistant.database import async_session_maker
        
        async with async_session_maker() as session:
            query = select(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
            
            # Apply search filter
            if search:
                search_pattern = f"%{search}%"
                query = query.where(ChatMessage.content.ilike(search_pattern))
            
            result = await session.execute(
                query.order_by(ChatMessage.created_at.asc()).limit(limit)
            )
            messages = result.scalars().all()
            
            return [
                {
                    "id": msg.id,
                    "conversation_id": msg.conversation_id,
                    "parent_message_id": msg.parent_message_id,
                    "is_user": msg.is_user,
                    "content": msg.content,
                    "input_tokens": msg.input_tokens,
                    "output_tokens": msg.output_tokens,
                    "total_tokens": msg.total_tokens,
                    "cost": msg.cost_usd,
                    "model": msg.model,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None
                }
                for msg in messages
            ]
    
    @app.get("/messages/search")
    async def search_all_messages(
        search: str,
        limit: int = 50,
        conversation_id: int = None
    ):
        """Search messages across all conversations or a specific conversation."""
        from sqlalchemy import select
        from workassistant.models.chat_message import ChatMessage
        from workassistant.database import async_session_maker
        
        async with async_session_maker() as session:
            query = select(ChatMessage)
            
            # Apply search filter
            search_pattern = f"%{search}%"
            query = query.where(ChatMessage.content.ilike(search_pattern))
            
            # Filter by conversation if specified
            if conversation_id:
                query = query.where(ChatMessage.conversation_id == conversation_id)
            
            result = await session.execute(
                query.order_by(ChatMessage.created_at.desc()).limit(limit)
            )
            messages = result.scalars().all()
            
            return [
                {
                    "id": msg.id,
                    "conversation_id": msg.conversation_id,
                    "parent_message_id": msg.parent_message_id,
                    "is_user": msg.is_user,
                    "content": msg.content,
                    "input_tokens": msg.input_tokens,
                    "output_tokens": msg.output_tokens,
                    "total_tokens": msg.total_tokens,
                    "cost": msg.cost_usd,
                    "model": msg.model,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None
                }
                for msg in messages
            ]
    
    @app.get("/messages/{message_id}/replies")
    async def get_message_replies(message_id: int):
        """Get all replies to a specific message."""
        from sqlalchemy import select
        from workassistant.models.chat_message import ChatMessage
        from workassistant.database import async_session_maker
        
        async with async_session_maker() as session:
            result = await session.execute(
                select(ChatMessage)
                .where(ChatMessage.parent_message_id == message_id)
                .order_by(ChatMessage.created_at.asc())
            )
            messages = result.scalars().all()
            
            return [
                {
                    "id": msg.id,
                    "conversation_id": msg.conversation_id,
                    "parent_message_id": msg.parent_message_id,
                    "is_user": msg.is_user,
                    "content": msg.content,
                    "input_tokens": msg.input_tokens,
                    "output_tokens": msg.output_tokens,
                    "total_tokens": msg.total_tokens,
                    "cost": msg.cost_usd,
                    "model": msg.model,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None
                }
                for msg in messages
            ]
    
    @app.get("/messages/{message_id}/thread")
    async def get_message_thread(message_id: int):
        """Get the full thread for a message (parent and all replies recursively)."""
        from sqlalchemy import select
        from workassistant.models.chat_message import ChatMessage
        from workassistant.database import async_session_maker
        
        async def get_thread_recursive(msg_id, session):
            """Recursively get message thread."""
            result = await session.execute(
                select(ChatMessage).where(ChatMessage.id == msg_id)
            )
            msg = result.scalar_one_or_none()
            if not msg:
                return None
            
            thread = {
                "id": msg.id,
                "conversation_id": msg.conversation_id,
                "parent_message_id": msg.parent_message_id,
                "is_user": msg.is_user,
                "content": msg.content,
                "input_tokens": msg.input_tokens,
                "output_tokens": msg.output_tokens,
                "total_tokens": msg.total_tokens,
                "cost": msg.cost_usd,
                "model": msg.model,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
                "replies": []
            }
            
            # Get replies
            replies_result = await session.execute(
                select(ChatMessage)
                .where(ChatMessage.parent_message_id == msg_id)
                .order_by(ChatMessage.created_at.asc())
            )
            replies = replies_result.scalars().all()
            
            for reply in replies:
                reply_thread = await get_thread_recursive(reply.id, session)
                thread["replies"].append(reply_thread)
            
            return thread
        
        async with async_session_maker() as session:
            return await get_thread_recursive(message_id, session)
    
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
