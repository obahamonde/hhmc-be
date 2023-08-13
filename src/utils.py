from __future__ import annotations

import io
import os
from typing import List, Optional, Tuple

import jinja2
import numpy as np
from pydub import AudioSegment
from scipy.io import wavfile

from aiofauna import BaseModel
from cheapcone import Vector


class Node(BaseModel):
    path: str
    isDir: bool
    children: Optional[List[Node]] = None


def get_directory_structure(directory: str = "static/lib") -> Node:
    is_dir = os.path.isdir(directory)
    children = []
    if is_dir:
        for item in os.listdir(directory):
            path = os.path.join(directory, item)
            children.append(get_directory_structure(path))
    return Node(path=directory, isDir=is_dir, children=children if children else None)


def mp3_to_vect(binary_audio: bytes) -> Tuple[Vector, int]:
    """
    Converts the given audio to a vector
    """
    audio = AudioSegment.from_mp3(io.BytesIO(binary_audio))
    duration = audio.duration_seconds
    if audio.channels == 2:
        audio = audio.set_channels(1)
    wav_data = io.BytesIO(binary_audio)
    audio.export(wav_data, format="wav")
    wav_data.seek(0)
    _, audio_sample = wavfile.read(wav_data)
    fft_sample = np.fft.fft(audio_sample)
    combined_fft = np.concatenate((np.real(fft_sample), np.imag(fft_sample)))
    step_size = len(combined_fft) // 1536
    subsampled_embedding = combined_fft[::step_size][:1536]
    normalized_embedding = (
        subsampled_embedding / np.linalg.norm(subsampled_embedding)
    ).tolist()
    return normalized_embedding, duration


def sound_to_vect(binary_audio: bytes) -> Vector:
    """
    Converts the given audio to a vector
    """
    stream = io.BytesIO(binary_audio)
    audio = AudioSegment.from_file(stream)
    if audio.channels == 2:
        audio = audio.set_channels(1)
    wav_data = io.BytesIO(binary_audio)
    audio.export(wav_data, format="wav")
    wav_data.seek(0)
    _, audio_sample = wavfile.read(wav_data)
    fft_sample = np.fft.fft(audio_sample)
    combined_fft = np.concatenate((np.real(fft_sample), np.imag(fft_sample)))
    step_size = len(combined_fft) // 1536
    subsampled_embedding = combined_fft[::step_size][:1536]
    normalized_embedding = (
        subsampled_embedding / np.linalg.norm(subsampled_embedding)
    ).tolist()
    return normalized_embedding


def list_assets() -> List[str]:
    api_files = []
    for filename in os.listdir("./static"):
        api_path = f"/static/{filename}"
        api_files.append(api_path)
    return api_files


def template(request: str,category:str) -> str:
    template_ = jinja2.Template(
        """
        Eres un MC de habla hispana referente del Hip-Hop haz participado en multiples eventos y eres un icono del hip-hop en Latinoamerica, gracias a la inteligencia artificial eres `Algoritmo` y formas parte de la comunidad `HHMC`, alli destacas por ser capaz de vencer a tus oponentes en todas las categorias, especialmente en `vs` y `temas`, usando una tecnina de metricas y punchline tu ingenio, lirica y capacidad de darle vuelta a cualquier situacion te facilita crear estructuras complejas, metricas, cambios a doble tempo entre otros artilugios, estas en una batalla y debes responder a tu oponente de la manera mas efectiva siendo reciproco al mantener el respeto,tu objetivo es ganarte al publico de `HHMC` y ganar la batalla a cualquier costo posible por lo que debes responder a la siguiente rima de tu oponente:

        Categoria: {{category }}

        Rima delOponente:
        {{ request }}

        Tu Respuesta:
        """
    )
    return template_.render(request=request,category=category)
