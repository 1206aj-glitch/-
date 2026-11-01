"""
Gemini가 설교 영상을 직접 보고 요약·키워드·성경구절·타임라인·상황 분류를 채웁니다.

- GEMINI_API_KEY (저장소 Secret)가 있을 때만 동작합니다. 없으면 아무것도 하지 않습니다.
- 공개 유튜브 영상 URL을 그대로 넘기므로 자막 추출이 필요 없습니다.
- 무료 등급 한도(하루 영상 8시간, 분당 토큰)를 넘지 않도록 한 번에 AI_MAX_PER_RUN 편까지,
  영상 사이에 쉬는 시간을 두고 처리합니다. 남은 설교는 다음 실행 때 이어서 처리됩니다.
"""
import json, os, re, time, urllib.error, urllib.request

GEMINI_KEY = os.environ.get('GEMINI_API_KEY', '').strip()
MODELS = [m.strip() for m in os.environ.get('GEMINI_MODEL', 'gemini-3.8-flash,gemini-2.5-flash').split(',') if m.strip()]
MAX_PER_RUN = int(os.environ.get('AI_MAX_PER_RUN', '6') or 6)
PAUSE = int(os.environ.get('AI_PAUSE_SEC', '65') or 65)

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
- situation: 이 설교가 가장 위로가 될 성도의 마음 상황 하나를 다음 중에서만: {situations}
- category: 다음 중 하나: {categories}

출력 형식 (설명 없이 JSON만):
{{"summary":"...","keywords":["#..."],"scripture":"...","timeline":[{{"time":"00:05:12","title":"..."}}],"situation":"...","category":"..."}}"""


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), method='POST',
                                 headers={'Content-Type': 'application/json', 'x-goog-api-key': GEMINI_KEY})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read().decode('utf-8'))


def _call_generate(model, prompt, video_url):
    body = {
        'contents': [{'parts': [{'file_data': {'file_uri': video_url}}, {'text': prompt}]}],
        'generationConfig': {'responseMimeType': 'application/json', 'temperature': 0.3,
                             'mediaResolution': 'MEDIA_RESOLUTION_LOW'},
    }
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
    last = None
    for model in MODELS:
        for caller in (_call_generate, _call_interactions):
            for attempt in range(3):
                try:
                    return _parse(caller(model, prompt, url)), model
                except urllib.error.HTTPError as ex:
                    detail = ex.read().decode('utf-8', 'replace')[:300]
                    last = '%s %s %s: %s' % (model, caller.__name__, ex.code, detail)
                    if ex.code == 429:          # 분당 한도 → 잠시 쉬고 재시도
                        time.sleep(70)
                        continue
                    break                       # 400/404 등 → 다른 방식/모델로
                except Exception as ex:
                    last = '%s %s: %s' % (model, caller.__name__, ex)
                    break
    raise RuntimeError(last)


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
    if tags:
        item['notes'] = '💡 주요 키워드: ' + ' '.join(t.replace(' ', '') for t in tags[:8])
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
    return item


def enrich(auto):
    """AI 정리가 아직 안 된 자동 등록 설교를 최신순으로 MAX_PER_RUN 편까지 채움. 처리한 편수를 반환."""
    if not GEMINI_KEY:
        print('  (GEMINI_API_KEY 미설정 — AI 정리 건너뜀)')
        return 0
    todo = [a for a in sorted(auto, key=lambda x: x['date'], reverse=True) if not a.get('ai')]
    if not todo:
        return 0
    print('  AI 정리 대기 %d편 → 이번에 최대 %d편 처리' % (len(todo), MAX_PER_RUN))
    done = 0
    enrich.failed = 0
    for i, item in enumerate(todo[:MAX_PER_RUN]):
        if i:
            time.sleep(PAUSE)
        try:
            res, model = ask_gemini(item['title'], item['date'], item['id'])
            _to_item(item, res)
            done += 1
            print('  AI 정리 완료 (%s): %s %s · 타임라인 %d개 · %s' % (
                model, item['date'], item['title'], len(item['timeline']), item.get('scripture', '')))
        except Exception as ex:
            enrich.failed += 1
            print('  AI 정리 실패:', item['date'], item['title'], '|', ex)
            if 'API key not valid' in str(ex) or 'PERMISSION_DENIED' in str(ex):
                break
    return done


enrich.failed = 0
