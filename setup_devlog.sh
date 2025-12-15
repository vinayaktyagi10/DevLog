#!/bin/bash

# Setup script for DevLog

PROJECT_DIR="$(pwd)"
VENV_BIN="$PROJECT_DIR/.venv/bin/devlog"
SHELL_RC=""

# Detect shell
if [ -n "$BASH_VERSION" ]; then
    SHELL_RC="$HOME/.bashrc"
elif [ -n "$ZSH_VERSION" ]; then
    SHELL_RC="$HOME/.zshrc"
fi

echo "DevLog Setup"
echo "============"
echo "Project directory: $PROJECT_DIR"

if [ ! -f "$VENV_BIN" ]; then
    echo "Error: Virtual environment executable not found at $VENV_BIN"
    echo "Please run: python3 -m venv .venv && source .venv/bin/activate && pip install -e ."
    exit 1
fi

echo ""
echo "Choose an option to make 'devlog' accessible system-wide:"
echo "1) Add alias to $SHELL_RC (Safest)"
echo "2) Create symlink in ~/.local/bin (Standard Linux)"
echo "3) Do nothing"
echo ""
read -p "Enter choice [1-3]: " choice

case $choice in
    1)
        if [ -z "$SHELL_RC" ]; then
            echo "Could not detect shell RC file. Please add this alias manually:"
            echo "alias devlog='$VENV_BIN'"
        else
            echo "" >> "$SHELL_RC"
            echo "# DevLog alias" >> "$SHELL_RC"
            echo "alias devlog='$VENV_BIN'" >> "$SHELL_RC"
            echo "Added alias to $SHELL_RC"
            echo "Please restart your shell or run: source $SHELL_RC"
        fi
        ;;
    2)
        mkdir -p "$HOME/.local/bin"
        ln -sf "$VENV_BIN" "$HOME/.local/bin/devlog"
        echo "Created symlink at $HOME/.local/bin/devlog"
        echo "Ensure $HOME/.local/bin is in your PATH."
        ;;
    3)
        echo "Skipping setup."
        ;;
    *)
        echo "Invalid choice."
        ;;
esac

echo ""
echo "Dependencies have been updated in pyproject.toml."
echo "If you haven't already, run: pip install -e ."
echo ""
echo "Done!"
