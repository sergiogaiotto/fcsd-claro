"""
Fale com Seus Dados — CLI Agent

Usage:
    python agent.py "Quais tabelas existem?"
    python agent.py "Qual o total de vendas por região?"

Follows the deepagents/examples/text-to-sql-agent pattern.
"""

import argparse
import os
import sys

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase
from rich.console import Console
from rich.panel import Panel

load_dotenv()
console = Console()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def create_cli_agent():
    """Create a standalone CLI Deep Agent for Fale com Seus Dados."""
    from sqlalchemy import create_engine

    db_path = os.path.join(BASE_DIR, "data", "quick_insights.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    db = SQLDatabase(engine=engine, sample_rows_in_table_info=3)

    model = ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-4.1"),
        temperature=0,
    )

    toolkit = SQLDatabaseToolkit(db=db, llm=model)
    sql_tools = toolkit.get_tools()

    # Try to use deepagents if available
    try:
        from deepagents import create_deep_agent
        from deepagents.backends import FilesystemBackend

        agent = create_deep_agent(
            model=model,
            memory=[os.path.join(BASE_DIR, "AGENTS.md")],
            skills=[os.path.join(BASE_DIR, "skills/")],
            tools=sql_tools,
            subagents=[],
            backend=FilesystemBackend(root_dir=BASE_DIR),
        )
        return agent
    except ImportError:
        # Fallback: build a simple LangGraph agent
        from typing import Annotated, TypedDict
        from langchain_core.messages import SystemMessage
        from langgraph.graph import StateGraph, START, END
        from langgraph.graph.message import add_messages
        from langgraph.prebuilt import ToolNode

        class State(TypedDict):
            messages: Annotated[list, add_messages]

        agents_md = ""
        agents_path = os.path.join(BASE_DIR, "AGENTS.md")
        if os.path.exists(agents_path):
            with open(agents_path) as f:
                agents_md = f.read()

        llm_with_tools = model.bind_tools(sql_tools)

        def agent_node(state):
            msgs = [SystemMessage(content=agents_md)] + state["messages"]
            return {"messages": [llm_with_tools.invoke(msgs)]}

        def should_continue(state):
            last = state["messages"][-1]
            if hasattr(last, "tool_calls") and last.tool_calls:
                return "tools"
            return END

        graph = StateGraph(State)
        graph.add_node("agent", agent_node)
        graph.add_node("tools", ToolNode(sql_tools))
        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
        graph.add_edge("tools", "agent")

        return graph.compile()


def main():
    parser = argparse.ArgumentParser(
        description="Fale com Seus Dados CLI — Deep Agent powered by OpenAI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python agent.py "Quais tabelas existem no banco?"
  python agent.py "Qual o total de vendas por categoria?"
  python agent.py "Mostre os 5 primeiros registros da tabela clientes"
        """,
    )
    parser.add_argument("question", type=str, help="Pergunta em linguagem natural")
    args = parser.parse_args()

    console.print(Panel(
        f"[bold cyan]Pergunta:[/bold cyan] {args.question}",
        border_style="cyan",
    ))
    console.print()
    console.print("[dim]Criando Deep Agent...[/dim]")

    agent = create_cli_agent()

    console.print("[dim]Processando consulta...[/dim]\n")

    try:
        result = agent.invoke({
            "messages": [{"role": "user", "content": args.question}]
        })

        final_message = result["messages"][-1]
        answer = (
            final_message.content
            if hasattr(final_message, "content")
            else str(final_message)
        )

        console.print(Panel(
            f"[bold green]Resposta:[/bold green]\n\n{answer}",
            border_style="green",
        ))
    except Exception as e:
        console.print(Panel(
            f"[bold red]Erro:[/bold red]\n\n{str(e)}",
            border_style="red",
        ))
        sys.exit(1)


if __name__ == "__main__":
    main()
