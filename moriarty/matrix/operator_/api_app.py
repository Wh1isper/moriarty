import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Response

from moriarty.log import logger
from moriarty.matrix.operator_.operator_ import Operator, get_operaotr
from moriarty.sidecar.params import MatrixCallback

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


@app.get("/")
async def root():
    return {"message": "Hello World"}
