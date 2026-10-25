import uvicorn

if __name__ == "__main__":
    # Binds to 0.0.0.0 so physical mobile devices on the same Wi-Fi can connect
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
