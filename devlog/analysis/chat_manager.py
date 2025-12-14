import json
from typing import List, Dict, Optional, AsyncGenerator
from devlog.analysis.llm import analyze_code, LLMConfig
from devlog.core.embeddings import semantic_search
from devlog.search.web_search import WebSearcher
import asyncio

class ChatManager:
    """Manages chat interactions, context, and LLM communication."""

    def __init__(self, model: str = LLMConfig.MODEL):
        self.model = model
        self.history: List[Dict] = []
        self.web_searcher = WebSearcher()
        self.system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        """Define the system prompt for the chatbot."""
        return (
            "You are DevLog, a highly intelligent and helpful coding assistant. "
            "You have access to a user's local Git commit history and the internet. "
            "Your primary goal is to provide accurate, concise, and helpful information "
            "related to software development, best practices, debugging, and code reviews. "
            "Always prioritize providing relevant code snippets or technical explanations. "
            "If the user asks a question that could benefit from recent commits or web search, "
            "use your tools to gather context before responding."
            "\n\n--- Available Tools ---"
            "\n- `search_commits(query: str, limit: int = 3)`: Search user's commit history for relevant code changes. Returns commit details including code changes."
            "\n- `web_search(query: str, limit: int = 3)`: Search the internet for up-to-date information, best practices, or solutions. Returns titles, snippets, and URLs."
            "\n--- End Tools ---"
            "\n\nWhen using a tool, output a JSON object like: `{'tool': 'search_commits', 'args': {'query': 'user auth'}}`"
            "\nIf you use a tool, wait for the tool output before generating your final response."
        )

    async def send_message(self, user_message: str) -> AsyncGenerator[str, None]:
        """
        Send a message to the chatbot and get a streaming response.
        Orchestrates tool use (commit search, web search) if necessary.
        """
        self.history.append({"role": "user", "content": user_message})

        full_prompt = self._build_full_prompt()
        
        # Initial call to LLM to decide on tool use
        tool_decision_prompt = self._build_tool_decision_prompt()
        
        tool_response_generator = await analyze_code(
            prompt=tool_decision_prompt,
            code=full_prompt,
            language="text", # Treat as plain text for tool decision
            stream=False # Tool decision is not streamed
        )
        
        tool_response_text = ""
        # If analyze_code returns a generator (which it will if `stream=True` but here we forced `stream=False`)
        # then we need to consume it. But since we forced `stream=False` it returns str.
        tool_response_text = tool_response_generator # It's a string because stream=False
        
        try:
            tool_call = json.loads(tool_response_text)
            if tool_call.get('tool'):
                yield f"[TOOL CALLING: {tool_call['tool']}...]\n"
                tool_output = await self._execute_tool(tool_call['tool'], tool_call['args'])
                self.history.append({"role": "tool", "content": json.dumps(tool_output)})
                full_prompt = self._build_full_prompt() # Rebuild prompt with tool output
                
                # After tool, ask LLM again with new context, streaming response
                response_generator = self._stream_llm_response(full_prompt)
                async for chunk in response_generator:
                    yield chunk
                return
        except json.JSONDecodeError:
            # Not a tool call, proceed with regular response
            pass
        except Exception as e:
            yield f"[ERROR executing tool: {e}]\n"
            self.history.append({"role": "system", "content": f"Error executing tool: {e}"})
            full_prompt = self._build_full_prompt() # Continue with error in context

        # Regular LLM response, streaming
        response_generator = self._stream_llm_response(full_prompt)
        async for chunk in response_generator:
            yield chunk

    def _build_full_prompt(self) -> str:
        """Construct the full prompt including system message and history."""
        prompt_parts = [self.system_prompt]
        for message in self.history:
            role = message["role"]
            content = message["content"]
            if role == "user":
                prompt_parts.append(f"\n[USER]: {content}")
            elif role == "assistant":
                prompt_parts.append(f"\n[ASSISTANT]: {content}")
            elif role == "tool":
                prompt_parts.append(f"\n[TOOL_OUTPUT]: {content}")
            elif role == "system":
                prompt_parts.append(f"\n[SYSTEM]: {content}")
        return "\n".join(prompt_parts) + "\n[ASSISTANT]:" # Indicate AI turn

    def _build_tool_decision_prompt(self) -> str:
        """Build a prompt for the LLM to decide if a tool is needed."""
        return (
            "You are a tool-use agent. Your task is to analyze the conversation history "
            "and decide if calling a tool would be beneficial to answer the user's latest query. "
            "If a tool is needed, respond with a JSON object containing 'tool' and 'args'. "
            "Otherwise, respond with a regular text message to continue the conversation directly. "
            "Only output the tool JSON, or directly start your response as ASSISTANT. "
            "Consider the available tools and their descriptions: "
            f"{self.system_prompt}" # Includes tool descriptions
            "\n\nBased on the history, should I call a tool?"
            "\n[ASSISTANT]: " # Indicate AI turn to make decision
        )

    async def _execute_tool(self, tool_name: str, args: Dict) -> Dict:
        """Execute the specified tool."""
        if tool_name == "search_commits":
            # Semantic search can be slow. Use keyword search for quick chat.
            from devlog.core.search import search_commits as keyword_search_commits
            results = await asyncio.to_thread(keyword_search_commits, query=args.get('query'), limit=args.get('limit', 3))
            formatted_results = []
            for commit in results:
                formatted_results.append({
                    "short_hash": commit['short_hash'],
                    "message": commit['message'],
                    "repo_name": commit['repo_name'],
                    "files_changed": [{"file_path": f['file_path'], "change_type": f['change_type']} for f in commit.get('files', [])[:2]] # Limit files
                })
            return {"tool_name": "search_commits", "results": formatted_results}
        
        elif tool_name == "web_search":
            results = await asyncio.to_thread(self.web_searcher.search, query=args.get('query'), num_results=args.get('limit', 3))
            formatted_results = []
            for res in results:
                formatted_results.append({
                    "title": res['title'],
                    "url": res['url'],
                    "snippet": res['snippet']
                })
            return {"tool_name": "web_search", "results": formatted_results}
        
        else:
            return {"error": f"Unknown tool: {tool_name}"}

    async def _stream_llm_response(self, prompt: str) -> AsyncGenerator[str, None]:
        """Stream response from the LLM."""
        response_generator = await analyze_code(
            prompt=prompt, # Use the full prompt
            code="", # No specific code context here, it's in the prompt history
            language="text", # Treat as plain text
            stream=True # Request streaming response
        )
        
        if isinstance(response_generator, AsyncGenerator):
            full_response_content = []
            async for chunk in response_generator:
                full_response_content.append(chunk)
                yield chunk
            self.history.append({"role": "assistant", "content": "".join(full_response_content)})
        else:
            # Fallback if streaming somehow didn't work (e.g., error generator)
            self.history.append({"role": "assistant", "content": response_generator})
            yield response_generator

    def get_history(self) -> List[Dict]:
        return self.history

    def clear_history(self):
        self.history = []
