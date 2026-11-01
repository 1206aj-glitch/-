#!/usr/bin/env python3
"""
유튜브 채널의 새 설교 영상을 index.html 에 자동으로 추가합니다.

- API 키 없이 YouTube RSS 피드를 사용합니다 (최근 영상 15개).
- 채널은 CHANNEL_ID 환경변수 → index.html 의 YT_EMBED.channel → 기존 설교 영상에서 자동 확인 순으로 정합니다.
- 이미 있는 영상(같은 영상 ID)은 건너뜁니다.
- GitHub Actions(.github/workflows/youtube-sync.yml)가 매주 실행합니다.
"""
import json, os, re, sys, time, urllib.parse, urllib.request
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



API_KEY = os.environ.get('YT_API_KEY', '').strip()


def api(path, **params):
    q = urllib.parse.urlencode(dict(params, key=API_KEY))
    with urllib.request.urlopen('https://www.googleapis.com/youtube/v3/%s?%s' % (path, q), timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))


def channel_from_api(html):
    """기존 설교 영상 ID로 채널을 확인 (가장 정확)"""
    seeds = list(dict.fromkeys(re.findall(r'\bid\s*:\s*"([\w-]{11})"', html) + re.findall(r'"id"\s*:\s*"([\w-]{11})"', html)))[:20]
    j = api('videos', part='snippet', id=','.join(seeds))
    counts, names = {}, {}
    for it in j.get('items', []):
        c = it['snippet']['channelId']
        counts[c] = counts.get(c, 0) + 1
        names[c] = it['snippet'].get('channelTitle', '')
    if not counts:
        sys.exit('기존 설교 영상으로 채널을 찾지 못했습니다.')
    cid = max(counts, key=counts.get)
    print('  채널 확인 (기존 설교 영상 기준):', cid, names.get(cid, ''))
    return cid


def entries_from_api(channel, since_date):
    """업로드 목록을 최신순으로 읽어 since_date 이전 영상이 나올 때까지 (최대 200개)"""
    uploads = 'UU' + channel[2:]
    out, token = [], None
    for _ in range(4):
        params = dict(part='snippet,contentDetails,status', playlistId=uploads, maxResults=50)
        if token:
            params['pageToken'] = token
        j = api('playlistItems', **params)
        stop = False
        for it in j.get('items', []):
            sn = it['snippet']
            if it.get('status', {}).get('privacyStatus') not in (None, 'public'):
                continue
            pub = it['contentDetails'].get('videoPublishedAt') or sn.get('publishedAt', '')
            out.append({'vid': it['contentDetails']['videoId'], 'title': sn.get('title', ''),
                        'published': pub, 'desc': sn.get('description', ''), 'pending': False})
            if since_date and pub[:10] < since_date:
                stop = True
        token = j.get('nextPageToken')
        if stop or not token:
            break
    print('  YouTube API 사용: 영상 %d개 확인' % len(out))
    return out


NS = {'a': 'http://www.w3.org/2005/Atom', 'yt': 'http://www.youtube.com/xml/schemas/2015',
      'media': 'http://search.yahoo.com/mrss/'}


def entries_from_rss(xml):
    root = ET.fromstring(xml)
    out = []
    for e in root.findall('a:entry', NS):
        stats = e.find('media:group/media:community/media:statistics', NS)
        out.append({'vid': e.findtext('yt:videoId', '', NS), 'title': e.findtext('a:title', '', NS),
                    'published': e.findtext('a:published', '', NS),
                    'desc': e.findtext('media:group/media:description', '', NS),
                    'pending': stats is not None and stats.get('views') == '0'})
    return out


def entries_from_pages(channel, existing):
    """RSS가 막혔을 때: 채널의 동영상/실시간 목록 페이지와 각 영상 페이지에서 직접 정보를 읽음"""
    ids = []
    for tab in ('videos', 'streams'):
        try:
            page = fetch('https://www.youtube.com/channel/%s/%s' % (channel, tab))
        except Exception as ex:
            print('  목록 페이지 조회 실패', tab, ex)
            continue
        for v in re.findall(r'"videoId":"([\w-]{11})"', page):
            if v not in ids:
                ids.append(v)
    out = []
    for vid in [v for v in ids if v not in existing][:20]:
        try:
            w = fetch('https://www.youtube.com/watch?v=' + vid)
            m = re.search(r'ytInitialPlayerResponse\s*=\s*(\{.+?\})\s*;\s*(?:var\s|</script>)', w, re.S)
            pr = json.loads(m.group(1))
        except Exception as ex:
            print('  영상 정보 조회 실패', vid, ex)
            continue
        vd = pr.get('videoDetails', {})
        if not vd.get('title'):
            print('  영상 정보 차단됨(유튜브 봇 확인 페이지):', vid)
            continue
        mf = pr.get('microformat', {}).get('playerMicroformatRenderer', {})
        live = mf.get('liveBroadcastDetails', {})
        published = mf.get('publishDate') or mf.get('uploadDate') or datetime.now(timezone.utc).isoformat()
        if len(published) == 10:
            published += 'T00:00:00+09:00'
        out.append({'vid': vid, 'title': vd.get('title', ''), 'published': published,
                    'desc': vd.get('shortDescription', ''),
                    'pending': bool(vd.get('isUpcoming') or live.get('isLiveNow'))})
    return out


def get_entries(channel, existing):
    if os.environ.get('RSS_FILE'):
        return entries_from_rss(open(os.environ['RSS_FILE'], encoding='utf-8').read())
    urls = ['https://www.youtube.com/feeds/videos.xml?channel_id=' + channel,
            'https://www.youtube.com/feeds/videos.xml?playlist_id=UU' + channel[2:]]
    for attempt in range(3):
        for u in urls:
            try:
                ents = entries_from_rss(fetch(u))
                print('  RSS 사용:', u)
                return ents
            except Exception as ex:
                print('  RSS 실패 (%d회차): %s %s' % (attempt + 1, u, ex))
        time.sleep(5)
    print('  RSS를 쓸 수 없어 채널 페이지에서 직접 확인합니다')
    return entries_from_pages(channel, existing)


def main():
    html = open(HTML, encoding='utf-8').read()
    if AUTO_S not in html:
        sys.exit('index.html 에 자동 등록 영역(AUTO_SERMONS)이 없습니다.')

    auto = json.loads(read_block(html, AUTO_S, AUTO_E).strip().removeprefix('var AUTO_SERMONS =').rstrip(';').strip() or '[]')
    existing = set(re.findall(r'\bid\s*:\s*"([\w-]{11})"', html)) | set(re.findall(r'"id"\s*:\s*"([\w-]{11})"', html))

    dates = re.findall(r'date\s*:\s*"(\d{4}-\d{2}-\d{2})"', html) + re.findall(r'"date"\s*:\s*"(\d{4}-\d{2}-\d{2})"', html)
    latest = max(dates) if dates else ''
    if API_KEY:
        channel = channel_from_api(html)
        entries = entries_from_api(channel, latest)
    else:
        print('  (YT_API_KEY 미설정 — 키 없이 RSS/페이지 방식 시도)')
        channel = resolve_channel(html)
        entries = get_entries(channel, existing)
    if not entries:
        sys.exit('유튜브에서 영상 목록을 가져오지 못했습니다. 저장소 Settings > Secrets and variables > Actions 에 YT_API_KEY 를 등록해 주세요.')
    kw = re.compile(KEYWORD) if KEYWORD else None
    added = []
    for ent in entries:
        vid, title, published, desc = ent['vid'], ent['title'], ent['published'], ent['desc']
        if not vid or vid in existing:
            continue
        if kw and not kw.search(title):
            print('  제외(제목 필터):', title)
            continue
        if ent.get('pending'):
            print('  보류(아직 공개 전 예약/라이브):', title)
            continue
        item = build_item(vid, title, published, desc)
        if latest and item['date'] < latest:
            continue  # 이미 정리된 설교보다 이전 영상(지난해 영상, 재업로드본 등)은 추가하지 않음
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
