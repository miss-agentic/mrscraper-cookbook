import asyncio, json, os
from dotenv import load_dotenv
load_dotenv()
from mrscraper import MrScraper
import monitor  # same dir, flat module

URL = "https://www.walmart.com/ip/Hisense-65-Class-4K-UHD-LED-Roku-Smart-TV-HDR-65R6E1/988564886"

async def go():
    client = MrScraper(token=os.environ["MRSCRAPER_API_TOKEN"])
    result = await client.create_scraper(
        url=URL, message=monitor.PROMPT, agent="general", proxy_country="US"
    )
    print("envelope shape:", monitor._shape(result))
    leaf = result["data"]["data"]["data"]
    if isinstance(leaf, str):
        leaf = json.loads(leaf)
    print(json.dumps(leaf, indent=2, ensure_ascii=False))
    print("price value:", repr(leaf.get("price")))
    print("price type :", type(leaf.get("price")).__name__)

asyncio.run(go())