import asyncio
from typing import List

from aiofauna.llm.llm import APIException, LLMStack
from aiofauna.utils import handle_errors, setup_logging
from aiohttp import ClientSession, TCPConnector
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
}
BAD_EXT = (
    "png",
    "jpg",
    "jpeg",
    "gif",
    "pdf",
    "doc",
    "docx",
    "ppt",
    "pptx",
    "xls",
    "xlsx",
    "zip",
    "rar",
    "gz",
    "7z",
    "exe",
    "mp3",
    "mp4",
    "avi",
    "mkv",
    "mov",
    "wmv",
    "flv",
    "swf",
)

connector = TCPConnector(limit=1500)

logger = setup_logging(__name__)


@handle_errors
async def sitemap(url: str, session: ClientSession) -> List[str]:
    urls = []
    if not url.endswith("xml"):
        url = f"{url.rstrip('/')}/sitemap.xml"
    async with session.get(url) as response:
        text = await response.text()
        soup = BeautifulSoup(text, features="xml")
        for loc in soup.findAll("loc"):
            if loc.text.endswith(BAD_EXT):
                continue
            urls.append(loc.text)
            logger.info("Found %s", loc.text)
        for nested_sitemap in soup.findAll("sitemap"):
            urls.extend(await sitemap(nested_sitemap.loc.text, session))
    return urls


@handle_errors
async def fetch_website(url: str, session: ClientSession, max_size: int = 40960) -> str:
    async with session.get(url) as response:
        html = await response.text()
        truncated_html = html[:max_size]
        return BeautifulSoup(truncated_html, features="lxml").get_text(
            separator="\n", strip=True
        )


async def sitemap_pipeline(
    url: str,
    namespace: str,
    session: ClientSession,
    llm: LLMStack = LLMStack(),
    chunk_size: int = 100,
):
    urls = await sitemap(url, session)
    length = len(urls)
    inserted = 0
    while urls:
        chunk = urls[:chunk_size]
        urls = urls[chunk_size:]
        try:
            contents = await asyncio.gather(
                *[fetch_website(url, session) for url in chunk]
            )
            inserted += await llm.ingest(contents, namespace, 100)
            progress = inserted / length
            logger.info("Progress: %s", progress)
            if progress >= 1:
                yield "100"
                break
            yield str(progress * 100)
        except (APIException, Exception) as e:
            logger.error(e)
            continue
