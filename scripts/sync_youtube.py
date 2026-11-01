#!/usr/bin/env python3
"""
유튜브 채널의 새 설교 영상을 index.html 에 자동으로 추가합니다.

- API 키 없이 YouTube RSS 피드를 사용합니다 (최근 영상 15개).
- 채널은 CHANNEL_ID 환경변수 → index.html 의 YT_EMBED.channel → 기존 설교 영상에서 자동 확인 순으로 정합니다.
- 이미 있는 영상(같은 영상 ID)은 건너뜁니다.
- GitHub Actions(.github/workflows/youtube-sync.yml)가 매주 실행합니다.
"""
import json, os, re, sys, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, 'index.html')
KEYWORD = os.environ.get('SERMON_KEYWORD', '설교|예배|말씀').strip()
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36',
      'Accept-Language': 'ko-KR,ko;q=0.9'}

AUTO_S, AUTO_E = '/*AUTO_SERMONS_START*/', '/*AUTO_SERMONS_END*/'
EMBED_S, EMBED_E = '/*YT_EMBED_START*/', '/*YT_EMBED_END*/'

BOOKS = ['창세기','출애굽기','레위기','민수기','신명기','여호수아','사사기','룻기','사무엘상','사무엘하','열왕기상','열왕기하',
 '역대상','역대하','에스라','느헤미야','에스더','욥기','시편','잠언','전도서','아가','이사야','예레미야','예레미야애가','에스겔',
 '다니엘','호세아','요엘','아모스','오바댜','요나','미가','나훔','하박국','스바냐','학개','스가랴','말라기','마태복음','마가복음',
 '누가복음','요한복음','사도행전','로마서','고린도전서','고린도후서','갈라디아서','에베소서','빌립보서','골로새서','데살로니가전서',
 '데살로니가후서','디모데전서','디모데후서','디도서','빌레몬서','히브리서','야고보서','베드로전서','베드로후서','요한1서','요한2서',
 '요한3서','유다서','요한계시록']


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8', 'replace')


def read_block(html, s, e):
    i, j = html.find(s), html.find(e)
    if i == -1 or j == -1:
        return None
    return html[i + len(s):j]


def resolve_channel(html):
    cid = os.environ.get('CHANNEL_ID', '').strip()
    if re.fullmatch(r'UC[\w-]{22}', cid):
        return cid
    embed = read_block(html, EMBED_S, EMBED_E) or ''
    m = re.search(r'"channel"\s*:\s*"(UC[\w-]{22})"', embed)
    if m:
        return m.group(1)
    # 기존 설교 영상 ID로 채널을 찾아냄
    seeds = re.findall(r'\bid\s*:\s*"([\w-]{11})"', html) + re.findall(r'"id"\s*:\s*"([\w-]{11})"', html)
    for vid in seeds[:6]:
        try:
            page = fetch('https://www.youtube.com/watch?v=' + vid)
        except Exception as ex:
            print('  영상 페이지 조회 실패', vid, ex)
            continue
        m = (re.search(r'itemprop="channelId"\s+content="(UC[\w-]{22})"', page)
             or re.search(r'"channelId"\s*:\s*"(UC[\w-]{22})"', page)
             or re.search(r'/channel/(UC[\w-]{22})', page))
        if m:
            print('  채널 확인 (영상 %s 기준): %s' % (vid, m.group(1)))
            return m.group(1)
    sys.exit('채널을 확인하지 못했습니다. 워크플로 파일의 CHANNEL_ID 에 채널 ID(UC...)를 넣어주세요.')


def build_item(vid, title, published, desc):
    title = title.strip()
    desc = (desc or '').replace('\r', '')
    m = re.search(r'(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일', title) or \
        re.search(r'(\d{4})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2})', title)
    if m:
        date = '%s-%02d-%02d' % (m.group(1), int(m.group(2)), int(m.group(3)))
    else:
        dt = datetime.fromisoformat(published.replace('Z', '+00:00')).astimezone(timezone(timedelta(hours=9)))
        date = dt.strftime('%Y-%m-%d')

    tl, seen = [], set()
    for line in desc.split('\n'):
        tm = re.match(r'^\s*[\[(]?\s*(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\s*[\])]?\s*[-–—:|]?\s*(.+)$', line)
        if not tm:
            continue
        h, mi, s = int(tm.group(1) or 0), int(tm.group(2)), int(tm.group(3))
        secs = h * 3600 + mi * 60 + s
        t = tm.group(4).strip()
        if not t or secs in seen:
            continue
        seen.add(secs)
        tl.append({'time': '[%02d:%02d:%02d]' % (h, mi, s), 'secs': secs, 'title': t})
    tl.sort(key=lambda x: x['secs'])

    scripture = ''
    names = sorted(BOOKS, key=len, reverse=True)
    sm = re.search('(' + '|'.join(names) + r')\s*(\d+)\s*(?:장|편|:)\s*(\d+)(?:\s*[~\-–]\s*(\d+))?', title + '\n' + desc)
    if sm:
        unit = '편' if sm.group(1) == '시편' else '장'
        scripture = '%s %s%s %s%s절' % (sm.group(1), sm.group(2), unit, sm.group(3), ('~' + sm.group(4)) if sm.group(4) else '')

    tags = re.findall(r'#[^\s#]+', desc)[:8]
    notes = ('💡 주요 키워드: ' + ' '.join(tags)) if tags else ''

    body = ' '.join(l for l in desc.split('\n')
                    if l.strip() and not re.match(r'^\s*[\[(]?\s*(\d{1,2}:)?\d{1,2}:\d{2}', l)
                    and not re.match(r'^\s*#', l) and 'http' not in l)
    body = re.sub(r'\s+', ' ', body).strip()
    summary = (body[:400] + ('…' if len(body) > 400 else '')) if body else \
        '(자동 등록된 설교입니다 · 요약은 관리자 화면에서 작성할 수 있습니다)'

    cat = '통합설교'
    for k, v in [('음악설교','음악설교'),('비전설교','비전설교'),('영화설교','영화설교'),('문학설교','문학설교'),
                 ('통합설교','통합설교'),('통합예배','통합설교'),('주일','주일예배'),('부활','주일예배'),
                 ('성탄','주일예배'),('감사','주일예배')]:
        if k in title:
            cat = v
            break

    return {'year': date[:4], 'id': vid, 'title': title, 'date': date, 'month': '%d월' % int(date[5:7]),
            'categoryKo': cat, 'scripture': scripture, 'summary': summary, 'notes': notes, 'timeline': tl}


def main():
    html = open(HTML, encoding='utf-8').read()
    if AUTO_S not in html:
        sys.exit('index.html 에 자동 등록 영역(AUTO_SERMONS)이 없습니다.')

    auto = json.loads(read_block(html, AUTO_S, AUTO_E).strip().removeprefix('var AUTO_SERMONS =').rstrip(';').strip() or '[]')
    existing = set(re.findall(r'\bid\s*:\s*"([\w-]{11})"', html)) | set(re.findall(r'"id"\s*:\s*"([\w-]{11})"', html))

    channel = resolve_channel(html)
    rss_src = os.environ.get('RSS_FILE')
    xml = open(rss_src, encoding='utf-8').read() if rss_src else \
        fetch('https://www.youtube.com/feeds/videos.xml?channel_id=' + channel)

    ns = {'a': 'http://www.w3.org/2005/Atom', 'yt': 'http://www.youtube.com/xml/schemas/2015',
          'media': 'http://search.yahoo.com/mrss/'}
    root = ET.fromstring(xml)
    kw = re.compile(KEYWORD) if KEYWORD else None
    added = []
    for e in root.findall('a:entry', ns):
        vid = e.findtext('yt:videoId', '', ns)
        title = e.findtext('a:title', '', ns)
        published = e.findtext('a:published', '', ns)
        desc = e.findtext('media:group/media:description', '', ns)
        stats = e.find('media:group/media:community/media:statistics', ns)
        if not vid or vid in existing:
            continue
        if kw and not kw.search(title):
            print('  제외(제목 필터):', title)
            continue
        if stats is not None and stats.get('views') == '0':
            print('  보류(아직 공개 전 예약/라이브):', title)
            continue
        item = build_item(vid, title, published, desc)
        auto.append(item)
        existing.add(vid)
        added.append(item)
        print('  추가:', item['date'], item['title'])

    # 채널 ID를 페이지 설정에도 기록 (관리자 화면 '지금 동기화'용)
    embed = read_block(html, EMBED_S, EMBED_E)
    if embed is not None and '"channel":""' in embed:
        html = html.replace(EMBED_S + embed + EMBED_E,
                            EMBED_S + embed.replace('"channel":""', '"channel":"%s"' % channel) + EMBED_E)

    if not added and embed is not None and html == open(HTML, encoding='utf-8').read():
        print('새 설교 없음')
        return

    auto.sort(key=lambda x: x['date'])
    data = json.dumps(auto, ensure_ascii=False).replace('</', '<\\/')
    old_block = AUTO_S + read_block(html, AUTO_S, AUTO_E) + AUTO_E
    html = html.replace(old_block, AUTO_S + 'var AUTO_SERMONS = ' + data + ';' + AUTO_E)
    open(HTML, 'w', encoding='utf-8').write(html)
    print('완료: 새 설교 %d편 추가' % len(added))


if __name__ == '__main__':
    main()
