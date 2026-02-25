#!/usr/bin/env python3
"""
IAINSU RSS Feed Scraper (Playwright + Residential Proxy)
=========================================================
Menggunakan Playwright + Geonode residential proxy untuk bypass Cloudflare.
"""

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import time
import re
import os
import html
import hashlib

BASE_URL = "https://iainsurakarta.ac.id"
HOMEPAGE_URL = "https://iainsurakarta.ac.id/"
MAX_ARTICLES = 10
FEED_TITLE = "IAINSU - Manfaat dan Kesehatan"
FEED_DESCRIPTION = "RSS Feed artikel dari iainsurakarta.ac.id dengan konten lengkap"
FEED_LINK = "https://iainsurakarta.ac.id/"
OUTPUT_FILE = "docs/feed.xml"
REQUEST_DELAY = 2
WIB = timezone(timedelta(hours=7))
BULAN_ID = {
    'januari': 1, 'februari': 2, 'maret': 3, 'april': 4,
    'mei': 5, 'juni': 6, 'juli': 7, 'agustus': 8,
    'september': 9, 'oktober': 10, 'november': 11, 'desember': 12
}

# Proxy dari environment variables (GitHub Secrets)
PROXY_HOST = os.environ.get('PROXY_HOST', '')
PROXY_PORT = os.environ.get('PROXY_PORT', '')
PROXY_USER = os.environ.get('PROXY_USER', '')
PROXY_PASS = os.environ.get('PROXY_PASS', '')

browser = None
context = None
page = None

def init_browser():
    global browser, context, page
    pw = sync_playwright().start()

    launch_args = {
        'headless': True,
        'args': ['--no-sandbox','--disable-setuid-sandbox','--disable-blink-features=AutomationControlled','--disable-dev-shm-usage']
    }

    # Konfigurasi proxy jika tersedia
    if PROXY_HOST and PROXY_PORT and PROXY_USER and PROXY_PASS:
        launch_args['proxy'] = {
            'server': f'http://{PROXY_HOST}:{PROXY_PORT}',
            'username': PROXY_USER,
            'password': PROXY_PASS,
        }
        print(f"[*] Proxy: {PROXY_HOST}:{PROXY_PORT} (residential)")
    else:
        print("[!] Proxy TIDAK dikonfigurasi - mungkin akan diblokir Cloudflare")

    browser = pw.chromium.launch(**launch_args)

    context = browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        locale='id-ID', timezone_id='Asia/Jakarta',
        extra_http_headers={'Accept-Language': 'id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7'}
    )
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'languages', { get: () => ['id-ID', 'id', 'en-US', 'en'] });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        window.chrome = { runtime: {} };
    """)
    page = context.new_page()
    print("[*] Browser Playwright berhasil diinisialisasi")
    return pw

def fetch_page(url, retries=3):
    for attempt in range(retries):
        try:
            print(f"  [>] Fetching: {url}")
            response = page.goto(url, wait_until='domcontentloaded', timeout=30000)
            if response is None:
                print(f"  [!] Response None (percobaan {attempt+1}/{retries})")
                time.sleep(REQUEST_DELAY * 2); continue
            status = response.status
            print(f"  [>] Status: {status}")
            if status == 200:
                time.sleep(2)
                content = page.content()
                print(f"  [+] Berhasil ({len(content)} chars)")
                return content
            if status == 403 or status == 503:
                print(f"  [~] Cloudflare challenge, menunggu...")
                time.sleep(8)
                content = page.content()
                if 'article' in content and ('h3' in content or 'article_content' in content):
                    print(f"  [+] Challenge solved! ({len(content)} chars)")
                    return content
                print(f"  [!] Masih challenge (percobaan {attempt+1}/{retries})")
                time.sleep(REQUEST_DELAY * 2); continue
            print(f"  [!] Status {status} (percobaan {attempt+1}/{retries})")
            time.sleep(REQUEST_DELAY * 2)
        except Exception as e:
            print(f"  [!] Error: {e} (percobaan {attempt+1}/{retries})")
            if attempt < retries - 1: time.sleep(REQUEST_DELAY * 2)
    return None

def close_browser():
    global browser, context
    try:
        if context: context.close()
        if browser: browser.close()
    except: pass

def parse_homepage():
    print(f"\n[*] Scraping homepage: {HOMEPAGE_URL}")
    html_content = fetch_page(HOMEPAGE_URL)
    if not html_content: return []
    soup = BeautifulSoup(html_content, 'lxml')
    articles = []; seen = set()
    for a_tag in soup.select('article h3 a'):
        href = a_tag.get('href', '').strip()
        title = a_tag.get_text(strip=True)
        if not href or not title or href in seen: continue
        seen.add(href)
        if not href.startswith('http'): href = BASE_URL + href
        article_elem = a_tag.find_parent('article')
        thumb = ''
        if article_elem:
            img = article_elem.select_one('img')
            if img: thumb = img.get('src', '')
        articles.append({'title': title, 'link': href, 'thumb': thumb})
    print(f"  [+] Ditemukan {len(articles)} artikel")
    return articles[:MAX_ARTICLES]

def parse_article_page(url):
    print(f"  [>] Mengambil artikel: {url}")
    html_content = fetch_page(url)
    if not html_content: return None
    soup = BeautifulSoup(html_content, 'lxml')
    article = soup.select_one('article#article_content') or soup.select_one('article')
    if not article: return None
    data = {}
    h1 = article.select_one('h1')
    data['title'] = h1.get_text(strip=True) if h1 else ''
    meta_elem = article.select_one('p small em')
    reporter = ''; pub_date_str = ''
    if meta_elem:
        mt = meta_elem.get_text(strip=True)
        if ' oleh ' in mt:
            parts = mt.split(' oleh ', 1)
            pub_date_str = parts[0].strip(); reporter = parts[1].strip()
        else: pub_date_str = mt
    data['reporter'] = reporter
    data['pub_date'] = parse_date(pub_date_str)
    og = soup.find('meta', property='og:image')
    data['image'] = og.get('content', '') if og else ''
    if not data['image']:
        mi = article.select_one('img.v-cover')
        if mi: data['image'] = mi.get('src', '')
    data['content'] = '\n\n'.join(extract_content(article))
    data['tags'] = []; data['category'] = 'Artikel'
    return data

def extract_content(article):
    parts = []; skip_meta = True
    for elem in article.children:
        if not hasattr(elem, 'name') or not elem.name: continue
        if elem.name == 'h1': continue
        if elem.name == 'p':
            if skip_meta and elem.select_one('small em'):
                skip_meta = False; continue
            skip_meta = False
            text = elem.get_text(strip=True)
            if text and len(text) > 5: parts.append(text)
        elif elem.name == 'center': continue
        elif elem.name in ['h2','h3']:
            text = elem.get_text(strip=True)
            if text: parts.append(f"\n### {text}\n")
        elif elem.name in ['h4','h5','h6']:
            text = elem.get_text(strip=True)
            if text: parts.append(f"\n#### {text}\n")
        elif elem.name == 'ol':
            for i, li in enumerate(elem.find_all('li', recursive=False), 1):
                strong = li.find('strong')
                if strong: parts.append(f"\n**{i}. {strong.get_text(strip=True)}**\n")
                for p in li.find_all('p'):
                    text = p.get_text(strip=True)
                    if text and len(text) > 5: parts.append(text)
        elif elem.name == 'ul':
            for li in elem.find_all('li', recursive=False):
                text = li.get_text(strip=True)
                if text: parts.append(f"• {text}")
        elif elem.name == 'section': continue
    return parts

def parse_date(date_str):
    if not date_str: return datetime.now(WIB).strftime('%a, %d %b %Y %H:%M:%S +0700')
    days = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']
    months_en = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    m = re.search(r'(\d{1,2})\s+(\w+)\s+(\d{4})', date_str)
    if m:
        day, ms, year = m.groups()
        mn = BULAN_ID.get(ms.lower(), 0)
        if mn:
            try:
                dt = datetime(int(year), mn, int(day), 12, 0, 0)
                return f"{days[dt.weekday()]}, {int(day):02d} {months_en[mn-1]} {int(year)} 12:00:00 +0700"
            except: pass
    return datetime.now(WIB).strftime('%a, %d %b %Y %H:%M:%S +0700')

def generate_rss(articles_data):
    print(f"\n[*] Generating RSS XML...")
    now = datetime.now(WIB).strftime('%a, %d %b %Y %H:%M:%S +0700')
    rss_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>{html.escape(FEED_TITLE)}</title>
    <description>{html.escape(FEED_DESCRIPTION)}</description>
    <link>{html.escape(FEED_LINK)}</link>
    <language>id</language>
    <lastBuildDate>{now}</lastBuildDate>
    <generator>IAINSU RSS Scraper - Playwright + Proxy (GitHub Actions)</generator>
'''
    for a in articles_data:
        if not a: continue
        ch = ''
        if a.get('image'): ch += f'<p><img src="{html.escape(a["image"])}" alt="{html.escape(a.get("title",""))}" style="max-width:100%;" /></p>\n'
        if a.get('reporter'): ch += f'<p><strong>Penulis:</strong> {html.escape(a["reporter"])}</p>\n'
        if a.get('content'):
            for para in a['content'].split('\n\n'):
                para = para.strip()
                if not para: continue
                if para.startswith('\n### '): ch += f'<h3>{html.escape(para.strip().lstrip("#").strip())}</h3>\n'
                elif para.startswith('\n#### '): ch += f'<h4>{html.escape(para.strip().lstrip("#").strip())}</h4>\n'
                elif para.startswith('**') and para.endswith('**'): ch += f'<p><strong>{html.escape(para.strip("*").strip())}</strong></p>\n'
                elif para.startswith('• '): ch += f'<p>{html.escape(para)}</p>\n'
                else: ch += f'<p>{html.escape(para)}</p>\n'
        guid = a.get('link', hashlib.md5(a.get('title','').encode()).hexdigest())
        rss_xml += f'    <item>\n      <title><![CDATA[{a.get("title","Tanpa Judul")}]]></title>\n      <link>{html.escape(a.get("link",""))}</link>\n      <guid isPermaLink="true">{html.escape(guid)}</guid>\n      <pubDate>{a.get("pub_date",now)}</pubDate>\n'
        if a.get('category'): rss_xml += f'      <category><![CDATA[{a["category"]}]]></category>\n'
        if a.get('image'): rss_xml += f'      <media:content url="{html.escape(a["image"])}" medium="image" />\n'
        rss_xml += f'      <description><![CDATA[{ch}]]></description>\n      <content:encoded><![CDATA[{ch}]]></content:encoded>\n    </item>\n'
    rss_xml += '  </channel>\n</rss>'
    return rss_xml

def main():
    print("=" * 60)
    print("  IAINSU RSS Scraper (Playwright + Residential Proxy)")
    print("=" * 60)
    print(f"  Feed Title : {FEED_TITLE}")
    print(f"  Output     : {OUTPUT_FILE}")
    print(f"  Max Artikel: {MAX_ARTICLES}")
    print(f"  Source URL : {HOMEPAGE_URL}")
    print(f"  Proxy      : {'Ya' if PROXY_HOST else 'Tidak'}")
    print("=" * 60)
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    pw = init_browser()
    try:
        articles = parse_homepage()
        if not articles:
            print("\n[!] Tidak ada artikel ditemukan."); return
        print(f"\n[*] Total {len(articles)} artikel akan diproses")
        articles_data = []
        for i, article in enumerate(articles):
            print(f"\n--- Artikel {i+1}/{len(articles)} ---")
            ad = parse_article_page(article['link'])
            if ad:
                if not ad.get('title'): ad['title'] = article['title']
                ad['link'] = article['link']
                if not ad.get('image') and article.get('thumb'): ad['image'] = article['thumb']
                articles_data.append(ad)
            else:
                articles_data.append({'title': article['title'], 'link': article['link'], 'content': '(Konten tidak dapat diambil)', 'pub_date': datetime.now(WIB).strftime('%a, %d %b %Y %H:%M:%S +0700'), 'image': article.get('thumb',''), 'reporter': '', 'tags': [], 'category': 'Artikel'})
            time.sleep(REQUEST_DELAY)
        rss_xml = generate_rss(articles_data)
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f: f.write(rss_xml)
        print(f"\n{'=' * 60}")
        print(f"  SELESAI! File: {OUTPUT_FILE}")
        print(f"  Total artikel: {len(articles_data)}")
        print(f"{'=' * 60}")
    finally:
        close_browser()
        try: pw.stop()
        except: pass

if __name__ == '__main__':
    main()
