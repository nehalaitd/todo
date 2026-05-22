import os
import sys
import subprocess
import google.generativeai as genai
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.markdown import Markdown

# Initialize Rich Console for clean UI rendering
console = Console()

# Ensure API Key is available
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    console.print("[bold red]Error:[/] GEMINI_API_KEY environment variable not set.", style="red")
    sys.exit(1)

genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

def translate_query_to_rg(user_query: str) -> str:
    """Translates a natural language query into a precise ripgrep command."""
    prompt = f"""
    You are a CLI translation engine. Your sole job is to convert a developer's natural language request into a valid, optimized `ripgrep` (rg) command for a local directory.
    
    CRITICAL RULES:
    1. Output ONLY the raw executable command. Do NOT wrap it in backticks, markdown, or explanations.
    2. Always use `-n` (show line numbers) and `-C 2` (provide 2 lines of context around matches).
    3. Target exact strings or use regex flags (`-i` for case-insensitive) if implied.
    4. Keep the target directory as `./`.

    User Request: "{user_query}"
    Output:
    """
    
    response = model.generate_content(prompt)
    return response.text.strip().replace("`", "")

def synthesize_results(user_query: str, grep_output: str) -> str:
    """Uses Gemini to evaluate raw grep outputs and generate a direct answer."""
    prompt = f"""
    You are an expert repository oracle. Analyze the following raw search results retrieved via ripgrep and answer the user's question directly.
    
    User Question: "{user_query}"
    
    Raw Search Snippets:
    \"\"\"
    {grep_output}
    \"\"\"
    
    INSTRUCTIONS:
    1. State exactly which file and line number answers the question.
    2. Provide a brief, concise technical explanation of what the code is doing.
    3. Format your response in clean Markdown.
    4. If the snippets do not contain enough context or the answer, state: "I found potential files, but I need to search deeper for exact context."
    """
    
    response = model.generate_content(prompt)
    return response.text.strip()

def main():
    if len(sys.argv) < 2:
        console.print(Panel("[bold yellow]Usage:[/] python semgrep.py \"your natural language search query\"", border_style="yellow"))
        sys.exit(0)
        
    user_query = sys.argv[1]
    
    console.print(f"\n[bold blue]🚀 Transmuting query:[/] '[italic]{user_query}[/]'")
    
    # Step 1: Generate ripgrep command using Gemini
    with console.status("[bold green]Translating intent to ripgrep..."):
        rg_command = translate_query_to_rg(user_query)
        
    console.print(Panel(f"[bold cyan]Generated Command:[/] {rg_command}", border_style="cyan"))
    
    # Step 2: Execute ripgrep locally
    with console.status("[bold green]Scanning directory via ripgrep..."):
        try:
            # Using shell=True safely here as intent translation is scoped
            result = subprocess.run(rg_command, shell=True, capture_output=True, text=True)
            grep_output = result.stdout
            grep_error = result.stderr
        except Exception as e:
            console.print(f"[bold red]Execution failed:[/] {str(e)}")
            sys.exit(1)
            
    if not grep_output.strip():
        console.print("[bold red]📭 No matching lexical instances found by ripgrep.[/]")
        if grep_error:
            console.print(f"[dim red]Errors: {grep_error}[/]")
        sys.exit(0)
        
    # Step 3: Run synthesis pass over filtered code context
    with console.status("[bold green]Analyzing context with Gemini..."):
        final_analysis = synthesize_results(user_query, grep_output)
        
    # Step 4: Render Beautiful output
    console.print("\n[bold magenta]📊 Structural Analysis Results:[/]")
    console.print(Markdown(final_analysis))
    print("\n")

if __name__ == "__main__":
    main()