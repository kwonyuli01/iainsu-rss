#!/usr/bin/env python3
"""
IAINSU RSS Feed Scraper
========================
Scrape homepage + konten artikel lengkap dari iainsurakarta.ac.id.

Situs ini server-side rendered tanpa Cloudflare blocking,
jadi cukup pakai requests biasa (tanpa Playwright).

Dijalankan otomatis via GitHub Actions + publish ke GitHub Pages.
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import time
import re
import os
import html
import hashlib

# ============================================================
# KONFIGURASI
# ============================================================

BASE_URL = "https://iainsurakarta.ac.id"
HOMEPAGE_URL = "https://iainsurakarta.ac.id/"

MAX_ARTICLES = 10  # Homepage hanya tampilkan 10 artikel

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

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7',
}

session = requests.Session()
session.headers.update(HEADERS)


# ============================================================
# FETCH
# ============================================================

def fetch_page(url, retries=3):
    """Fetch halaman menggunakan requests."""
    for attempt in range(retries):
        try:
            print(f"  [>] Fetching: {url}")
            resp = session.get(url, timeout=30)
            print(f"  [>] Status: {resp.status_code}")

            if resp.status_code == 200:
                print(f"  [+] Berhasil ({len(resp.text)} chars)")
                return resp.text

            print(f"  [!] Status {resp.status_code} (percobaan {attempt+1}/{retries})")
            time.sleep(REQUEST_DELAY * 2)

        except Exception as e:
            print(f"  [!] Error: {e} (percobaan {attempt+1}/{retries})")
            if attempt < retries - 1:
                time.sleep(REQUEST_DELAY * 2)

    return None


# ============================================================
# PARSING
# ============================================================

def parse_homepage():
    """Parse homepage untuk mendapatkan daftar artikel."""
    print(f"\n[*] Scraping homepage: {HOMEPAGE_URL}")
    html_content = fetch_page(HOMEPAGE_URL)
    if not html_content:
        return []

    soup = BeautifulSoup(html_content, 'lxml')
    articles = []
    seen = set()

    for a_tag in soup.select('article h3 a'):
        href = a_tag.get('href', '').strip()
        title = a_tag.get_text(strip=True)

        if not href or not title or href in seen:
            continue
        seen.add(href)

        if not href.startswith('http'):
            href = BASE_URL + href

        # Thumbnail
        article_elem = a_tag.find_parent('article')
        thumb = ''
        if article_elem:
            img = article_elem.select_one('img')
            if img:
                thumb = img.get('src', '')

        articles.append({
            'title': title,
            'link': href,
            'thumb': thumb,
        })

    print(f"  [+] Ditemukan {len(articles)} artikel")
    return articles[:MAX_ARTICLES]


def parse_article_page(url):
    """Parse halaman artikel untuk mendapatkan konten lengkap."""
    print(f"  [>] Mengambil artikel: {url}")

    html_content = fetch_page(url)
    if not html_content:
        return None

    soup = BeautifulSoup(html_content, 'lxml')
    article_data = {}

    article = soup.select_one('article#article_content')
    if not article:
        article = soup.select_one('article')
    if not article:
        return None

    # JUDUL
    h1 = article.select_one('h1')
    article_data['title'] = h1.get_text(strip=True) if h1 else ''

    # TANGGAL & AUTHOR: "Rabu, 25 Februari 2026 oleh journal"
    meta_elem = article.select_one('p small em')
    reporter = ''
    pub_date_str = ''
    if meta_elem:
        meta_text = meta_elem.get_text(strip=True)
        # Format: "Rabu, 25 Februari 2026 oleh journal"
        if ' oleh ' in meta_text:
            parts = meta_text.split(' oleh ', 1)
            pub_date_str = parts[0].strip()
            reporter = parts[1].strip()
        else:
            pub_date_str = meta_text

    article_data['reporter'] = reporter
    article_data['pub_date'] = parse_date(pub_date_str)

    # GAMBAR
    og_image = soup.find('meta', property='og:image')
    article_data['image'] = og_image.get('content', '') if og_image else ''
    if not article_data['image']:
        main_img = article.select_one('img.v-cover')
        if main_img:
            article_data['image'] = main_img.get('src', '')

    # KONTEN
    content_parts = extract_content(article)
    article_data['content'] = '\n\n'.join(content_parts)

    # TAGS (tidak ada tag di situs ini)
    article_data['tags'] = []

    # KATEGORI dari og:type atau default
    article_data['category'] = 'Artikel'

    return article_data


def extract_content(article):
    """Ekstrak konten dari article#article_content."""
    content_parts = []

    # Skip elemen pertama (h1) dan kedua (meta date)
    skip_first_p = True

    for elem in article.children:
        if not hasattr(elem, 'name') or not elem.name:
            continue

        if elem.name == 'h1':
            continue

        if elem.name == 'p':
            # Skip meta date paragraph
            if skip_first_p and elem.select_one('small em'):
                skip_first_p = False
                continue
            skip_first_p = False

            text = elem.get_text(strip=True)
            if text and len(text) > 5:
                content_parts.append(text)

        elif elem.name == 'center':
            # Skip gambar utama (dalam <center>)
            continue

        elif elem.name in ['h2', 'h3']:
            text = elem.get_text(strip=True)
            if text:
                content_parts.append(f"\n### {text}\n")

        elif elem.name in ['h4', 'h5', 'h6']:
            text = elem.get_text(strip=True)
            if text:
                content_parts.append(f"\n#### {text}\n")

        elif elem.name == 'ol':
            for i, li in enumerate(elem.find_all('li', recursive=False), 1):
                # Judul item (strong)
                strong = li.find('strong')
                if strong:
                    title = strong.get_text(strip=True)
                    content_parts.append(f"\n**{i}. {title}**\n")

                # Paragraf dalam li
                for p in li.find_all('p'):
                    text = p.get_text(strip=True)
                    if text and len(text) > 5:
                        content_parts.append(text)

        elif elem.name == 'ul':
            for li in elem.find_all('li', recursive=False):
                text = li.get_text(strip=True)
                if text:
                    content_parts.append(f"• {text}")

        elif elem.name == 'section':
            # Related posts section, skip
            continue

    return content_parts


# ============================================================
# DATE PARSING
# ============================================================

def parse_date(date_str):
    """Parse tanggal Indonesia ke format RFC 822."""
    if not date_str:
        return datetime.now(WIB).strftime('%a, %d %b %Y %H:%M:%S +0700')

    days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    months_en = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

    # Format: "Rabu, 25 Februari 2026"
    m = re.search(r'(\d{1,2})\s+(\w+)\s+(\d{4})', date_str)
    if m:
        day, month_str, year = m.groups()
        month_num = BULAN_ID.get(month_str.lower(), 0)
        if month_num:
            try:
                dt = datetime(int(year), month_num, int(day), 12, 0, 0)
                return f"{days[dt.weekday()]}, {int(day):02d} {months_en[month_num-1]} {int(year)} 12:00:00 +0700"
            except ValueError:
                pass

    return datetime.now(WIB).strftime('%a, %d %b %Y %H:%M:%S +0700')


# ============================================================
# RSS GENERATION
# ============================================================

def generate_rss(articles_data):
    """Generate file RSS XML."""
    print(f"\n[*] Generating RSS XML...")
    now = datetime.now(WIB).strftime('%a, %d %b %Y %H:%M:%S +0700')

    rss_items = []
    for article in articles_data:
        if not article:
            continue

        content_html = ''

        if article.get('image'):
            content_html += f'<p><img src="{html.escape(article["image"])}" alt="{html.escape(article.get("title", ""))}" style="max-width:100%;" /></p>\n'
        if article.get('reporter'):
            content_html += f'<p><strong>Penulis:</strong> {html.escape(article["reporter"])}</p>\n'

        if article.get('content'):
            for para in article['content'].split('\n\n'):
                para = para.strip()
                if not para:
                    continue
                if para.startswith('\n### '):
                    content_html += f'<h3>{html.escape(para.strip().lstrip("#").strip())}</h3>\n'
                elif para.startswith('\n#### '):
                    content_html += f'<h4>{html.escape(para.strip().lstrip("#").strip())}</h4>\n'
                elif para.startswith('**') and para.endswith('**'):
                    content_html += f'<p><strong>{html.escape(para.strip("*").strip())}</strong></p>\n'
                elif para.startswith('• '):
                    content_html += f'<p>{html.escape(para)}</p>\n'
                else:
                    content_html += f'<p>{html.escape(para)}</p>\n'

        guid = article.get('link', hashlib.md5(article.get('title', '').encode()).hexdigest())

        rss_items.append({
            'title': article.get('title', 'Tanpa Judul'),
            'link': article.get('link', ''),
            'description': content_html,
            'pubDate': article.get('pub_date', now),
            'category': article.get('category', ''),
            'guid': guid,
            'image': article.get('image', ''),
        })

    rss_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:atom="http://www.w3.org/2005/Atom"
     xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>{html.escape(FEED_TITLE)}</title>
    <description>{html.escape(FEED_DESCRIPTION)}</description>
    <link>{html.escape(FEED_LINK)}</link>
    <language>id</language>
    <lastBuildDate>{now}</lastBuildDate>
    <generator>IAINSU RSS Scraper (GitHub Actions)</generator>
'''

    for item in rss_items:
        rss_xml += f'''    <item>
      <title><![CDATA[{item['title']}]]></title>
      <link>{html.escape(item['link'])}</link>
      <guid isPermaLink="true">{html.escape(item['guid'])}</guid>
      <pubDate>{item['pubDate']}</pubDate>
'''
        if item['category']:
            rss_xml += f'      <category><![CDATA[{item["category"]}]]></category>\n'
        if item['image']:
            rss_xml += f'      <media:content url="{html.escape(item["image"])}" medium="image" />\n'
        rss_xml += f'      <description><![CDATA[{item["description"]}]]></description>\n'
        rss_xml += f'      <content:encoded><![CDATA[{item["description"]}]]></content:encoded>\n'
        rss_xml += '    </item>\n'

    rss_xml += '''  </channel>
</rss>'''

    return rss_xml


# ============================================================
# MAIN
# ============================================================

def main():
    """Fungsi utama."""
    print("=" * 60)
    print("  IAINSU RSS Scraper")
    print("=" * 60)
    print(f"  Feed Title : {FEED_TITLE}")
    print(f"  Output     : {OUTPUT_FILE}")
    print(f"  Max Artikel: {MAX_ARTICLES}")
    print(f"  Source URL : {HOMEPAGE_URL}")
    print("=" * 60)

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    # Step 1: Scrape homepage
    articles = parse_homepage()

    if not articles:
        print("\n[!] Tidak ada artikel ditemukan.")
        return

    print(f"\n[*] Total {len(articles)} artikel akan diproses")

    # Step 2: Fetch konten lengkap setiap artikel
    articles_data = []
    for i, article in enumerate(articles):
        print(f"\n--- Artikel {i+1}/{len(articles)} ---")

        article_data = parse_article_page(article['link'])

        if article_data:
            if not article_data.get('title'):
                article_data['title'] = article['title']
            article_data['link'] = article['link']
            if not article_data.get('image') and article.get('thumb'):
                article_data['image'] = article['thumb']
            articles_data.append(article_data)
        else:
            articles_data.append({
                'title': article['title'],
                'link': article['link'],
                'content': '(Konten tidak dapat diambil)',
                'pub_date': datetime.now(WIB).strftime('%a, %d %b %Y %H:%M:%S +0700'),
                'image': article.get('thumb', ''),
                'reporter': '',
                'tags': [], 'category': 'Artikel', 'caption': '',
            })

        time.sleep(REQUEST_DELAY)

    # Step 3: Generate & simpan RSS
    rss_xml = generate_rss(articles_data)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(rss_xml)

    print(f"\n{'=' * 60}")
    print(f"  SELESAI! File: {OUTPUT_FILE}")
    print(f"  Total artikel: {len(articles_data)}")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    main()
