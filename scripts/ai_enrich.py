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


class DailyQuotaExceeded(Exception):
    pass


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), method='POST',
                                 headers={'Content-Type': 'application/json', 'x-goog-api-key': GEMINI_KEY})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read().decode('utf-8'))


def _call_generate(model, prompt, video_url, light=True):
    video = {'file_data': {'file_uri': video_url}}
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


def _parse(text):
    text = text.strip()
    m = re.search(r'\{[\s\S]*\}', text)
    return json.loads(m.group(0) if m else text)


def ask_gemini(title, date, vid):
    prompt = PROMPT.format(title=title, date=date, situations=', '.join(SITUATIONS), categories=', '.join(CATEGORIES))
    url = 'https://www.youtube.com/watch?v=' + vid
    errors = []
    callers = [('generate', lambda m: _call_generate(m, prompt, url, True)),
               ('generate(기본설정)', lambda m: _call_generate(m, prompt, url, False)),
               ('interactions', lambda m: _call_interactions(m, prompt, url))]
    for model in MODELS:
        for name, caller in callers:
            for attempt in range(4):
                try:
                    return _parse(caller(model)), model
                except urllib.error.HTTPError as ex:
                    full = ex.read().decode('utf-8', 'replace')
                    detail = full[:400]
                    errors.append('%s/%s %s: %s' % (model, name, ex.code, detail))
                    if ex.code == 403:
                        # 영상 접근 권한 문제 → 다른 방식으로 다시 보내도 같은 결과, 하루 요청 수만 낭비하므로 바로 포기
                        raise RuntimeError(' || '.join(errors[-2:]))
                    if ex.code == 429:
                        if re.search(r'per ?day|PerDay|daily', full, re.I):
                            raise DailyQuotaExceeded(detail)   # 하루 한도 → 오늘은 여기까지, 다음 실행에서 이어서
                        time.sleep(75)                         # 분당 한도 → 잠시 쉬고 재시도
                        continue
                    if ex.code in (500, 503, 504):
                        time.sleep(30)
                        continue
                    break                                      # 400/404 등 → 다음 방식으로
                except Exception as ex:
                    errors.append('%s/%s: %s' % (model, name, ex))
                    break
    raise RuntimeError(' || '.join(errors[-4:]))


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
    if not todo:
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
            print('  AI 정리 완료 (%s): %s %s · 타임라인 %d개 · %s' % (
                model, item['date'], item['title'], len(item['timeline']), item.get('scripture', '')))
        except DailyQuotaExceeded:
            print('  오늘 무료 한도에 도달 — 남은 설교는 다음 실행에서 이어서 정리합니다')
            quota_hit = True
            enrich.quota_hit = True
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
    enrich.more = bool(done) and not quota_hit and len(todo) > MAX_PER_RUN
    return done


enrich.failed = 0
enrich.more = False
enrich.quota_hit = False
