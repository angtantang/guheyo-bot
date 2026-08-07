import asyncio
import os
import re
from threading import Thread
from bs4 import BeautifulSoup
import discord
from discord import app_commands
from discord.ext import tasks
from flask import Flask
import requests

# ==================== [ 환경 변수 설정 ] ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHECK_INTERVAL = 60  # 60초 주기
# ============================================================

# Render 24시간 구동용 웹서버
app = Flask("")


@app.route("/")
def home():
  return "Bot is running!"


def run_flask():
  app.run(host="0.0.0.0", port=8080)


def keep_alive():
  t = Thread(target=run_flask)
  t.start()


# 디스코드 클라이언트 및 슬래시 커맨드 트리 설정
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

user_keywords = {}
seen_post_ids = set()


# -------------------- [ 크롤링 함수 (안정형 API/헤더 우회 방식) ] --------------------
def fetch_latest_posts():
  url = "https://guheyo.com/sell"
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
          " like Gecko) Chrome/120.0.0.0 Safari/537.36"
      ),
      "Accept": (
          "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
      ),
      "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
      "Referer": "https://guheyo.com/",
  }

  try:
    response = requests.get(url, headers=headers, timeout=10)
    print(f"[디버그] 구해요 판매탭 접속 응답 코드: {response.status_code}")

    if response.status_code != 200:
      return []

    soup = BeautifulSoup(response.text, "html.parser")
    posts = []

    # 페이지 내의 모든 /offer/ 링크 추출
    links = soup.select("a[href*='/offer/']")

    for tag in links:
      rel_url = tag.get("href")
      if not rel_url:
        continue

      post_url = (
          rel_url
          if rel_url.startswith("http")
          else f"https://guheyo.com{rel_url}"
      )
      post_id = rel_url.split("/")[-1].split("?")[0]

      if not post_id or any(p["id"] == post_id for p in posts):
        continue

      title = tag.get_text(strip=True)
      if not title or len(title) < 2:
        parent = tag.find_parent(["div", "article", "li"])
        if parent:
          title_elem = parent.select_one(".title, h2, h3, span, p")
          title = (
              title_elem.get_text(strip=True) if title_elem else "판매글 제목 없음"
          )
        else:
          title = "판매글 제목 없음"

      posts.append({
          "id": post_id,
          "title": title,
          "price": "가격 확인",
          "url": post_url,
          "image_url": "",
          "full_text": title.lower(),
      })

    print(f"[디버그] 최종 수집된 유효 게시글 수: {len(posts)}")
    return posts
  except Exception as e:
    print(f"[크롤링 에러] {e}")
    return []


# -------------------- [ 슬래시 명령어 정의 ] --------------------
@tree.command(
    name="판매알림등록",
    description="판매글 제목/본문에 키워드가 있으면 DM을 보냅니다.",
)
@app_commands.describe(
    키워드="등록할 검색 키워드 (최대 5개, 대소문자 구분 없음)"
)
async def add_keyword(interaction: discord.Interaction, 키워드: str):
  user_id = interaction.user.id
  if user_id not in user_keywords:
    user_keywords[user_id] = []

  if len(user_keywords[user_id]) >= 5:
    await interaction.response.send_message(
        "키워드는 최대 5개까지만 등록할 수 있습니다.", ephemeral=True
    )
    return

  clean_kw = 키워드.strip().lower()

  if clean_kw in user_keywords[user_id]:
    await interaction.response.send_message(
        f"`{clean_kw}`(은)는 이미 등록된 키워드입니다.", ephemeral=True
    )
    return

  user_keywords[user_id].append(clean_kw)
  await interaction.response.send_message(
      f"✅ 키워드 **`{clean_kw}`**(이)가 등록되었습니다! (현재"
      f" {len(user_keywords[user_id])}/5개)",
      ephemeral=True,
  )


@tree.command(name="판매알림삭제", description="등록한 판매 알림 키워드를 삭제합니다.")
@app_commands.describe(키워드="삭제할 키워드")
async def delete_keyword(interaction: discord.Interaction, 키워드: str):
  user_id = interaction.user.id
  clean_kw = 키워드.strip().lower()

  if user_id in user_keywords and clean_kw in user_keywords[user_id]:
    user_keywords[user_id].remove(clean_kw)
    await interaction.response.send_message(
        f"🗑️ 키워드 **`{clean_kw}`**(이)가 삭제되었습니다.", ephemeral=True
    )
  else:
    await interaction.response.send_message(
        f"등록되지 않은 키워드입니다: `{clean_kw}`", ephemeral=True
    )


@tree.command(
    name="알림목록", description="내가 등록한 알림 키워드 목록을 확인합니다."
)
async def list_keywords(interaction: discord.Interaction):
  user_id = interaction.user.id
  kws = user_keywords.get(user_id, [])

  if not kws:
    await interaction.response.send_message(
        "등록된 키워드가 없습니다.", ephemeral=True
    )
  else:
    kw_str = "\n".join([f"- `{kw}`" for kw in kws])
    await interaction.response.send_message(
        f"📋 **현재 등록된 키워드 목록 ({len(kws)}/5개)**\n{kw_str}",
        ephemeral=True,
    )


@tree.command(name="도움말", description="동왕 알리미 봇 사용법을 안내합니다.")
async def help_command(interaction: discord.Interaction):
  embed = discord.Embed(
      title="AKNotifier — 구해요 키워드 DM 알림",
      description=(
          "`/판매알림등록 [키워드]` — 판매글에 키워드가 있을 때 DM 알림\n`/판매알림삭제"
          " [키워드]` — 등록된 알림 삭제\n`/알림목록` — 내가 등록한 알림 목록 확인"
      ),
      color=0x2b2d31,
  )
  await interaction.response.send_message(embed=embed, ephemeral=True)


# -------------------- [ 모니터링 태스크 루프 ] --------------------
async def send_discord_dm(user, post, matched_keyword):
  embed = discord.Embed(title="판매글 알림", color=0x2b2d31)
  embed.add_field(
      name="", value=f"**[{post['title']}]({post['url']})**", inline=False
  )
  embed.add_field(name="가격", value=post["price"], inline=True)
  embed.add_field(name="키워드", value=matched_keyword, inline=True)

  now_str = discord.utils.utcnow().strftime("%Y년 %m월 %d일 %p %I:%M")
  embed.add_field(name="등록", value=f"`{now_str}`", inline=False)

  header_text = f"판매 • [{matched_keyword}]\n{post['title']}"

  try:
    await user.send(content=f"**동왕 알리미 봇**\n{header_text}", embed=embed)
  except Exception as e:
    print(f"[DM 발송 실패] {e}")


@tasks.loop(seconds=CHECK_INTERVAL)
async def monitor_loop():
  print("[디버그] 판매탭 새 글을 확인합니다...")
  posts = fetch_latest_posts()

  if not posts:
    print("[디버그] 수집된 글이 없습니다.")
    return

  for post in reversed(posts):
    if post["id"] in seen_post_ids:
      continue

    seen_post_ids.add(post["id"])
    post_full_text = post.get("full_text", "")

    for user_id, keywords in list(user_keywords.items()):
      for kw in keywords:
        if kw in post_full_text:
          try:
            user = await client.fetch_user(user_id)
            await send_discord_dm(user, post, kw)
          except Exception as e:
            print(f"[유저 전달 오류] {e}")
          break


@monitor_loop.before_loop
async def before_monitor_loop():
  await client.wait_until_ready()
  print("[디버그] 초기 게시글 캐싱 중...")
  initial_posts = fetch_latest_posts()
  for p in initial_posts:
    seen_post_ids.add(p["id"])
  print(f"[디버그] 초기 캐싱 완료 (총 {len(seen_post_ids)}개 인식)")


@client.event
async def on_ready():
  await tree.sync()
  print(f"로그인 성공: {client.user.name}")
  if not monitor_loop.is_running():
    monitor_loop.start()


if __name__ == "__main__":
  keep_alive()
  client.run(BOT_TOKEN)
