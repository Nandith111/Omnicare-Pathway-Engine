from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from langserve import add_routes
import uvicorn
from agents import WorkflowEngine

# 1. Initialize the FastAPI application
app = FastAPI(
    title="OmniCare Pathway API",
    version="1.0",
    description="REST API for the Agentic Multi-Hop GraphRAG Rare Disease Diagnostic Engine",
)

@app.get("/")
async def redirect_root_to_docs():
    return RedirectResponse("/docs")

# 2. Compile the core engine
engine = WorkflowEngine()
app_graph = engine.compile_graph()

# 3. Expose the LangGraph via LangServe routes
# A compiled StateGraph is natively compatible with LangChain's Runnable interface
add_routes(
    app,
    app_graph,
    path="/omnicare",
)

if __name__ == "__main__":
    print("🚀 Starting OmniCare API Engine on http://localhost:8000")
    uvicorn.run(app, host="localhost", port=8000)