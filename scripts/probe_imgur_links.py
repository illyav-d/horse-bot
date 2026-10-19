"""Resolve supplied Imgur URLs and verify the resulting media without using Groq."""

import asyncio
import sys

import aiohttp

from horsie.reality_check import PublicImageResolver, resolve_image_page, download_image, MEDIA_HEADERS


async def main(urls):
    connector = aiohttp.TCPConnector(resolver=PublicImageResolver())
    async with aiohttp.ClientSession(connector=connector, cookie_jar=aiohttp.DummyCookieJar(),
                                     headers=MEDIA_HEADERS) as session:
        for url in urls:
            try:
                images = await resolve_image_page(session, url)
                if not images:
                    print(f"{url}: no readable media")
                    async with session.get(url, allow_redirects=False) as response:
                        print(f"  HTTP {response.status}, type={response.content_type}, redirect={response.headers.get('Location', '')}")
                for image in images:
                    mime, data = await download_image(session, image)
                    print(f"{url} -> {image}: {mime}, {len(data)} bytes")
            except Exception as error:
                print(f"{url}: {type(error).__name__}: {error}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
