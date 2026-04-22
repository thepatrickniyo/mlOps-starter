from fastapi import FastAPI
import uvicorn

app = FastAPI()

@app.get("/")
def read_root():
    return {"status": "Model API is online"}

@app.post("/predict")
def predict(data: dict):
    # Logic for model inference would go here
    return {"prediction": "dummy_result", "input": data}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)