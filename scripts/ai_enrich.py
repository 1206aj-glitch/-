"""
Gemini가 설교 영상을 직접 보고 요약·키워드·성경구절·타임라인·상황 분류를 채웁니다.

- GEMINI_API_KEY (저장소 Secret)가 있을 때만 동작합니다. 없으면 아무것도 하지 않습니다.
- 공개 유튜브 영상 URL을 그대로 넘기므로 자막 추출이 필요 없습니다.
- 무료 등급 한도(하루 영상 8시간, 분당 토큰)를 넘지 않도록 한 번에 AI_MAX_PER_RUN 편까지,
  영상 사이에 쉬는 시간을 두고 처리합니다. 남은 설교는 다음 실행 때 이어서 처리됩니다.
"""
import json, os, re, time, urllib.error, urllib.request

GEMINI_KEY = os.environ.get('GEMINI_API_KEY', '').strip()
MODELS = [m.strip() for m in os.environ.get('GEMINI_MODEL', 'gemini-3.8-flash').split(',') if m.strip()]
MAX_PER_RUN = int(os.environ.get('AI_MAX_PER_RUN', '6') or 6)
PAUSE = int(os.environ.get('AI_PAUSE_SEC', '65') or 65)

AI_VERSION = 2   # 정리 형식이 바뀌면 올림 → 예전 형식으로 정리된 설교도 다시 정리

SITUATIONS = ['상처치유', '우울불안', '고난시련', '실패결핍', '분노용서', '가정가족', '조급인내', '나눔전도']
CATEGORIES = ['통합설교', '음악설교', '주일예배', '비전설교', '영화설교', '문학설교']

PROMPT = """당신은 한국 교회 설교 아카이브 편집자입니다. 첨부한 설교 영상 전체를 보고 아래 JSON 하나만 출력하세요.

영상 제목: {title}
설교 날짜: {date}

작성 규칙
- summary: 이 설교의 '영적 본질'을 성도가 읽기 좋게 3~5문장(250~450자)으로. 설교에서 실제로 강조한 원어(히브리어·헬라어) 풀이, 예화(영화·책·실화), 적용점이 있으면 자연스럽게 담으세요. 영상에 없는 내용은 쓰지 마세요.
- keywords: 해시태그 5~7개. 첫 번째는 설교 종류(#음악설교 등), 원어가 나오면 그 단어도 포함. 예: ["#비전설교","#척박함","#광야","#라파"]
- scripture: 중심 성경 본문 하나. 형식은 반드시 "책이름 N장 N~N절" (시편은 "시편 N편 N절"). 성경 봉독 장면을 기준으로.
- timeline: 영상 흐름을 8~14개 지점으로. time은 영상에서 그 부분이 실제 시작되는 시각 "HH:MM:SS". title은 무엇을 하는 부분인지 구체적으로(예: "성경 봉독 (시편 121:1~2)", "🎵 특송 《하나님의 시간》", "영화 예화: 〈쇼생크 탈출〉의 희망 장면", "헬라어 '아피에미' 강해", "📝 시 낭송 《제목 — 김형종》", "결단 기도"). 시각은 반드시 영상을 기준으로 정확하게.
- insights: '인사이트 & 성령 전술 노트' 3~4개. 각 항목은 label과 text. label은 다음 중에서 설교에 실제로 있는 것만: 원어 강해, 예화, 특송, 시 낭송, 실천 지침, 핵심 메시지. text는 1~2문장으로 구체적으로(예: label "원어 강해", text "히브리어 '라파'는 상처를 꿰매어 온전히 회복시키는 치유를 뜻하며…"; label "실천 지침", text "이번 주 매일 5분, 감사 제목 세 가지를 적고 가족과 나누기"). 실천 지침은 꼭 하나 포함.
- situation: 이 설교가 가장 위로가 될 성도의 마음 상황 하나를 다음 중에서만: {situations}
- category: 다음 중 하나: {categories}

출력 형식 (설명 없이 JSON만):
{{"summary":"...","keywords":["#..."],"scripture":"...","timeline":[{{"time":"00:05:12","title":"..."}}],"insights":[{{"label":"원어 강해","text":"..."}}],"situation":"...","category":"..."}}"""


def quota_day():
    """Gemini 무료 한도가 초기화되는 기준 날짜 (미국 태평양 시간 자정 = 한국 오후 4~5시)"""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo('America/Los_Angeles')).date().isoformat()


def waiting(a):
    """아직 AI 정리가 필요하고, 오늘(한도일) 이미 권한 오류로 실패한 영상이 아닌 설교"""
    if (a.get('ai_v') or 0) >= AI_VERSION:
        return False
    if a.get('ai_denied', 0) >= 7:      # 일주일 내내 볼 수 없던 영상은 포기
        return False
    return a.get('ai_denied_on') != quota_day()


def progress():
    """한 편 정리될 때마다 호출 → 사이트에 바로 저장 (sync_youtube 가 연결)"""
    if progress.hook:
        try:
            progress.hook()
        except Exception as ex:
            print('  (중간 저장 실패, 회차 끝에 저장합니다):', ex)


progress.hook = None


class DailyQuotaExceeded(Exception):
    pass


class ServiceBusy(Exception):
    pass


STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts', 'ai_state.json')


def _state():
    try:
        st = json.load(open(STATE_FILE, encoding='utf-8'))
    except Exception:
        st = {}
    if st.get('day') != quota_day():          # 한도일이 바뀌면 소진 기록 초기화
        st = {'day': quota_day(), 'exhausted': []}
    return st


def _save_state(st):
    json.dump(st, open(STATE_FILE, 'w', encoding='utf-8'), ensure_ascii=False)


_MODELS_CACHE = []


def models():
    """사용할 모델 목록. 무료 한도는 '모델별'로 따로 있으므로 여러 모델을 돌려 쓰면 하루 처리량이 늘고,
    한 모델이 혼잡(503)할 때 다른 모델로 넘어갈 수 있음. 목록은 API에서 자동으로 확인 (조회는 한도에 안 잡힘)."""
    if _MODELS_CACHE:
        return _MODELS_CACHE
    found = []
    try:
        req = urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000',
                                     headers={'x-goog-api-key': GEMINI_KEY})
        with urllib.request.urlopen(req, timeout=60) as r:
            for m in json.loads(r.read().decode('utf-8')).get('models', []):
                name = m.get('name', '').replace('models/', '')
                if 'generateContent' not in (m.get('supportedGenerationMethods') or []):
                    continue
                if not re.match(r'^gemini-\d+(\.\d+)?-(flash|pro)', name):
                    continue
                if re.search(r'lite|image|tts|audio|live|embed|robotics|computer|exp|customtools|\d{3}$', name):   # Flash-Lite는 품질 문제로 제외
                    continue
                found.append(name)
    except Exception as ex:
        print('  모델 목록 조회 실패(기본 모델만 사용):', ex)

    def rank(n):
        v = re.match(r'^gemini-(\d+(?:\.\d+)?)', n)
        ver = float(v.group(1)) if v else 0
        kind = 0 if '-flash' in n else 1   # flash → pro
        return (kind, -ver, 'preview' in n, n)
    for n in MODELS + sorted([n for n in found if n not in MODELS], key=rank)[:5]:
        if n not in _MODELS_CACHE:
            _MODELS_CACHE.append(n)
    print('  사용 모델 순서:', ', '.join(_MODELS_CACHE))
    return _MODELS_CACHE


def quota_used_up():
    """오늘(한도일) 모든 모델의 하루 한도를 다 썼으면 True → 요청을 보내지 않고 바로 끝냄"""
    st = _state()
    if st.get('all'):
        return True
    return False


def mark_quota_used_up():
    st = _state()
    st['all'] = True
    _save_state(st)


def _mark_model_exhausted(model):
    st = _state()
    if model not in st['exhausted']:
        st['exhausted'].append(model)
    _save_state(st)


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), method='POST',
                                 headers={'Content-Type': 'application/json', 'x-goog-api-key': GEMINI_KEY})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read().decode('utf-8'))


def _call_generate(model, prompt, video_url, light=True, mime=None):
    video = {'file_data': {'file_uri': video_url}}
    if mime:
        video['file_data']['mime_type'] = mime
    cfg = {'responseMimeType': 'application/json', 'temperature': 0.3}
    if light:
        # 설교는 음성이 핵심 → 화면은 5초에 1장, 저해상도로 보내 토큰을 크게 줄임 (무료 분당 한도 대응)
        video['video_metadata'] = {'fps': 0.2}
        cfg['mediaResolution'] = 'MEDIA_RESOLUTION_LOW'
    body = {'contents': [{'parts': [video, {'text': prompt}]}], 'generationConfig': cfg}
    j = _post('https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent' % model, body)
    parts = j['candidates'][0]['content']['parts']
    return ''.join(p.get('text', '') for p in parts)


def _call_interactions(model, prompt, video_url):
    body = {'model': model,
            'input': [{'type': 'text', 'text': prompt}, {'type': 'video', 'uri': video_url}],
            'response_format': {'type': 'text', 'mime_type': 'application/json'}}
    j = _post('https://generativelanguage.googleapis.com/v1beta/interactions', body)
    out = []
    for st in j.get('steps', []):
        if st.get('type') == 'model_output':
            out += [c.get('text', '') for c in st.get('content', []) if isinstance(c, dict)]
    return ''.join(out)


def upload_file(path, mime, name=''):
    """영상 파일을 Gemini File API에 올리고 처리가 끝날 때까지 기다림 → (file_uri, file_name). 업로드는 하루 한도에 안 잡힘"""
    size = os.path.getsize(path)
    req = urllib.request.Request('https://generativelanguage.googleapis.com/upload/v1beta/files', method='POST',
                                 data=json.dumps({'file': {'display_name': name[:100] or os.path.basename(path)}}).encode('utf-8'),
                                 headers={'x-goog-api-key': GEMINI_KEY, 'Content-Type': 'application/json',
                                          'X-Goog-Upload-Protocol': 'resumable', 'X-Goog-Upload-Command': 'start',
                                          'X-Goog-Upload-Header-Content-Length': str(size),
                                          'X-Goog-Upload-Header-Content-Type': mime})
    with urllib.request.urlopen(req, timeout=120) as r:
        up_url = r.headers.get('X-Goog-Upload-URL') or r.headers.get('x-goog-upload-url')
    with open(path, 'rb') as f:
        req = urllib.request.Request(up_url, data=f, method='POST',
                                     headers={'Content-Length': str(size), 'X-Goog-Upload-Offset': '0',
                                              'X-Goog-Upload-Command': 'upload, finalize'})
        with urllib.request.urlopen(req, timeout=3600) as r:
            info = json.loads(r.read().decode('utf-8'))['file']
    for _ in range(120):                      # 영상 처리(최대 약 20분) 대기
        if info.get('state') == 'ACTIVE':
            return info['uri'], info['name']
        if info.get('state') == 'FAILED':
            raise RuntimeError('Gemini 영상 처리 실패: %s' % info)
        time.sleep(10)
        req = urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/' + info['name'],
                                     headers={'x-goog-api-key': GEMINI_KEY})
        with urllib.request.urlopen(req, timeout=60) as r:
            info = json.loads(r.read().decode('utf-8'))
    raise RuntimeError('Gemini 영상 처리 시간 초과')


def delete_file(name):
    try:
        req = urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/' + name, method='DELETE',
                                     headers={'x-goog-api-key': GEMINI_KEY})
        urllib.request.urlopen(req, timeout=60).close()
    except Exception:
        pass


def _parse(text):
    text = text.strip()
    m = re.search(r'\{[\s\S]*\}', text)
    return json.loads(m.group(0) if m else text)


def ask_gemini(title, date, vid, file_uri=None, mime=None):
    """vid: 유튜브 영상 ID. file_uri/mime: Gemini에 직접 올린 영상 파일(밴드 영상 등)"""
    prompt = PROMPT.format(title=title, date=date, situations=', '.join(SITUATIONS), categories=', '.join(CATEGORIES))
    url = file_uri or ('https://www.youtube.com/watch?v=' + vid)
    errors = []
    callers = [('generate', lambda m: _call_generate(m, prompt, url, True, mime)),
               ('generate(기본설정)', lambda m: _call_generate(m, prompt, url, False, mime))]
    if not file_uri:
        callers.append(('interactions', lambda m: _call_interactions(m, prompt, url)))
    any_busy = False
    for model in models():
        if model in _state()['exhausted'] or model in ask_gemini.busy_models:
            continue
        for name, caller in callers:
            busy, next_model = 0, False
            while True:
                try:
                    return _parse(caller(model)), model
                except urllib.error.HTTPError as ex:
                    full = ex.read().decode('utf-8', 'replace')
                    detail = full[:400]
                    errors.append('%s/%s %s: %s' % (model, name, ex.code, detail))
                    if ex.code == 403 and ('PERMISSION_DENIED' in full or 'permission' in full):
                        # 영상 접근 권한 문제 → 다른 모델로 보내도 같은 결과
                        raise RuntimeError(' || '.join(errors[-2:]))
                    if ex.code == 429:
                        if re.search(r'per ?day|PerDay|daily', full, re.I) or re.search(r'limit:\s*0\b', full):
                            print('    %s: 오늘 무료 한도 소진 → 다음 모델로' % model)
                            _mark_model_exhausted(model)
                            next_model = True
                            break
                        time.sleep(75)                         # 분당 한도 → 잠시 쉬고 재시도 (요청 수에 안 잡힘)
                        continue
                    if ex.code >= 500:
                        # 서버 혼잡 — 실패한 요청도 하루 한도에 포함되므로 한 번만 더 해보고 다른 모델로
                        busy += 1
                        if busy >= 2:
                            print('    %s: 서버 혼잡 → 다음 모델로' % model)
                            ask_gemini.busy_models.add(model)
                            any_busy = True
                            next_model = True
                            break
                        time.sleep(60)
                        continue
                    if ex.code in (400, 404):
                        if ex.code == 404:
                            if re.search(r'no longer available|models/[\w.\-]+ is not found', full, re.I):
                                # 없는/더 이상 제공되지 않는 모델 → 오늘은 이 모델 제외(다시 요청해 한도 낭비하지 않게)
                                print('    %s: 사용할 수 없는 모델(404) → 오늘 제외' % model)
                                _mark_model_exhausted(model)
                            next_model = True
                        break                                  # 요청 형식 문제 → 다른 방식으로
                    raise RuntimeError(' || '.join(errors[-2:]))
                except RuntimeError:
                    raise
                except Exception as ex:
                    errors.append('%s/%s: %s' % (model, name, ex))
                    raise RuntimeError(' || '.join(errors[-2:]))
            if next_model:
                break
    remaining = [m for m in models() if m not in _state()['exhausted']]
    if not remaining:
        raise DailyQuotaExceeded(' || '.join(errors[-2:]))
    if any_busy or all(m in ask_gemini.busy_models for m in remaining):
        raise ServiceBusy(' || '.join(errors[-2:]))
    raise RuntimeError(' || '.join(errors[-4:]))


ask_gemini.busy_models = set()


def _to_item(item, res):
    tl, seen = [], set()
    for t in res.get('timeline') or []:
        m = re.match(r'^\s*(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\s*$', str(t.get('time', '')))
        title = str(t.get('title', '')).strip()
        if not m or not title:
            continue
        h, mi, s = int(m.group(1) or 0), int(m.group(2)), int(m.group(3))
        secs = h * 3600 + mi * 60 + s
        if secs in seen:
            continue
        seen.add(secs)
        tl.append({'time': '[%02d:%02d:%02d]' % (h, mi, s), 'secs': secs, 'title': title})
    tl.sort(key=lambda x: x['secs'])

    summary = str(res.get('summary', '')).strip()
    tags = [k if str(k).startswith('#') else '#' + str(k) for k in (res.get('keywords') or []) if str(k).strip()]
    if summary:
        item['summary'] = summary
    lines = []
    if tags:
        lines.append('💡 주요 키워드: ' + ' '.join(t.replace(' ', '') for t in tags[:8]))
    elif item.get('notes', '').startswith('💡 주요 키워드'):
        lines.append(item['notes'].split('\n')[0])
    for ins in (res.get('insights') or [])[:5]:
        label, text = str(ins.get('label', '')).strip(), str(ins.get('text', '')).strip()
        if label and text:
            lines.append('💡 %s: %s' % (label, text.replace('\n', ' ')))
    if lines:
        item['notes'] = '\n'.join(lines)
    sc = str(res.get('scripture', '')).strip()
    if re.search(r'\d+\s*(장|편)', sc):
        item['scripture'] = sc
    if len(tl) >= 3 and (len(tl) >= len(item.get('timeline') or [])):
        item['timeline'] = tl
    if res.get('situation') in SITUATIONS:
        item['situation'] = res['situation']
    if res.get('category') in CATEGORIES:
        item['categoryKo'] = res['category']
    item['ai'] = True
    item['ai_v'] = AI_VERSION
    return item


def enrich(auto):
    """AI 정리가 아직 안 된 자동 등록 설교를 최신순으로 MAX_PER_RUN 편까지 채움. 처리한 편수를 반환."""
    if not GEMINI_KEY:
        print('  (GEMINI_API_KEY 미설정 — AI 정리 건너뜀)')
        return 0
    # 항상 가장 최근 설교부터 (월요일엔 전날 주일 설교가 맨 먼저).
    # 권한 오류가 난 영상(생방송 직후 처리 중 등)은 같은 '한도일'에는 다시 시도하지 않고 다음 날 다시 맨 앞에서 시도
    todo = [a for a in sorted(auto, key=lambda x: x['date'], reverse=True) if waiting(a)]
    enrich.quota_hit = False
    enrich.busy = False
    enrich.failed = 0
    enrich.more = False
    if not todo:
        return 0
    if quota_used_up():
        print('  오늘 무료 한도를 이미 다 썼음 — 한도 초기화(한국 오후 5시) 후 이어서 정리합니다 (대기 %d편)' % len(todo))
        enrich.quota_hit = True
        return 0
    print('  AI 정리 대기 %d편 → 이번에 최대 %d편 처리' % (len(todo), MAX_PER_RUN))
    done = 0
    perm_fail = 0
    quota_hit = False
    enrich.quota_hit = False
    enrich.failed = 0
    for i, item in enumerate(todo[:MAX_PER_RUN]):
        if i:
            time.sleep(PAUSE)
        try:
            res, model = ask_gemini(item['title'], item['date'], item['id'])
            _to_item(item, res)
            item.pop('ai_denied', None)
            item.pop('ai_denied_on', None)
            done += 1
            progress()
            print('  AI 정리 완료 (%s): %s %s · 타임라인 %d개 · %s' % (
                model, item['date'], item['title'], len(item['timeline']), item.get('scripture', '')))
        except DailyQuotaExceeded:
            print('  오늘 무료 한도에 도달 — 남은 설교는 다음 실행에서 이어서 정리합니다')
            quota_hit = True
            enrich.quota_hit = True
            mark_quota_used_up()
            break
        except ServiceBusy as ex:
            print('  Gemini 서버 혼잡 — 이번 회차는 여기까지, 잠시 후 다시 시도합니다 |', str(ex)[:200])
            enrich.busy = True
            break
        except Exception as ex:
            enrich.failed += 1
            print('  AI 정리 실패:', item['date'], item['title'], '|', ex)
            if 'API key not valid' in str(ex):
                break
            # 403 권한 오류는 그 영상만의 문제일 수 있음(방금 올린 생방송·처리 중 영상 등) → 다음 영상으로.
            # 다만 연속 3편이 모두 403이면 키 문제로 보고 중단
            if 'PERMISSION_DENIED' in str(ex) or 'permission_denied' in str(ex):
                item['ai_denied'] = item.get('ai_denied', 0) + 1
                item['ai_denied_on'] = quota_day()
                perm_fail += 1
                if perm_fail >= 3 and not done:
                    break
            continue
        perm_fail = 0
    # 이번에 처리 못 한 설교가 남았고 한도에도 안 걸렸으면 → 워크플로가 곧바로 다음 회차를 실행
    enrich.more = bool(done) and not quota_hit and not enrich.busy and len(todo) > MAX_PER_RUN
    return done


enrich.failed = 0
enrich.more = False
enrich.quota_hit = False
enrich.busy = False
