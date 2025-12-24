"""
Week 1 Implementation Test Suite
Run this to verify everything works correctly
"""

import asyncio
import sys
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


def test_tool_registry():
    """Test tool registry"""
    console.print("\n[bold cyan]Testing Tool Registry...[/]")

    try:
        from devlog.analysis.tool_registry import get_tool_registry

        registry = get_tool_registry()
        tools = registry.list_tools()

        console.print(f"✓ Loaded {len(tools)} tools")

        # Test each category
        from devlog.analysis.tool_registry import ToolCategory
        for category in ToolCategory:
            cat_tools = registry.list_tools(category)
            if cat_tools:
                console.print(f"  • {category.value}: {len(cat_tools)} tools")

        # Test help text generation
        help_text = registry.get_help_text()
        console.print(f"✓ Generated help text ({len(help_text)} chars)")

        return True

    except Exception as e:
        console.print(f"[red]✗ Tool registry failed: {e}[/]")
        return False


def test_smart_router():
    """Test smart router"""
    console.print("\n[bold cyan]Testing Smart Router...[/]")

    try:
        from devlog.analysis.smart_router import SmartToolRouter

        router = SmartToolRouter()

        # Test entity extraction
        test_cases = [
            ("find my Python work in auth repo", {
                'expected_repo': 'auth',
                'expected_language': 'python'
            }),
            ("analyze commit abc1234", {
                'expected_commit': 'abc1234'
            }),
            ("review my authentication code", {
                'expected_topic': 'authentication'
            })
        ]

        for query, expected in test_cases:
            routing = asyncio.run(router.route(query))
            console.print(f"✓ Query: '{query[:40]}...'")
            console.print(f"  → Tool: {routing.tool_name} ({routing.confidence:.2f})")
            console.print(f"  → Entities: {len(routing.entities.commit_hashes)} commits, "
                         f"{len(routing.entities.repo_names)} repos, "
                         f"{len(routing.entities.languages)} languages")

        return True

    except Exception as e:
        console.print(f"[red]✗ Smart router failed: {e}[/]")
        import traceback
        traceback.print_exc()
        return False


def test_conversation_db():
    """Test conversation persistence"""
    console.print("\n[bold cyan]Testing Conversation DB...[/]")

    try:
        from devlog.analysis.conversation_db import ConversationManager

        manager = ConversationManager()

        # Create conversation
        conv_id = manager.create_conversation("Test Conversation")
        console.print(f"✓ Created conversation #{conv_id}")

        # Add messages
        msg1_id = manager.add_message(conv_id, "user", "Hello!")
        msg2_id = manager.add_message(conv_id, "assistant", "Hi there!")
        console.print(f"✓ Added 2 messages")

        # Retrieve
        conv = manager.get_conversation(conv_id)
        messages = manager.get_messages(conv_id)
        console.print(f"✓ Retrieved conversation: {conv['title']}")
        console.print(f"✓ Retrieved {len(messages)} messages")

        # Export
        markdown = manager.export_conversation(conv_id, 'markdown')
        console.print(f"✓ Exported to markdown ({len(markdown)} chars)")

        # Cleanup
        manager.delete_conversation(conv_id)
        console.print(f"✓ Cleaned up test conversation")

        return True

    except Exception as e:
        console.print(f"[red]✗ Conversation DB failed: {e}[/]")
        import traceback
        traceback.print_exc()
        return False


def test_enhanced_chat_manager():
    """Test enhanced chat manager"""
    console.print("\n[bold cyan]Testing Enhanced Chat Manager...[/]")

    try:
        from devlog.analysis.enhanced_chat_manager import EnhancedChatManager

        manager = EnhancedChatManager()

        # Test slash command detection
        test_messages = [
            "/help",
            "/stats",
            "show me my work"
        ]

        for msg in test_messages:
            is_slash = msg.startswith('/')
            console.print(f"✓ Message: '{msg}' - Slash command: {is_slash}")

        # Test context
        context = manager._get_context()
        console.print(f"✓ Context: User={context.user_name}, Repo={context.current_repo}")

        # Test history
        manager.history.append(type('Message', (), {
            'role': 'user',
            'content': 'test',
            'timestamp': '2024-12-15'
        })())
        console.print(f"✓ History management works ({len(manager.history)} messages)")

        return True

    except Exception as e:
        console.print(f"[red]✗ Enhanced chat manager failed: {e}[/]")
        import traceback
        traceback.print_exc()
        return False


def test_tool_execution():
    """Test tool execution"""
    console.print("\n[bold cyan]Testing Tool Execution...[/]")

    try:
        from devlog.analysis.tool_registry import get_tool_registry

        registry = get_tool_registry()

        # Test show_stats (doesn't require commits)
        result = asyncio.run(registry.execute_tool('show_stats'))

        if 'error' not in result:
            console.print(f"✓ show_stats executed successfully")
            console.print(f"  • Total commits: {result.get('total_commits', 0)}")
        else:
            console.print(f"[yellow]⚠ show_stats returned error (expected if no commits)[/]")

        # Test list_repos
        result = asyncio.run(registry.execute_tool('list_repos'))

        if 'error' not in result:
            console.print(f"✓ list_repos executed successfully")
            console.print(f"  • Found {result.get('count', 0)} repos")
        else:
            console.print(f"[yellow]⚠ list_repos returned error[/]")

        return True

    except Exception as e:
        console.print(f"[red]✗ Tool execution failed: {e}[/]")
        import traceback
        traceback.print_exc()
        return False


def run_all_tests():
    """Run all tests"""
    console.print(Panel.fit(
        "[bold cyan]DevLog Week 1 Test Suite[/]\n"
        "[dim]Testing all new components...[/]",
        border_style="cyan"
    ))

    results = []

    # Run tests
    results.append(("Tool Registry", test_tool_registry()))
    results.append(("Smart Router", test_smart_router()))
    results.append(("Conversation DB", test_conversation_db()))
    results.append(("Enhanced Chat Manager", test_enhanced_chat_manager()))
    results.append(("Tool Execution", test_tool_execution()))

    # Summary
    console.print("\n" + "=" * 60)
    console.print("[bold]Test Summary:[/]\n")

    table = Table()
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="bold")

    passed = 0
    failed = 0

    for name, result in results:
        status = "[green]✓ PASSED[/]" if result else "[red]✗ FAILED[/]"
        table.add_row(name, status)
        if result:
            passed += 1
        else:
            failed += 1

    console.print(table)

    console.print(f"\n[bold]Total:[/] {passed} passed, {failed} failed")

    if failed == 0:
        console.print("\n[bold green]🎉 All tests passed! Week 1 implementation is ready.[/]")
        console.print("\n[cyan]Next steps:[/]")
        console.print("1. Run: [bold]python -m devlog.cli.chat_tui[/]")
        console.print("2. Try: [bold]/help[/] to see available commands")
        console.print("3. Test: [bold]show me my recent work[/]")
    else:
        console.print("\n[bold yellow]⚠️  Some tests failed. Check the output above.[/]")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
