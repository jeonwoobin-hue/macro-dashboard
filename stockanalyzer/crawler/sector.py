"""업종별 시세 크롤러 (네이버 금융 sise_group.naver).
ETF/ETN은 이 업종 분류 체계에 속하지 않아 별도 필터링 없이도 실제 상장기업만 나온다.

네이버는 79개 세분류(GICS 서브산업 수준)로 나눠두는데, 사람이 고르기엔 너무 잘게 쪼개져 있어서
비슷한 세분류끼리 묶어 14개의 큰 업종 그룹으로 재정리해서 제공한다."""
from stockanalyzer.crawler.common import get_soup, parse_number

SECTOR_LIST_URL = "https://finance.naver.com/sise/sise_group.naver?type=upjong"
SECTOR_DETAIL_URL = "https://finance.naver.com/sise/sise_group_detail.naver?type=upjong&no={no}"

_sector_list_cache = None

# 큰 업종 그룹명 -> 네이버 79개 세분류 이름 목록
BROAD_SECTOR_GROUPS = {
    "반도체·IT전자": [
        "전자제품", "사무용전자제품", "반도체와반도체장비", "전자장비와기기",
        "디스플레이장비및부품", "디스플레이패널", "컴퓨터와주변기기", "핸드셋", "통신장비",
    ],
    "소프트웨어·통신·미디어": [
        "소프트웨어", "IT서비스", "다각화된통신서비스", "무선통신서비스",
        "양방향미디어와서비스", "방송과엔터테인먼트", "게임엔터테인먼트", "출판", "광고",
    ],
    "자동차": ["자동차", "자동차부품"],
    "화학·소재": ["화학", "비철금속", "철강", "종이와목재", "포장재", "건축자재", "건축제품"],
    "헬스케어·제약·바이오": [
        "건강관리업체및서비스", "제약", "생명과학도구및서비스", "생물공학",
        "건강관리장비와용품", "건강관리기술",
    ],
    "금융": ["은행", "손해보험", "생명보험", "카드", "증권", "기타금융", "창업투자"],
    "필수소비재·유통": [
        "식품", "음료", "담배", "가정용품", "화장품", "백화점과일반상점", "전문소매",
        "식품과기본식료품소매", "인터넷과카탈로그소매", "판매업체", "무역회사와판매업체",
    ],
    "산업재·기계·조선·방산": ["기계", "조선", "우주항공과국방", "전기장비", "전기제품", "상업서비스와공급품", "복합기업"],
    "에너지·유틸리티": ["에너지장비및서비스", "가스유틸리티", "전기유틸리티", "복합유틸리티", "석유와가스"],
    "운송·물류": ["도로와철도운송", "해운사", "운송인프라", "항공화물운송과물류", "항공사"],
    "건설·부동산": ["건설", "부동산"],
    "레저·여행·교육": ["호텔,레스토랑,레저", "레저용장비와제품", "교육서비스", "다각화된소비자서비스"],
    "섬유·의류·기타소비재": ["섬유,의류,신발,호화품", "가구", "문구류"],
    "기타": ["기타"],
}


def fetch_sector_list():
    """업종 목록 [{no, name}] 을 반환한다. 79개 안팎이며 자주 바뀌지 않아 프로세스 내 캐싱한다."""
    global _sector_list_cache
    if _sector_list_cache is not None:
        return _sector_list_cache

    soup = get_soup(SECTOR_LIST_URL)
    table = soup.select_one("table.type_1")
    sectors = []
    for a in table.select("a[href*='no=']"):
        href = a.get("href", "")
        if "no=" not in href:
            continue
        no = href.split("no=")[-1]
        name = a.text.strip()
        if name:
            sectors.append({"no": no, "name": name})

    _sector_list_cache = sectors
    return sectors


def fetch_sector_stocks(no: str):
    """해당 업종(no)에 속한 종목 [{code, name, price, change_pct, volume, trading_value}] 를 반환한다."""
    soup = get_soup(SECTOR_DETAIL_URL.format(no=no))
    table = soup.select_one("table.type_5")
    if table is None:
        return []

    stocks = []
    for tr in table.select("tbody tr"):
        name_link = tr.select_one("td.name a")
        if not name_link:
            continue
        tds = tr.select("td.number")
        if len(tds) < 6:
            continue
        code = name_link["href"].split("code=")[-1]
        stocks.append(
            {
                "code": code,
                "name": name_link.text.strip(),
                "price": parse_number(tds[0].text),
                "change_pct": parse_number(tds[2].text),
                "volume": parse_number(tds[5].text),
                "trading_value": parse_number(tds[6].text) if len(tds) > 6 else None,
            }
        )
    return stocks


def fetch_broad_sector_list():
    """큰 업종 그룹 이름 목록(14개)을 반환한다."""
    return [{"name": name} for name in BROAD_SECTOR_GROUPS.keys()]


def fetch_stocks_for_broad_sector(broad_name: str):
    """큰 업종 그룹에 속한 세분류들을 모두 조회해 종목을 합친다(중복 제거)."""
    detail_names = BROAD_SECTOR_GROUPS.get(broad_name, [])
    name_to_no = {s["name"]: s["no"] for s in fetch_sector_list()}

    seen_codes = set()
    combined = []
    for detail_name in detail_names:
        no = name_to_no.get(detail_name)
        if not no:
            continue
        for stock in fetch_sector_stocks(no):
            if stock["code"] not in seen_codes:
                seen_codes.add(stock["code"])
                combined.append(stock)
    return combined
