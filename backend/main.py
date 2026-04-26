from fastapi import FastAPI

app = FastAPI(title="Agentic Economy Demo")

@app.get("/")
def home():
    return {"message": "Agentic Economy is live!"}
