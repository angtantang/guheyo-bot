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
CHECK_INTERVAL = 60  # 크롤링 주기 (초 단위)
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

# 유저별 키워드 저장소 { user_id: ["hhkb", "상우"] } (소문자로 저장)
user_keywords = {}
seen_post_ids = set()


# -------------------- [ 크롤링 함수 ] --------------------
def fetch_latest_posts():
  # 장터 판매 탭의 실제 주소로 변경
  url = "https://guheyo.com/sell"
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
          " like Gecko) Chrome/120.0.0.0 Safari/537.36"
      ),
      "RSC": "1",  # Next.js 서버 컴포넌트 데이터 요청 헤더
  }

  try:
    response = requests.get(url, headers=headers, timeout=10)
    print(f"[디버그] 구해요 판매탭 접속 응답 코드: {response.status_code}")

    if response.status_code != 200:
      return []

    soup = BeautifulSoup(response.text, "html.parser")
posts = []

    # 판매 탭 페이지 내의 게시글 카드 선택자 탐색
    articles = soup.select(".post-item, article, tr.board-list, .list-item, div[class*='item']")
    print(f"[디버그] 찾아낸 게시글 수: {len(articles)}")

    for article in articles:
      link_tag = article.select_one("a[href*='/post/']") or article.select_one("a")
      if not link_tag or not link_tag.get("href"):
        continue

      rel_url = link_tag["href"]
      post_url = (
          rel_url
          if rel_url.startswith("http")
          else f"https://guheyo.com{rel_url}"
      )

      post_id_match = re.search(r"/(\d+)", rel_url)
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

      content_text = ""
      try:
        detail_resp = requests.get(post_url, headers=headers, timeout=5)
        if detail_resp.status_code == 200:
          detail_soup = BeautifulSoup(detail_resp.text, "html.parser")
          body_elem = detail_soup.select_one(
              ".post-content, .content, article, .board-view"
          )
          if body_elem:
            content_text = body_elem.get_text(strip=True)
      except Exception:
        pass

      full_text = f"{title} {content_text}"

      posts.append({
          "id": post_id,
          "title": title,
          "price": price,
          "url": post_url,
          "image_url": img_url,
          "full_text": full_text,
      })

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
        f"`{clean_kw}`(은)는 이미 등록된 키워드입니다 (대소문자 구분 안 함).",
        ephemeral=True,
    )
    return

  user_keywords[user_id].append(clean_kw)
  await interaction.response.send_message(
      f"✅ 키워드 **`{clean_kw}`**(이)가 등록되었습니다! (대소문자 구분 안 함, 현재"
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
          "`/판매알림등록 [키워드]` — 판매글 제목·본문에 키워드가 있을 때 DM 알림 (최대"
          " 5개, 대소문자 미구분)\n`/판매알림삭제 [키워드]` — 등록된 알림 삭제\n`/알림목록`"
          " — 내가 등록한 알림 목록 확인"
      ),
      color=0x2b2d31,
  )
  embed.set_footer(text="알림은 봇 DM으로 전송됩니다.")
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

  if post["image_url"]:
    embed.set_thumbnail(url=post["image_url"])

  header_text = f"판매 • [{matched_keyword}]\n{post['title']}"

  try:
    await user.send(content=f"**동왕 알리미 봇**\n{header_text}", embed=embed)
  except Exception as e:
    print(f"[DM 발송 실패] {e}")


@tasks.loop(seconds=CHECK_INTERVAL)
async def monitor_loop():
  print("[디버그] 60초 주기로 판매탭 새 글을 확인합니다...")
  posts = fetch_latest_posts()

  if not posts:
    print("[디버그] 수집된 글이 없습니다.")
    return

  for post in reversed(posts):
    if post["id"] in seen_post_ids:
      continue

    seen_post_ids.add(post["id"])
    post_full_text = post.get("full_text", post["title"]).lower()

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
  print("[디버그] 모니터링 루프 대기 중...")
  await client.wait_until_ready()
  print("[디버그] 봇 준비 완료, 최초 판매탭 게시글 캐싱 중...")
  initial_posts = fetch_latest_posts()
  for p in initial_posts:
    seen_post_ids.add(p["id"])
  print(f"[디버그] 초기 캐싱 완료 (총 {len(seen_post_ids)}개 게시글 인식)")


@client.event
async def on_ready():
  await tree.sync()
  print(f"로그인 성공 및 슬래시 명령어 동기화 완료: {client.user.name}")
  if not monitor_loop.is_running():
    monitor_loop.start()


if __name__ == "__main__":
  keep_alive()
  client.run(BOT_TOKEN)
