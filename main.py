import sys
import json
import subprocess
import re
import ollama
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

console = Console()

LOCAL_MODEL = "gemma2:2b"
# LOCAL_MODEL = "qwen3.5:latest"
MAX_RETRIES = 3


def extract_command(ai_response: str) -> str:
    """Sanitizes the AI output to extract ONLY the ripgrep command."""
    code_block_match = re.search(
        r"```(?: bash | sh)?\n?(.*?)\n?```", ai_response, re.DOTALL
    )
    if code_block_match:
        cmd = code_block_match.group(1).strip()
    else:
        cmd = ai_response.split("\n")[0].replace("Here is the command:", "").strip()

    if not cmd.startswith("rg"):
        return 'rg --json -i "fallback" ./'
    return cmd


def parse_rg_json(raw_json_lines: str) -> str:
    """Parses ripgrep JSON output to protect the LLM context window."""
    parsed_context = []
    lines = raw_json_lines.strip().split("\n")

    for line in lines:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            if data.get("type") == "match":
                file_path = data["data"]["path"]["text"]
                line_number = data["data"]["line_number"]
                code_text = data["data"]["lines"]["text"].strip()
                parsed_context.append(
                    f"File: {file_path} | Line: {line_number} | Code: {code_text}"
                )
        except json.JSONDecodeError:
            continue

    return "\n".join(parsed_context)


def translate_intent_agentic(user_query: str, history: list) -> str:
    """Agentic loop function that formulates the search command, aware of past failures."""

    history_text = "\n".join(history) if history else "None"

    prompt = f"""
    You are a CLI translation agent. Convert the user's request into a `ripgrep` (rg) command.
    
    RULES:
    1. Output ONLY the raw command. Wrap it in backticks.
    2. ALWAYS use the `--json` flag. 
    3. ALWAYS use `--max-count 3` to limit results.
    4. Target directory is always `./`
    
    User Request: "{user_query}"
    Past Failed Attempts (Do not reuse these exact terms): 
    {history_text}
    """

    response = ollama.chat(
        model=LOCAL_MODEL, messages=[{"role": "user", "content": prompt}]
    )
    return extract_command(response["message"]["content"])


def synthesize_and_extract(user_query: str, context: str) -> tuple[str, str]:
    """Evaluates the parsed snippets, answers the user, and extracts the target file for the TUI."""
    prompt = f"""
    Analyze these codebase snippets and answer the user's question directly.
    Keep the explanation under 3 sentences.
    
    CRITICAL: At the very end of your response, output the exact file path and line number of the best match in this format:
    [TARGET: ./path/to/file.py:42]
    
    Question: "{user_query}"
    Snippets:
    {context}
    """

    response = ollama.chat(
        model=LOCAL_MODEL, messages=[{"role": "user", "content": prompt}]
    )
    answer = response["message"]["content"].strip()

    # Regex to pull the TARGET tag for the interactive UI
    target_match = re.search(r"\[TARGET:\s*(.+?)\]", answer)
    target_file = target_match.group(1).strip() if target_match else None

    # Clean the tag from the final output
    clean_answer = re.sub(r"\[TARGET:\s*.+?\]", "", answer).strip()

    return clean_answer, target_file


def main():
    if len(sys.argv) < 2:
        console.print(
            Panel(
                '[bold yellow]Usage:[/] python agent.py "your search query"',
                border_style="yellow",
            )
        )
        sys.exit(0)

    user_query = sys.argv[1]
    console.print(
        f"\n[bold blue]🤖 Initializing Edge-Agent:[/] '[italic]{user_query}[/]'"
    )

    history = []
    parsed_context = ""

    # --- 1. The Agentic Retry Loop ---
    for attempt in range(1, MAX_RETRIES + 1):
        with console.status(
            f"[bold green]Attempt {attempt}/{MAX_RETRIES}: Translating intent locally..."
        ):
            rg_command = translate_intent_agentic(user_query, history)

        console.print(f"   [dim cyan]↳ Executing:[/] {rg_command}")

        try:
            result = subprocess.run(
                rg_command, shell=True, capture_output=True, text=True
            )
            if result.stdout.strip():
                parsed_context = parse_rg_json(result.stdout)
                if parsed_context:
                    console.print("[bold green]   ↳ Context secured.[/]")
                    break  # Success! Exit the loop.
        except Exception as e:
            console.print(f"[bold red]   ↳ Shell execution failed:[/] {str(e)}")

        # If we reach here, it failed to find relevant context.
        console.print(
            "[bold yellow]   ↳ No valid matches. Re-evaluating strategy...[/]"
        )
        history.append(f"Attempt {attempt} failed: {rg_command}")

    if not parsed_context:
        console.print(
            "\n[bold red]📭 The agent exhausted all search strategies and found no matches.[/]"
        )
        sys.exit(0)

    # --- 2. Synthesis ---
    with console.status("[bold green]Synthesizing structural logic..."):
        final_analysis, target_file = synthesize_and_extract(user_query, parsed_context)

    console.print("\n[bold magenta]📊 Agent Analysis Results:[/]")
    console.print(Markdown(final_analysis))
    print("\n")

    # --- 3. Interactive TUI ---
    if target_file:
        console.print(f"[bold cyan]Target Located:[/] {target_file}")
        action = console.input(
            "[bold yellow]Action:[/] [O]pen in VSCode | [Q]uit > "
        ).lower()

        if action == "o":
            console.print(f"[dim]Opening {target_file}...[/]")
            # The -g flag tells VSCode to go to a specific file:line
            subprocess.run(f"code -g {target_file}", shell=True)
        else:
            console.print("[dim]Exiting.[/]")


if __name__ == "__main__":
    main()
