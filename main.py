import uvicorn

from zpay import config

if __name__ == "__main__":
    uvicorn.run("zpay.app:app", host="127.0.0.1", port=config.PORT)
