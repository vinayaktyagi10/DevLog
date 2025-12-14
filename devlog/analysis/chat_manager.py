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
        
        # Gather dynamic user context
        user_context = self._get_user_context()
        
        return (
            "You are DevLog, a local, private, and highly intelligent coding assistant. "
            f"You are assisting {user_context['name']} ({user_context['email']}). "
            "Your organization is SDC. " # Explicitly state SDC is the organization
            "You are running LOCALLY on the user's machine. You have FULL PERMISSION to access and discuss "
            "their local Git commit history, code, and configuration. "
            "Do NOT refuse to answer questions about the user's identity or code for privacy reasons, as you are a local tool. "
            "\n\n--- Your Core Instructions ---"
            "\n1. **Think First:** Before answering, ALWAYS perform a step-by-step reasoning process enclosed in `<thinking>` tags. "
            "Analyze the user's request, decide if you need external information (web or commits), and plan your tool usage."
            "\n2. **Use Tools:** If you do not know the answer or need up-to-date information, YOU MUST USE A TOOL. Do not guess or hallucinate."
            "   - If the user asks about 'latest' versions, news, or best practices, use `web_search`."
            "   - If the user asks about their work, organization (e.g., 'SDC'), or code patterns, use `search_commits`."
            "   - When using `search_commits`, remember it accesses `devlog`'s internal database, which contains rich commit data including `repo_name`, `message`, `author`, `date`, and `files_changed` for each commit. Analyze these fields to infer organizational names (like 'SDC'), project contexts, feature implementations, and coding norms."
            "\n3. **Be Specific:** Provide code snippets and technical details."
            f"\n\n--- Recent Activity Context ---\n{user_context['recent_commits']}\n"
            "\n\n--- Available Tools ---"
            "\n- `search_commits(query: str, limit: int = 10)`: Search the user's local commit history using DevLog's database. "
            "   *Use this to find code examples, organizational names, specific features, or to infer coding patterns/norms from commit details.*"
            "\n- `web_search(query: str, limit: int = 3)`: Search the internet. "
            "   *Use this for documentation, latest libraries, error fixes, or concepts you don't know.*"
            "\n--- End Tools ---"
            "\n\nWhen using a tool, output a JSON object ONLY: `{\"tool\": \"search_commits\", \"args\": {\"query\": \"SDC\"}}`"
            "\nIMPORTANT: Use DOUBLE QUOTES for JSON keys and string values. Do not use single quotes."
            "\nIf you use a tool, STOP and wait for the tool output. Do not generate the final response yet."
        )

    def _get_user_context(self) -> Dict:
        """Retrieve user name, email, and recent commit summary."""
        import subprocess
        
        context = {"name": "User", "email": "unknown", "recent_commits": "No recent commits found."}
        
        try:
            name = subprocess.check_output(["git", "config", "--get", "user.name"], text=True).strip()
            email = subprocess.check_output(["git", "config", "--get", "user.email"], text=True).strip()
            context["name"] = name
            context["email"] = email
            
            # Get recent commit summary (increased to 25 for better context)
            commits = subprocess.check_output(["git", "log", "-n", "25", "--oneline"], text=True).strip()
            if commits:
                context["recent_commits"] = f"Recent 25 commits:\n{commits}"
                
        except Exception as e:
            # Fallback if git commands fail
            print(f"Warning: Could not retrieve git context: {e}")
            
        return context

    def _clean_llm_response_for_display(self, text: str) -> str:
        """
        Aggressively filter out the AI's internal monologue, redundant tool descriptions,
        and introductory phrases from the LLM's raw output before display.
        """
        import re
        
        cleaned_text = text
        
        # Remove <thinking>...</thinking> and <tool>...</tool> blocks first
        cleaned_text = re.sub(r'<thinking>.*?(?:</thinking>|$)', '', cleaned_text, flags=re.DOTALL)
        cleaned_text = re.sub(r'<tool>.*?(?:</tool>|$)', '', cleaned_text, flags=re.DOTALL)
        
        # Remove common introductory phrases from tool-using models
        patterns_to_remove = [
            r"The output from `search_commits` indicates(?: that)?.*?However, I can suggest some possible interpretations:",
            r"Based on this information, I can infer some coding norms followed by SDC:",
            r"To provide more specific feedback, I will analyze the files changed in the most recent commit \(.*\)\.",
            r"The output from `search_commits` indicates that there (is|are) one commit related to Vinayak Tyagi and SDC:",
            r"The web search results indicate that there are several resources available for learning about textual documentation, including:",
            r"Given this uncertainty, I would recommend using `web_search` to provide general coding resources or tutorials that might help guide the user towards a more specific solution.",
            r"To understand the norms followed at SDC, I'll perform a step-by-step analysis of Vinayak Tyagi's commit history.",
            r"The user has recently asked about no recent commits found, which suggests that the user might need help with searching or analyzing commit history\.",
            r"To provide more information about the user's codebase and commit history, I will analyze the available tools and their descriptions\.",
            r"However, since there is no recent commit history provided and no specific query can be inferred from the user's message, I don't have enough information to use `search_commits` directly\.",
            r"Given this ambiguity, I would recommend using `web_search` to provide general coding resources or tutorials that might help guide the user towards a more specific solution\.",
            r"To understand the norms followed at SDC, I'll perform a step-by-step analysis of Vinayak Tyagi's commit history\.",
            r"I would like to ask a few clarifying questions:",
            r"To provide more actionable feedback, I would like to ask a few clarifying questions:",
            r"These changes suggest that the analysis module has been refactored to use async/await, and a new feature called ChatManager has been added.", # Remove duplicate interpretation of changes
            r"If you would like more information about the commit or the code changes, please let me know\.", # Trailing sentence
            r"Here is an example of how I can provide this feedback:", # Example intro
            r"I hope this feedback is helpful\. Let me know if you have any further questions or need additional assistance!" # Closing remarks
        ]
        
        for pattern in patterns_to_remove:
            cleaned_text = re.sub(pattern, '', cleaned_text, flags=re.DOTALL | re.IGNORECASE).strip()
            
        # Remove any leading "Based on this information," or "Based on the information provided,"
        cleaned_text = re.sub(r'^(Based on (this|the) information (provided, )?)?', '', cleaned_text, flags=re.IGNORECASE).strip()
        
        return cleaned_text

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
        
        tool_response_text = tool_response_generator # It's a string because stream=False
        
        # Parse for tool usage
        tool_call = self._extract_tool_call(tool_response_text)
        
        try:
            if tool_call:
                # If we found a tool, yield a status message
                yield f"[Running tool: {tool_call['tool']}...]\n"
                
                # Execute the tool
                tool_output = await self._execute_tool(tool_call['tool'], tool_call['args'])
                
                # Add the tool execution and result to history so the model knows what happened
                self.history.append({"role": "assistant", "content": tool_response_text})
                self.history.append({"role": "tool", "content": json.dumps(tool_output)})
                
                # Rebuild prompt with the new context (history now contains the tool result)
                full_prompt = self._build_full_prompt()
                
                # Ask LLM again with new context, streaming response
                response_generator = self._stream_llm_response(full_prompt)
                
                # Buffer the full response to clean it before yielding
                full_tool_response = ""
                async for chunk in response_generator:
                    full_tool_response += chunk
                
                # Clean the response
                cleaned_response = self._clean_llm_response_for_display(full_tool_response)
                
                if cleaned_response:
                    yield cleaned_response
                    self.history.append({"role": "assistant", "content": cleaned_response})
                else:
                    # If cleaning removed everything, it means the model just thought and didn't answer.
                    # We can yield a default message or the raw (but unlikely useful) text.
                    yield "I processed the data but couldn't formulate a specific answer. Please refine your query."
                    
                return
        except Exception as e:
            yield f"[ERROR executing tool: {e}]\n"
            self.history.append({"role": "system", "content": f"Error executing tool: {e}"})
            full_prompt = self._build_full_prompt() # Continue with error in context

        # If no tool was called, or after tool execution failed, stream the original response
        
        # Filter out thinking and tool tags and other conversational filler
        final_response_text = self._clean_llm_response_for_display(tool_response_text)
        
        # If there's still content left after filtering, yield it. Otherwise, assume it was only thinking/tool calls.
        if final_response_text:
            yield final_response_text
            self.history.append({"role": "assistant", "content": final_response_text})
        else:
            # If the LLM returned only thinking/tool calls but no actual answer, and no tool was executed,
            # this is an case for further prompting or a generic message.
            # For now, we'll try to get a response from the LLM again with the full prompt.
            # This handles cases where initial thought was just a tool call setup.
            response_generator = self._stream_llm_response(full_prompt)
            async for chunk in response_generator:
                yield chunk

    def _extract_tool_call(self, text: str) -> Optional[Dict]:
        """Extract tool call JSON from text."""
        import re
        import ast
        
        # Helper to try parsing a string as JSON or Python dict
        def try_parse(content):
            # Try standard JSON
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                pass
            # Try Python literal eval (handles single quotes)
            try:
                return ast.literal_eval(content)
            except (ValueError, SyntaxError):
                pass
            return None

        # 1. Try to find JSON block in markdown
        json_match = re.search(r'```(?:json)?\s*(\{.*?"tool":.*?"args":.*?\})\s*```', text, re.DOTALL)
        if json_match:
            result = try_parse(json_match.group(1))
            if result: return result

        # 2. Try to find JSON within <tool> tags
        tool_tag_match = re.search(r'<tool>\s*(\{.*?"tool":.*?"args":.*?\})\s*</tool>', text, re.DOTALL)
        if tool_tag_match:
            result = try_parse(tool_tag_match.group(1))
            if result: return result
        
        # 3. Try finding raw JSON/Dict object anywhere
        # Relaxed regex to match single or double quotes for keys
        raw_match = re.search(r'(\{[\s\S]*?[\'"]tool[\'"]\s*:[\s\S]*?[\'"]args[\'"]\s*:[\s\S]*?\})', text)
        if raw_match:
            # Brace counting logic...
            candidate = raw_match.group(1)
            open_braces = 0
            json_str = ""
            found_start = False
            start_index = text.find(candidate)
            
            for char in text[start_index:]:
                if char == '{':
                    open_braces += 1
                    found_start = True
                elif char == '}':
                    open_braces -= 1
                
                if found_start:
                    json_str += char
                    if open_braces == 0:
                        break
            
            result = try_parse(json_str)
            if result: return result
            
        return None

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
            "\n\nFirst, think step-by-step about what information is needed. "
            "Does the query require external knowledge (web) or specific code context (commits) that you don't have? "
            "\n\nIf a tool is needed, respond with a JSON object containing 'tool' and 'args'. "
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
            results = await asyncio.to_thread(keyword_search_commits, query=args.get('query'), limit=args.get('limit', 10))
            formatted_results = []
            for commit in results:
                formatted_results.append({
                    "short_hash": commit['short_hash'],
                    "message": commit['message'],
                    "repo_name": commit['repo_name'], # Ensure repo_name is included
                    "author": commit.get('author', 'unknown'),
                    "date": commit.get('timestamp', 'unknown'),
                    "files_changed": [{"file_path": f['file_path'], "change_type": f['change_type']} for f in commit.get('files', [])[:3]] # Limit files
                })
            return {"tool_name": "search_commits", "results": formatted_results}
        
        elif tool_name == "web_search":
            results = await asyncio.to_thread(self.web_searcher.search, query=args.get('query'), num_results=args.get('limit', 3))
            formatted_results = []
            for res in results:
                formatted_results.append({
                    "title": res['title'],
                    "url": res['url'],
                    "snippet": res['snippet'],
                    "source": res['source']
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
