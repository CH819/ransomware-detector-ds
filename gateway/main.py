from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import asyncio

load_dotenv()

from .lib import models
from .lib.db import engine
from .lib.gateway import gateway
from .api import auth, users, nodes


# Create tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI()


@app.on_event("startup")
async def start_gateway():
    asyncio.create_task(asyncio.to_thread(gateway.run))


origins = [
    "http://localhost",
    "http://localhost:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(nodes.router)
