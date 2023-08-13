from typing import Optional

from aiofauna import FaunaModel, Field
from pydantic import HttpUrl  # pylint: disable=no-name-in-module
from pydantic import BaseModel


class User(FaunaModel):
    """
    Auth0 User, Github User or Cognito User
    """

    email: Optional[str] = Field(default=None, index=True)
    email_verified: Optional[bool] = Field(default=False)
    family_name: Optional[str] = Field(default=None)
    given_name: Optional[str] = Field(default=None)
    locale: Optional[str] = Field(default=None, index=True)
    name: str = Field(...)
    nickname: Optional[str] = Field(default=None)
    picture: Optional[str] = Field(default=None)
    sub: str = Field(..., unique=True)
    updated_at: Optional[str] = Field(default=None)


class AudioTrack(FaunaModel):
    """
    AudioTrack model
    """

    playlist: str = Field(..., index=True)  # Metadata
    url: HttpUrl = Field(..., unique=True)  # Metadata
    user: str = Field(..., index=True)  # Metadata
    duration: int = Field(..., index=True)  # Metadata
    cover: Optional[HttpUrl] = Field(default=None)
    title: str = Field(...)
    lyrics: Optional[str] = Field(default=None)
    namespace: str = Field(default="audio_tracks")


class Namespace(FaunaModel):
    """
    Playlist model
    """

    name: str = Field(...)
    user: str = Field(..., index=True)  # Metadata
    cover: Optional[HttpUrl] = Field(default=None)
    description: Optional[str] = Field(default=None)


class YouTubeVideo(BaseModel):
    """
    YouTube Video model
    """

    id: str = Field(..., description="The unique identifier for the video.")
    title: str = Field(..., description="The title of the video.")
    thumbnail: str = Field(..., description="The URL of the video's thumbnail.")
    duration: int = Field(..., description="The length of the video in seconds.")
    views: int = Field(..., description="The number of views for the video.")
    channel: str = Field(
        ..., description="The author or channel that published the video."
    )
    url: str = Field(..., description="The URL of the video.")
