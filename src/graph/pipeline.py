"""LangGraph assembly for the HorRAGor multi-agent workflow."""

from langgraph.graph import END, START, StateGraph

from ..models.state import AgentState
from .router import should_scrape_or_narrate
from .tools_nodes import narration_node, rag_node, scraper_node

workflow = StateGraph(AgentState)
workflow.add_node("rag", rag_node)
workflow.add_node("scraper", scraper_node)
workflow.add_node("narration", narration_node)
workflow.add_edge(START, "rag")
workflow.add_conditional_edges(
	"rag",
	should_scrape_or_narrate,
	{
		"scraper": "scraper",
		"narration": "narration",
	},
)
workflow.add_edge("scraper", "narration")
workflow.add_edge("narration", END)

app = workflow.compile()
