# DevLog - Personal Code Review Assistant

DevLog is a powerful local-first CLI and TUI tool designed to track your coding activity, analyze your commits using local LLMs (via Ollama), and provide deep code reviews by comparing your work against web-based best practices.

It acts as an automated developer journal that not only records *what* you changed but helps you understand *how* to improve it.

## 🚀 Key Features

*   **Repository Tracking**: Automatically captures every commit you make in tracked repositories using Git hooks.
*   **AI-Powered Analysis**: Uses local LLMs (Ollama) to analyze commits for bugs, code quality, and design patterns.
*   **Web-Enhanced Reviews**: `devlog review` searches the web for best practices on a specific topic and compares your recent code against them.
*   **Semantic Search**: Search your commit history not just by keyword, but by meaning (e.g., "commits where I fixed memory leaks").
*   **Interactive TUI**: A full-featured terminal user interface for exploring your history, viewing diffs, and running analyses without remembering CLI commands.
*   **Statistics**: Visualize your coding habits, languages used, and activity trends.
*   **Privacy Focused**: All data is stored locally in SQLite. All AI analysis is performed locally using Ollama.

## 🛠 Prerequisites

1.  **Python 3.10+**
2.  **Ollama**: DevLog relies on [Ollama](https://ollama.com/) for local AI analysis.
    *   Install Ollama.
    *   Pull a model (e.g., `llama3`, `mistral`, or `codellama`):
        ```bash
        ollama pull llama3
        ```
    *   Start the server:
        ```bash
        ollama serve
        ```

## 📦 Installation

1.  **Clone the repository:**
    ```bash
    git clone <your-repo-url>
    cd devlog
    ```

2.  **Set up a virtual environment:**
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -e .
    ```

4.  **Run the setup script (Optional):**
    This script helps create a system-wide `devlog` alias or symlink.
    ```bash
    ./setup_devlog.sh
    ```

## 📖 Usage Guide

### 1. Start Tracking
Tell DevLog to watch a repository. This installs a `post-commit` hook.
```bash
devlog track /path/to/your/project
```

### 2. Work as Usual
Make changes and commit them using git. DevLog captures the data automatically in the background.
```bash
git add .
git commit -m "Refactored login logic"
# DevLog captures this instantly!
```

### 3. Analyze Commits
Ask the AI to analyze a specific commit.
```bash
# Get the hash from `git log` or `devlog commits`
devlog analyze <commit-hash>
```

### 4. Interactive Mode (TUI)
Launch the interactive UI to browse repos, commits, and run analyses visually.
```bash
devlog tui
```
*   **Navigation**: Use mouse or arrow keys.
*   **Actions**: Press `a` to analyze the selected commit.

### 5. Deep Code Review
Compare your implementation of a feature against top search results from the web.
```bash
devlog review "Python async context managers" --language python
```
This command:
1. Searches the web for "Python async context managers best practices".
2. Scrapes the content and extracts code examples.
3. Finds your relevant local commits.
4. Uses the LLM to generate a report comparing your code to the industry standards.

### 6. Search
```bash
# Keyword search
devlog find "authentication"

# Semantic search (requires embedding first)
devlog embed  # Run once to generate embeddings
devlog semantic "commits related to database performance"
```

## 🧩 Commands Reference

| Command | Description |
|---------|-------------|
| `devlog track <path>` | Start tracking a repository |
| `devlog untrack <path>` | Stop tracking a repository |
| `devlog repos` | List tracked repositories |
| `devlog commits` | Show recent commits across all repos |
| `devlog analyze <hash>` | Analyze a commit with AI |
| `devlog review <topic>` | Generate a best-practices review |
| `devlog stats` | Show coding statistics |
| `devlog tui` | Open the Terminal User Interface |
| `devlog find <query>` | Keyword search in commits |
| `devlog semantic <query>` | Semantic search (concept-based) |
| `devlog help` | Show full help message |

## ⚠️ Current Status & Notes

*   **Beta**: The project is functional but evolving.
*   **Search Backends**: Web search relies on DuckDuckGo (default) or Brave Search. Rate limits may apply.
*   **Chat Interface**: There is an experimental chat interface accessible via `devlog-chat` (or `python -m devlog.cli.chat_tui`), but it is currently separate from the main TUI.
*   **Ollama Dependency**: Analysis commands will fail gracefully if Ollama is not running.
