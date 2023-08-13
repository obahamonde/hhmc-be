import asyncio
import json

import aiohttp_cors
from aiofauna import *
from aiofauna.llm import LLMStack
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pytube import YouTube

from src.handlers import (audiotrack_feed_handler, audiotrack_handler,
                          get_assets)
from src.services import User, YoutubeClient, auth
from src.utils import template

load_dotenv()

llm = LLMStack()
app = APIServer()
yt = YoutubeClient()
logger = setup_logging(__name__)

@app.get("/api/assets")
async def static_dir():
    return await get_assets()


@app.get("/api/chat")
async def chat(text: str):
    return await llm.chat_with_memory(
        text=text, context="You are an MC from Urban Roosters", namespace="hhmc"
    )


@app.post("/api/tracks/upsert")
async def upload_endpoint(request: Request):
    """Takes an MP3 file, transcodes it to WAV, changes to mono, extracts the FFT and generates an embedding of 1536 dimensions that is upserted to Pinecone for further similarity search, meanwhile save the audio track to the main database, and return the `AudioTrack` object."""
    return await audiotrack_handler(request)


@app.get("/api/tracks/feed")
async def feed_endpoint(url: str):
    """Returns the 10 KNN for the given track url"""
    return await audiotrack_feed_handler(url)


@app.post("/api/auth")
async def auth_endpoint(request: Request):
    """Authenticates a user using Auth0 and saves it to the database"""
    token = request.headers.get("Authorization", "").split("Bearer ")[-1]
    user_dict = await auth.update_headers({"Authorization": f"Bearer {token}"}).get(
        "/userinfo"
    )
    user = User(**user_dict)
    response = await user.save()
    assert isinstance(response, User)
    return response.dict()


@app.websocket("/api/chat/{ref}")
async def chat_with_memory(ref: str, category:str, websocket: WebSocketResponse):
    while True:
        request = await websocket.receive_str()
        response = await llm.chat_with_memory(
            text=request, context=template(request=request,category=category), namespace=ref
        )
        data = await websocket.send_str(response)
        await llm.ingest(texts=[request, response], namespace=ref)
        logger.info(data)

@app.websocket("/api/hhmc/{category}")
async def you_vs_algoritmo(category: str, websocket: WebSocketResponse):
    while True:
        request = await websocket.receive_str()
        response = await llm.chat_with_memory(
            text=request, context=template(request=request,category=category), namespace=category
        )
        data = await websocket.send_str(response)
        await llm.ingest(texts=[request, response], namespace=category)
        logger.info(data)


@app.get("/api/youtube/{id}")
async def youtube_search(id: str):
    responses = await yt.search(id=id)
    items = []
    for response in responses:
        item = await yt.details(response)
        logger.info(item)
        items.append(item)
        if item.duration > 300:
            continue
        await yt.upsert(response)
    return items

app.router.add_static("/static", "static",show_index=True)



cors = aiohttp_cors.setup(app)

for route in list(app.router.routes()):
    cors.add(route)
