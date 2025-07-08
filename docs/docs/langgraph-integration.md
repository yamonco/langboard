# Integrating Multiple Agents with LangGraph

LangGraph can be used to coordinate multiple agents in a single workflow. Each node in the graph represents an agent, and edges define how messages flow between them.

```python
from langgraph.graph import Graph, END
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-3.5-turbo")

def ask_agent(query: str) -> str:
    """Generate a follow-up question from the initial query."""
    return llm.invoke(query).content


def answer_agent(question: str) -> str:
    """Provide an answer to the question."""
    return llm.invoke(f"Answer the following question:\n{question}").content


graph = Graph()
graph.add_node("ask", ask_agent)
graph.add_node("answer", answer_agent)

# connect the agents
graph.add_edge("ask", "answer")
# finish the workflow after the answer is produced
graph.add_edge("answer", END)

result = graph.invoke("2018년 월드컵 우승팀은?")
print(result)
```

The first agent generates a question, which is then passed to the second agent that returns the final answer. You can expand this pattern to include more complex chains or conditional branches.
