"""종목토론실 게시글 제목 기반 간이 한국어 감성분석 (키워드 사전 방식).

두 단계로 매칭한다:
1) 명사/은어 사전 - 문자열 그대로 부분일치 검사 (기존 방식)
2) 동사 어간 사전 - kiwipiepy 형태소 분석으로 어간을 뽑아서 활용형이 달라도 잡아낸다.
   ("오른다"/"올랐다"/"오르네"는 표기가 다 다르지만 형태소 분석하면 전부 어간 "오르"로 정규화된다.)
   단, "가다"/"달리다"처럼 주식과 무관한 문맥에서도 흔히 쓰이는 범용 동사는
   오탐 위험이 커서 어간 사전에 넣지 않는다.
"""
import re

from kiwipiepy import Kiwi

POSITIVE_WORDS = [
    "상승", "급등", "호재", "매수", "대박", "익절", "신고가", "강세", "돌파",
    "기대", "우량", "저평가", "가즈아", "좋다", "좋음", "오른다", "올랐", "상한가",
    "흑자", "실적개선", "성장", "반등", "회복", "매수세", "수급개선", "탄탄",
    "청신호", "호실적", "어닝서프라이즈", "목표가상향", "순항", "굳건", "안심",
    "박수", "환호", "폭등", "쾌청", "달린다", "축포",
    # "간다"/"가보자"는 뺐다: "가다"라는 범용 동사와 겹쳐서 주식과 무관한 문장(예: "학교 간다")도
    # 잘못 긍정으로 잡아내는 오탐이 실제 테스트에서 확인됐다.
    # 아래는 자체 코퍼스(종목토론실 게시글 4,675문장) PPMI 유사어 분석으로 찾아 검증 후 추가한 단어
    "최고", "서프라이즈",
    # 주식 커뮤니티 은어 (충돌 위험 검토 후 추가)
    "떡상", "줍줍", "우상향",
    # 실제 크롤링 데이터(삼성전자 200개 표본)에서 찾은 추가 후보
    "경축", "축하",
]

NEGATIVE_WORDS = [
    "하락", "급락", "악재", "매도", "손절", "하한가", "폭락", "위험", "거품",
    "고평가", "물렸", "물림", "답없다", "망했", "개미지옥", "조심", "위기",
    "부도", "상장폐지", "적자", "실적악화", "불안", "폭탄", "매도세", "수급악화",
    "부진", "충격", "쇼크", "우려", "패닉", "눈물", "물타기", "탈출", "손실",
    "곡소리", "어닝쇼크", "목표가하향", "빨간불", "침체", "추락", "붕괴",
    # 주식 커뮤니티 은어 (충돌 위험 검토 후 추가)
    "떡락", "개미털기", "설거지",
    # 실제 크롤링 데이터(삼성전자 200개 표본)에서 찾은 추가 후보
    "걱정", "공포",
]

# 동사/형용사 어간 사전 - "가다","달리다"처럼 범용적인 동사는 오탐 위험이 커서 제외했다.
POSITIVE_STEMS = {"오르", "급등하", "반등하", "회복하", "돌파하"}
NEGATIVE_STEMS = {"떨어지", "빠지", "무너지", "급락하", "폭락하", "추락하"}

_pos_pattern = re.compile("|".join(map(re.escape, POSITIVE_WORDS)))
_neg_pattern = re.compile("|".join(map(re.escape, NEGATIVE_WORDS)))
_laugh_pattern = re.compile(r"[ㅋㅎ]{2,}")  # "ㅋㅋㅋ", "ㅎㅎ" 등 반복
_kiwi = Kiwi()


def _stem_score(text: str, occupied_spans: list) -> tuple:
    """형태소 분석으로 동사/형용사 어간을 뽑아 POSITIVE_STEMS/NEGATIVE_STEMS와 비교한다.
    문자열 사전 매칭이 이미 차지한 구간(occupied_spans)과 겹치는 토큰은 건너뛴다 —
    예를 들어 "오른다"가 POSITIVE_WORDS에도 있고 그 어간 "오르"가 POSITIVE_STEMS에도 있으면
    같은 단어가 두 번 카운트돼 점수가 부풀려지는 문제가 있었다."""
    pos = neg = 0
    for token in _kiwi.tokenize(text):
        if token.tag not in ("VV", "VA"):
            continue
        span = (token.start, token.start + token.len)
        if any(span[0] < e and span[1] > s for s, e in occupied_spans):
            continue
        if token.form in POSITIVE_STEMS:
            pos += 1
        elif token.form in NEGATIVE_STEMS:
            neg += 1
    return pos, neg


def score_text(text: str) -> int:
    """텍스트 하나에 대해 (긍정 키워드 수 - 부정 키워드 수)를 반환한다."""
    if not text:
        return 0
    pos_matches = list(_pos_pattern.finditer(text))
    neg_matches = list(_neg_pattern.finditer(text))
    pos = len(pos_matches)
    neg = len(neg_matches)
    occupied_spans = [m.span() for m in pos_matches] + [m.span() for m in neg_matches]
    stem_pos, stem_neg = _stem_score(text, occupied_spans)
    total_pos, total_neg = pos + stem_pos, neg + stem_neg
    score = total_pos - total_neg

    # 부정 단어가 있는데 긍정 단어와 상쇄돼 0점(중립)이 되려는 경우, "ㅋㅋㅋ"/"ㅎㅎㅎ"가 같이
    # 있으면 진짜 웃긴 게 아니라 자조·비꼬는 웃음일 가능성이 높다고 보고 부정 쪽으로 판정한다.
    # 예: "급락의 원인이 성장둔화? ㅋㅋㅋ" (급락=부정, 성장=긍정 상쇄 -> 중립이 되던 것을 부정으로)
    if total_neg > 0 and score >= 0 and _laugh_pattern.search(text):
        return -1

    return score


def classify(score: int) -> str:
    if score > 0:
        return "긍정"
    if score < 0:
        return "부정"
    return "중립"


def score_posts(posts: list) -> list:
    """게시글 리스트(dict, 'title' 키 포함)에 'sentiment_score'와 'sentiment_label'을 추가해 반환한다."""
    for post in posts:
        s = score_text(post.get("title", ""))
        post["sentiment_score"] = s
        post["sentiment_label"] = classify(s)
    return posts


# 명사 키워드 추출 시 제외할 흔한 잡음 단어(종목 커뮤니티 게시글 제목에 너무 자주 나와
# 특정 종목/이슈를 대표하지 못하는 것들). 완전한 불용어 사전은 아니고, 실제 표본에서
# 자주 걸리던 단어 위주로 최소한만 추린 것.
_KEYWORD_STOPWORDS = {
    "오늘", "진짜", "정말", "제발", "여기", "우리", "저기", "이거", "그거",
    "사람", "종목", "주식", "완전", "약간", "지금", "생각", "이번", "저번",
    "매매", "장난", "역시", "그냥", "아까",
}


def top_keywords(posts: list, label: str, top_n: int = 3) -> list:
    """label(긍정/부정)로 분류된 게시글 제목들에서 가장 자주 등장한 명사 top_n개를 반환한다.
    감성 사전 단어 매칭이 아니라 형태소 분석 기반 명사 빈도이므로, "유가상승"/"중동"처럼
    감성 단어집에는 없는 실제 화제 키워드도 잡아낼 수 있다."""
    counts: dict = {}
    for post in posts:
        if post.get("sentiment_label") != label:
            continue
        for token in _kiwi.tokenize(post.get("title", "")):
            if token.tag not in ("NNG", "NNP"):
                continue
            word = token.form
            if len(word) < 2 or word in _KEYWORD_STOPWORDS:
                continue
            counts[word] = counts.get(word, 0) + 1
    return [w for w, _ in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:top_n]]


def daily_sentiment_summary(posts: list) -> dict:
    """날짜별로 게시글 감성점수를 집계해 {date: {pos, neg, neutral, total, avg_score}} 형태로 반환한다."""
    summary = {}
    for post in posts:
        date = post["date"]
        bucket = summary.setdefault(
            date, {"pos": 0, "neg": 0, "neutral": 0, "total": 0, "score_sum": 0}
        )
        label = post.get("sentiment_label") or classify(post.get("sentiment_score", 0))
        if label == "긍정":
            bucket["pos"] += 1
        elif label == "부정":
            bucket["neg"] += 1
        else:
            bucket["neutral"] += 1
        bucket["total"] += 1
        bucket["score_sum"] += post.get("sentiment_score", 0)
    for bucket in summary.values():
        bucket["avg_score"] = bucket["score_sum"] / bucket["total"] if bucket["total"] else 0
    return summary
