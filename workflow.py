from langgraph.graph import END, START, StateGraph

from agents.bill_agent import bill_agent_node
from agents.discharge_agent import discharge_agent_node
from agents.id_agent import id_agent_node
from agents.segregator import segregator_node
from models.schemas import ClaimState


def aggregator_node(state: ClaimState) -> dict:
    page_classifications = state.get("page_classifications", {})

    pages_by_type: dict[str, int] = {}
    for doc_type in page_classifications.values():
        pages_by_type[doc_type] = pages_by_type.get(doc_type, 0) + 1

    agents_invoked: list[str] = []
    if state.get("id_pages"):
        agents_invoked.append("id_agent")
    if state.get("discharge_pages"):
        agents_invoked.append("discharge_agent")
    if state.get("bill_pages"):
        agents_invoked.append("bill_agent")

    final_output = {
        "claim_id": state["claim_id"],
        "status": "success",
        "page_classification": {
            str(k): v for k, v in page_classifications.items()
        },
        "extracted_data": {
            "identity": state.get("identity_data", {}),
            "discharge_summary": state.get("discharge_data", {}),
            "itemized_bill": state.get("bill_data", {}),
        },
        "processing_metadata": {
            "total_pages": state.get("total_pages", 0),
            "pages_by_type": pages_by_type,
            "agents_invoked": agents_invoked,
        },
    }

    return {"final_output": final_output}


def build_workflow():
    graph = StateGraph(ClaimState)

    graph.add_node("segregator", segregator_node)
    graph.add_node("id_agent", id_agent_node)
    graph.add_node("discharge_agent", discharge_agent_node)
    graph.add_node("bill_agent", bill_agent_node)
    graph.add_node("aggregator", aggregator_node)

    graph.add_edge(START, "segregator")

    # Fan-out: three extraction agents run in parallel after segregator
    graph.add_edge("segregator", "id_agent")
    graph.add_edge("segregator", "discharge_agent")
    graph.add_edge("segregator", "bill_agent")

    # Fan-in: aggregator waits for all three to complete
    graph.add_edge("id_agent", "aggregator")
    graph.add_edge("discharge_agent", "aggregator")
    graph.add_edge("bill_agent", "aggregator")

    graph.add_edge("aggregator", END)

    return graph.compile()
