import asyncio
import re

from aiofauna import FileField, Request
from aiofauna.llm import LLMStack
from aiohttp import ClientSession
from boto3 import Session
from cheapcone import Embedding, List, QueryBuilder

from .schemas import AudioTrack
from .utils import list_assets, mp3_to_vect

Vector = List[float]

llm = LLMStack()
aws = Session()
s3 = aws.client("s3")
q = QueryBuilder()


async def audiotrack_handler(request: Request):
    """Takes an MP3 file, transcodes it to WAV, changes to mono, extracts the FFT and generates an embedding of 1536 dimensions that is upserted to Pinecone for further similarity search, meanwhile save the audio track to the main database, and return the `AudioTrack` object."""
    user = request.query.get("user")
    playlist = request.query.get("playlist")
    audio_mp3 = (await request.post())["file"]
    assert isinstance(audio_mp3, FileField)
    binary_mp3 = audio_mp3.file.read()
    s3.put_object(Bucket="audio-aiofauna", Key=f"{user}/{playlist}/{audio_mp3.filename}", Body=binary_mp3)  # type: ignore
    normalized_embedding, duration = mp3_to_vect(binary_mp3)
    audio_track = await AudioTrack(
        playlist=playlist,  # type: ignore
        url=f"https://audio-aiofauna.s3.amazonaws.com/{user}/{playlist}/  {audio_mp3.filename}",  # type: ignore
        user=user,  # type: ignore
        duration=duration,  # type: ignore
        title=audio_mp3.filename,  # type: ignore
    ).save()
    assert isinstance(audio_track, AudioTrack)
    metadata = audio_track.dict()
    await llm.pinecone.upsert(
        [Embedding(values=normalized_embedding, metadata=metadata)]  # type: ignore
    )
    return audio_track


async def audiotrack_feed_handler(url: str):
    """Returns the 10 KNN for the given track url"""
    namespace = q("namespace") == "audio_tracks"
    async with ClientSession() as session:
        async with session.get(url) as response:
            data = await response.read()
            normalized_embedding, _ = mp3_to_vect(data)
            results = await llm.pinecone.query(
                expr=namespace.query, vector=normalized_embedding, topK=10
            )
            matches = results.matches
            return sorted(matches, key=lambda x: x.score, reverse=True)


async def youtube_search(id: str):
    async with ClientSession() as session:
        async with session.get(f"https://www.youtube.com/watch?v={id}") as response:
            data = await response.text()
            related_videos = re.findall(r"watch\?v=(.{11})", data)
            return related_videos


async def ingest_music_vector(vectors: List[Vector], url: str):
    return await llm.pinecone.upsert(
        [
            Embedding(values=v, metadata={"url": url, "namespace": "hhmc"})
            for v in vectors
        ]
    )


async def get_assets():
    return list_assets()
