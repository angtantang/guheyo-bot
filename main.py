import os
import asyncio
import re
import requests
from bs4 import BeautifulSoup
import discord
from flask import Flask
from threading import Thread

# ==================== [ 환경 변수 설정 ] ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
TARGET_USER_ID = int(os.environ.get("TARGET_USER_ID", "0"))
KEYWORDS = ["hhkb", "상우", "매그넘", "agar"]  # 감시할 키워드 목록
CHECK_INTERVAL = 60                           # 크롤링 주기 (초 단위)
# ============================================================

# Render 웹 서비스 유지용 가짜 서버 (24시간 켜둠 보장용)
app = Flask('')
@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

intents = discord.Intents.default()
client = discord.Client(intents=intents)
seen_post_ids = set()

def fetch_latest_posts():
    url = "https://guheyo.com"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        posts = []

        # 구해요 게시글 리스트 선택
        articles = soup.select(".post-item, article, tr.board-list, .list-item")

        for article in articles:
            link_tag = article.select_one("a[href*='/post/']") or article.select_one("a")
            if not link_tag or not link_tag.get("href"):
                continue

            rel_url = link_tag["href"]
            post_url = rel_url if rel_url.startswith("http") else f"https://guheyo.com{rel_url}"

            post_id_match = re.search(r'/(\d+)', rel_url)
            post_id = post_id_match.group(1) if post_id_match else rel_url

            title_tag = article.select_one(".title") or link_tag
            title = title_tag.get_text(strip=True) if title_tag else "제목 없음"

            price_tag = article.select_one(".price")
            price = price_tag.get_text(strip=True) if price_tag else "가격 미기재"

            img_tag = article.select_one("img")
            img_url = ""
            if img_tag and img_tag.get("src"):
                src = img_tag["src"]
                img_url = src if src.startswith("http") else f"https://guheyo.com{src}"

            posts.append({
                "id": post_id,
                "title": title,
                "price": price,
                "url": post_url,
                "image_url": img_url
            })

        return posts
    except Exception as e:
        print(f"[크롤링 에러] {e}")
        return []

async def send_discord_dm(user, post, matched_keyword):
    embed = discord.Embed(
        title="판매글 알림",
        color=0x2b2d31
    )
    embed.add_field(
        name="",
        value=f"**[{post['title']}]({post['url']})**",
        inline=False
    )
    embed.add_field(name="가격", value=post["price"], inline=True)
    embed.add_field(name="키워드", value=matched_keyword, inline=True)

    now_str = discord.utils.utcnow().strftime("%Y년 %m월 %d일 %p %I:%M")
    embed.add_field(name="등록", value=f"`{now_str}`", inline=False)

    if post["image_url"]:
        embed.set_thumbnail(url=post["image_url"])

    header_text = f"판매 • [{matched_keyword}]\n{post['title']}"

    try:
        await user.send(content=f"**동왕 알리미 봇**\n{header_text}", embed=embed)
        print(f"[DM 발송 완료] {post['title']}")
    except Exception as e:
        print(f"[DM 발송 실패] {e}")

async def monitor_loop():
    await client.wait_until_ready()
    user = await client.fetch_user(TARGET_USER_ID)

    initial_posts = fetch_latest_posts()
    for p in initial_posts:
        seen_post_ids.add(p["id"])

    while not client.is_closed():
        await asyncio.sleep(CHECK_INTERVAL)
        posts = fetch_latest_posts()

        for post in reversed(posts):
            if post["id"] in seen_post_ids:
                continue

            seen_post_ids.add(post["id"])

            for kw in KEYWORDS:
                if kw.lower() in post["title"].lower():
                    await send_discord_dm(user, post, kw)
                    break

@client.event
async def on_ready():
    print(f"로그인 성공: {client.user.name}")
    client.loop.create_task(monitor_loop())

if __name__ == "__main__":
    keep_alive()
    client.run(BOT_TOKEN)
