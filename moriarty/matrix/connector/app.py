import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Response

from moriarty.log import logger
from moriarty.matrix.connector.invoker import Invoker, get_invoker
from moriarty.matrix.connector.params import InvokeParams, InvokeResponse

TOKEN = os.getenv("MORIARTY_MATRIX_TOKEN")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if TOKEN:
        logger.info(f"Token: {TOKEN}")
    else:
        logger.info("Token not set, authentication is disabled")

    yield


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def verify_token(request, call_next):
    if request.url.path == "/":
        return await call_next(request)

    if TOKEN and request.headers.get("Authorization") != f"Bearer {TOKEN}":
        return Response(status_code=401, content="Unauthorized, check token")
    return await call_next(request)


@app.post("/invoke")
async def invoke(
    params: InvokeParams,
    invoker: Invoker = Depends(get_invoker),
) -> InvokeResponse:
    return await invoker.invoke(params)


@app.get("/")
async def root():
    return {"message": "Hello World"}
