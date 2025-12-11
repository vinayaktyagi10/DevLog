"""
LLM Integration for Code Analysis using Ollama
"""
import requests
import json
from typing import Optional, Dict
import re


class LLMConfig:
    """Configuration for LLM analysis"""
    BASE_URL = "http://localhost:11434/api/generate"
    MODEL = "llama3.2:3b"
    TIMEOUT = 120
    MAX_CODE_LENGTH = 4000  # Characters to avoid context overflow


def chunk_code(code: str, max_length: int = LLMConfig.MAX_CODE_LENGTH) -> list:
    """
    Split code into manageable chunks for analysis

    Args:
        code: Source code to chunk
        max_length: Maximum characters per chunk

    Returns:
        List of code chunks
    """
    if len(code) <= max_length:
        return [code]

    lines = code.split('\n')
    chunks = []
    current_chunk = []
    current_length = 0

    for line in lines:
        line_length = len(line) + 1  # +1 for newline

        if current_length + line_length > max_length and current_chunk:
            # Save current chunk
            chunks.append('\n'.join(current_chunk))
            current_chunk = [line]
            current_length = line_length
        else:
            current_chunk.append(line)
            current_length += line_length

    # Add remaining chunk
    if current_chunk:
        chunks.append('\n'.join(current_chunk))

    return chunks


def analyze_code(prompt: str, code: str, language: str) -> str:
    """
    Analyze code using Ollama LLM

    Args:
        prompt: Analysis instructions
        code: Code to analyze
        language: Programming language

    Returns:
        Analysis text from LLM
    """
    # Check if code is too long
    if len(code) > LLMConfig.MAX_CODE_LENGTH:
        # Analyze in chunks and combine
        chunks = chunk_code(code)
        results = []

        for i, chunk in enumerate(chunks):
            chunk_prompt = f"{prompt}\n\nAnalyzing part {i+1} of {len(chunks)}:\n\n"
            result = _call_ollama(chunk_prompt, chunk, language)
            if result:
                results.append(result)

        # Combine results
        return "\n\n".join(results)
    else:
        return _call_ollama(prompt, code, language)


def _call_ollama(prompt: str, code: str, language: str) -> str:
    """
    Make API call to Ollama

    Args:
        prompt: Analysis prompt
        code: Code snippet
        language: Programming language

    Returns:
        LLM response text
    """
    full_prompt = f"""{prompt}

```{language}
{code}
```

Provide specific, actionable feedback."""

    payload = {
        "model": LLMConfig.MODEL,
        "prompt": full_prompt,
        "stream": False,
        "options": {
            "temperature": 0.3,  # Lower for more focused analysis
            "top_p": 0.9,
        }
    }

    try:
        response = requests.post(
            LLMConfig.BASE_URL,
            json=payload,
            timeout=LLMConfig.TIMEOUT
        )

        if response.status_code != 200:
            return f"Error: LLM returned status {response.status_code}"

        data = response.json()
        return data.get("response", "No response from LLM")

    except requests.exceptions.Timeout:
        return "Error: LLM request timed out"
    except requests.exceptions.ConnectionError:
        return "Error: Could not connect to Ollama. Is it running?"
    except Exception as e:
        return f"Error: {str(e)}"


def test_connection() -> bool:
    """
    Test if Ollama is running and accessible

    Returns:
        True if connection successful
    """
    try:
        # Try a simple prompt
        payload = {
            "model": LLMConfig.MODEL,
            "prompt": "Say 'OK' if you're working.",
            "stream": False
        }

        response = requests.post(
            LLMConfig.BASE_URL,
            json=payload,
            timeout=10
        )

        return response.status_code == 200

    except:
        return False


def analyze_quick(code: str, language: str, file_path: str) -> Dict:
    """
    Quick analysis: find immediate issues

    Args:
        code: Source code
        language: Programming language
        file_path: Path to file

    Returns:
        Dictionary with issues and suggestions
    """
    prompt = f"""Analyze this {language} code from {file_path} for immediate issues.

Focus on:
1. Potential bugs or logic errors
2. Security vulnerabilities
3. Performance problems
4. Code smell

Provide output in this exact format:
ISSUES:
- [specific issue with line context]

SUGGESTIONS:
- [actionable fix]"""

    result = analyze_code(prompt, code, language)
    return _parse_structured_response(result)


def analyze_deep(code: str, language: str) -> Dict:
    """
    Deep analysis: patterns, architecture, complexity

    Args:
        code: Source code
        language: Programming language

    Returns:
        Dictionary with patterns, anti-patterns, and complexity analysis
    """
    prompt = f"""Perform deep analysis of this {language} code.

Analyze:
1. Design patterns used (name them specifically)
2. Anti-patterns present (code smells, bad practices)
3. Cyclomatic complexity concerns
4. Maintainability issues

Format:
PATTERNS:
- [pattern name]: [how it's used]

ANTI_PATTERNS:
- [anti-pattern]: [why it's problematic]

COMPLEXITY:
- [issue]: [recommendation]"""

    result = analyze_code(prompt, code, language)
    return _parse_structured_response(result)


def suggest_improvements(code: str, language: str, context: str = "") -> Dict:
    """
    Generate specific improvement suggestions

    Args:
        code: Source code
        language: Programming language
        context: Additional context about the code

    Returns:
        Dictionary with improvement suggestions
    """
    context_str = f"\n\nContext: {context}" if context else ""

    prompt = f"""Suggest specific improvements for this {language} code.{context_str}

Provide:
1. Code refactoring opportunities
2. Better alternatives for current approach
3. Modern best practices not being followed
4. Specific code examples where helpful

Format:
REFACTORING:
- [what to refactor and why]

ALTERNATIVES:
- [better approach with brief example]

BEST_PRACTICES:
- [practice not followed and how to fix]"""

    result = analyze_code(prompt, code, language)
    return _parse_structured_response(result)


def compare_with_best_practices(code: str, language: str, topic: str) -> str:
    """
    Compare code against best practices for a specific topic

    Args:
        code: Source code
        language: Programming language
        topic: Specific topic (e.g., "authentication", "database queries")

    Returns:
        Comparison analysis text
    """
    prompt = f"""Compare this {language} code with current best practices for {topic}.

Analyze:
1. What's good about the current implementation
2. What's missing compared to best practices
3. Security considerations
4. Performance considerations
5. Specific recommendations with examples

Provide a detailed comparison."""

    return analyze_code(prompt, code, language)


def _parse_structured_response(response: str) -> Dict:
    """
    Parse LLM response into structured format

    Args:
        response: Raw LLM response text

    Returns:
        Dictionary with parsed sections
    """
    result = {
        'raw': response,
        'issues': [],
        'suggestions': [],
        'patterns': [],
        'anti_patterns': [],
        'complexity': [],
        'refactoring': [],
        'alternatives': [],
        'best_practices': []
    }

    current_section = None
    section_map = {
        'ISSUES:': 'issues',
        'SUGGESTIONS:': 'suggestions',
        'PATTERNS:': 'patterns',
        'ANTI_PATTERNS:': 'anti_patterns',
        'ANTI-PATTERNS:': 'anti_patterns',
        'COMPLEXITY:': 'complexity',
        'REFACTORING:': 'refactoring',
        'ALTERNATIVES:': 'alternatives',
        'BEST_PRACTICES:': 'best_practices',
        'BEST PRACTICES:': 'best_practices',
    }

    for line in response.split('\n'):
        line = line.strip()

        # Check if this is a section header
        for header, section in section_map.items():
            if header in line.upper():
                current_section = section
                break

        # Extract bullet points
        if line.startswith('-') and current_section:
            item = line[1:].strip()
            if item and current_section in result:
                result[current_section].append(item)

    return result


def generate_analysis_summary(issues: list, suggestions: list, patterns: list) -> str:
    """
    Generate human-readable summary of analysis

    Args:
        issues: List of issues found
        suggestions: List of suggestions
        patterns: List of patterns identified

    Returns:
        Summary text
    """
    parts = []

    if issues:
        parts.append(f"Found {len(issues)} issues to address")

    if suggestions:
        parts.append(f"{len(suggestions)} improvement suggestions")

    if patterns:
        parts.append(f"Identified {len(patterns)} patterns")

    if not parts:
        return "No significant issues found"

    return ", ".join(parts)
