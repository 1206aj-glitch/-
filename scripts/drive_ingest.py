"""
구글 드라이브 '밴드 설교 영상' 폴더의 새 영상을 Gemini로 정리해 사이트에 추가합니다.

- 폴더는 "링크가 있는 모든 사용자 - 뷰어"로 공유되어 있어야 합니다 (API 키로 읽기 위해).
- DRIVE_FOLDER_ID: 폴더 주소 https://drive.google.com/drive/folders/<여기> 부분
- 키는 YT_API_KEY(같은 Google Cloud 프로젝트에서 Google Drive API를 '사용'으로 켜야 함)를 함께 씁니다.
- 파일 이름 규칙: "2019-03-10 비전설교 제목.mp4" (날짜가 없으면 드라이브에 올린 날짜를 씀)
- AI 정리에 성공한 영상만 추가합니다. 같은 날짜 설교가 이미 있으면(유튜브와 같은 설교) 건너뜁니다.
"""
import json, os, re, tempfile, time, urllib.parse, urllib.request

import ai_enrich

FOLDER = os.environ.get('DRIVE_FOLDER_ID', '').strip()
KEY = os.environ.get('YT_API_KEY', '').strip()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_FILE = os.path.join(ROOT, 'scripts', 'drive_skip.json')


def _get(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read().decode('utf-8'))


def list_videos():
    out, token = [], None
    q = "'%s' in parents and trashed=false and mimeType contains 'video/'" % FOLDER
    while True:
        params = {'q': q, 'key': KEY, 'pageSize': 1000,
                  'fields': 'nextPageToken,files(id,name,mimeType,createdTime,size)'}
        if token:
            params['pageToken'] = token
        j = _get('https://www.googleapis.com/drive/v3/files?' + urllib.parse.urlencode(params))
        out += j.get('files', [])
        token = j.get('nextPageToken')
        if not token:
            return out


def parse_name(name, created):
    base = re.sub(r'\.[A-Za-z0-9]{2,4}$', '', name).strip()
    m = (re.search(r'(\d{4})\s*[-.년/]\s*(\d{1,2})\s*[-.월/]\s*(\d{1,2})\s*일?', base)
         or re.search(r'\b(\d{4})(\d{2})(\d{2})\b', base))
    if m:
        date = '%s-%02d-%02d' % (m.group(1), int(m.group(2)), int(m.group(3)))
        title = (base[:m.start()] + ' ' + base[m.end():]).strip(' _-.')
    else:
        date, title = created[:10], base
    title = re.sub(r'[_]+', ' ', title).strip() or '밴드 설교 영상'
    return date, title


def download(fid, path):
    url = 'https://www.googleapis.com/drive/v3/files/%s?alt=media&acknowledgeAbuse=true&key=%s' % (fid, KEY)
    with urllib.request.urlopen(url, timeout=3600) as r, open(path, 'wb') as f:
        while True:
            chunk = r.read(8 << 20)
            if not chunk:
                break
            f.write(chunk)


def ingest(auto, dates, slots):
    """드라이브 폴더의 새 영상을 최신순으로 slots 편까지. 반환: (추가 편수, 남은 영상이 있는지)"""
    if not (FOLDER and KEY and ai_enrich.GEMINI_KEY) or slots <= 0:
        return 0, False
    try:
        skip = set(json.load(open(SKIP_FILE, encoding='utf-8')))
    except Exception:
        skip = set()
    have = {a.get('drive') for a in auto if a.get('drive')}
    try:
        files = list_videos()
    except Exception as ex:
        print('  밴드 영상 폴더를 읽지 못했습니다 (폴더 공유 설정·Google Drive API 사용 여부 확인):', ex)
        return 0, False
    todo = []
    for f in files:
        if f['id'] in have or f['id'] in skip:
            continue
        date, title = parse_name(f['name'], f.get('createdTime', ''))
        if date in dates:
            print('  밴드 영상 건너뜀 (같은 날짜 설교가 이미 있음):', f['name'])
            skip.add(f['id'])
            continue
        todo.append((date, title, f))
    todo.sort(key=lambda x: x[0], reverse=True)
    print('  밴드 영상: 새 영상 %d편 → 이번에 최대 %d편' % (len(todo), slots))
    added, tried = 0, 0
    for date, title, f in todo[:slots]:
        if ai_enrich.quota_used_up():
            break
        tried += 1
        tmp = os.path.join(tempfile.gettempdir(), 'band_' + f['id'])
        fname = None
        try:
            download(f['id'], tmp)
            uri, fname = ai_enrich.upload_file(tmp, f.get('mimeType') or 'video/mp4', title)
            res, model = ai_enrich.ask_gemini(title, date, None, file_uri=uri, mime=f.get('mimeType') or 'video/mp4')
        except ai_enrich.DailyQuotaExceeded:
            print('  오늘 무료 한도에 도달 — 밴드 영상은 다음 실행에서 이어서')
            ai_enrich.enrich.quota_hit = True
            ai_enrich.mark_quota_used_up()
            break
        except ai_enrich.ServiceBusy as ex:
            print('  Gemini 서버 혼잡 — 이번 회차는 여기까지 |', str(ex)[:200])
            ai_enrich.enrich.busy = True
            break
        except Exception as ex:
            print('  밴드 영상 정리 실패:', f['name'], '|', str(ex)[:300])
            continue
        finally:
            if fname:
                ai_enrich.delete_file(fname)
            if os.path.exists(tmp):
                os.remove(tmp)
        item = {'year': date[:4], 'id': 'drive_' + f['id'], 'drive': f['id'], 'title': title, 'date': date,
                'month': '%d월' % int(date[5:7]), 'categoryKo': '통합설교', 'scripture': '', 'summary': '',
                'notes': '', 'timeline': [], 'source': 'band'}
        ai_enrich._to_item(item, res)
        auto.append(item)
        dates.add(date)
        added += 1
        print('  밴드 영상 추가 (%s): %s %s · 타임라인 %d개 · %s' % (
            model, date, title, len(item['timeline']), item.get('scripture', '')))
    json.dump(sorted(skip), open(SKIP_FILE, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    return added, len(todo) > tried
