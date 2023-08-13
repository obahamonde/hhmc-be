import io
import json
import re
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from os import environ

from aiofauna import *
from aiofauna.helpers import ThreadPoolExecutor
from aiofauna.llm import LLMStack
from aiohttp import ClientSession
from aiohttp.web_exceptions import HTTPException
from boto3 import Session
from cheapcone import Embedding, QueryBuilder
from pytube import YouTube
from typing_extensions import override

from .schemas import AudioTrack, Namespace, User, YouTubeVideo
from .utils import mp3_to_vect, sound_to_vect

logger = setup_logging(__name__)
llm = LLMStack()


class YoutubeClient(object):
    executor = ThreadPoolExecutor(max_workers=10)

    async def search(self, id: str):
        async with ClientSession() as session:
            async with session.get(f"https://www.youtube.com/watch?v={id}") as response:
                data = await response.text()
                related_videos = re.findall(r"watch\?v=(.{11})", data)
                return list(set(related_videos))

    @asyncify
    def download(self, id: str):
        """Fetches the audio from the given track url"""
        yt = YouTube(f"https://www.youtube.com/watch?v={id}")
        response = yt.streams.filter(only_audio=True).first()
        assert response is not None
        logger.info(f"Downloading {id}")
        buffer = io.BytesIO()
        response.stream_to_buffer(buffer)
        buffer.seek(0)
        return buffer.read()

    async def upsert(self, id: str):
        """Upserts the given track url to Pinecone"""
        raw_audio = await self.download(id)
        normalized_embedding = sound_to_vect(raw_audio)
        return await llm.pinecone.upsert(
            [
                Embedding(
                    values=normalized_embedding,
                    metadata={
                        "id": id,
                        "url": f"https://www.youtube.com/watch?v={id}",
                        "namespace": "audio_tracks",
                    },
                )
            ]
        )  # type: ignore

    async def query(self, id: str):
        """Returns the 10 KNN for t he given track url"""
        namespace = q("namespace") == "audio_tracks"
        normalized_embedding, _ = mp3_to_vect(await self.download(id))
        results = await llm.pinecone.query(
            expr=namespace.query, vector=normalized_embedding, topK=10
        )
        matches = results.matches
        return sorted(matches, key=lambda x: x.score, reverse=True)

    @asyncify
    def details(self, id: str):
        """Returns the details for the given track url"""
        ytvid = YouTube(f"https://www.youtube.com/watch?v={id}")
        data = {
            "id": id,
            "title": ytvid.title,
            "thumbnail": ytvid.thumbnail_url,
            "duration": ytvid.length,
            "views": ytvid.views,
            "channel": ytvid.author,
            "url": f"https://www.youtube.com/watch?v={id}",
        }
        return YouTubeVideo(**data)


@dataclass
class AuthClient(APIClient):
    async def user_info(self, token: str):
        try:
            user_dict = await self.update_headers(
                {"Authorization": f"Bearer {token}"}
            ).get("/userinfo")
            assert isinstance(user_dict, dict)
            return await User(**user_dict).save()

        except (AssertionError, HTTPException) as exc:
            return HTTPException(
                text=json.dumps({"status": "error", "message": str(exc)})
            )


auth = AuthClient(
    base_url=environ["AUTH0_URL"], headers={"Content-Type": "application/json"}
)
