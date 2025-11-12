import re
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup
from unidecode import unidecode
from dateutil import parser as dateparser

# ------------------------------
# НАСТРОЙКИ
# ------------------------------
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/128.0.0.0 Safari/537.36"
}

WIKI_BASE = "https://en.wikipedia.org"

ENTRY_PAGES = [
    "/wiki/List_of_Michelin_3-star_restaurants",
    "/wiki/List_of_Michelin_2-star_restaurants",
    "/wiki/List_of_Michelin_starred_restaurants_in_Europe"
]

EU_COUNTRIES = [
    "France","Belgium","Netherlands","Luxembourg","Italy","Spain","Portugal","Austria",
    "Czech","Hungary","Poland","Switzerland","Slovenia","Denmark","Sweden","Norway",
    "Finland","Estonia","Latvia","Lithuania","Croatia","Serbia","Romania","Bulgaria",
    "United Kingdom","Ireland","Greece","Cyprus","Bosnia","Albania","Montenegro",
    "Macedonia","Malta","Iceland","Slovakia","Germany"
]

BIG_CITIES = [
    "Paris","Lyon","Marseille","Nice","Bordeaux","Brussels","Amsterdam","Rotterdam",
    "Luxembourg","Rome","Milan","Venice","Florence","Naples","Barcelona","Madrid",
    "Seville","Valencia","Lisbon","Porto","Vienna","Prague","Budapest","Krakow","Warsaw",
    "Zurich","Geneva","Ljubljana","Copenhagen","Stockholm","Oslo","Helsinki","Tallinn",
    "Riga","Vilnius","Zagreb","Dubrovnik","Belgrade","Bucharest","Sofia","London",
    "Edinburgh","Manchester","Dublin","Athens","Thessaloniki","Nicosia","Sarajevo",
    "Tirana","Kotor","Skopje","Valletta","Reykjavik","Bratislava"
]

# ------------------------------
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ------------------------------
def norm_col(c):
    c = unidecode(str(c)).lower().strip()
    return re.sub(r"[^a-z0-9]+", "_", c).strip("_")

def try_parse_year(s):
    if pd.isna(s):
        return None
    s = str(s)
    m = re.search(r"(19|20)\d{2}", s)
    if m:
        return int(m.group(0))
    try:
        dt = dateparser.parse(s, fuzzy=True)
        return dt.year if dt else None
    except:
        return None

def extract_stars_from_html(html_row):
    html = str(html_row).lower()
    img = len(re.findall(r"michelin[_-]?star", html))
    svg = len(re.findall(r"<svg", html))
    stars = len(re.findall(r"★", html))
    total = max(img, svg, stars)
    return min(total, 3) if total > 0 else None

# ------------------------------
# ОСНОВНОЙ СКРИПТ
# ------------------------------

links = set()
for entry in ENTRY_PAGES:
    url = WIKI_BASE + entry
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "List_of_Michelin" in href and "restaurant" in href:
                links.add(href)
    except:
        pass
    time.sleep(0.1)

filtered = []
for l in links:
    l_norm = l.lower().replace("-", "_")
    if any(c.lower().replace(" ", "_") in l_norm for c in EU_COUNTRIES) \
       or any(city.lower().replace(" ", "_") in l_norm for city in BIG_CITIES):
        filtered.append(l)

all_parts = []
for href in filtered:
    page_url = WIKI_BASE + href
    try:
        r = requests.get(page_url, headers=HEADERS, timeout=25)
        soup = BeautifulSoup(r.text, "html.parser")
        tables = soup.find_all("table", class_="wikitable")
        for t in tables:
            try:
                df = pd.read_html(str(t))[0]
            except:
                continue
            if len(df) < 2:
                continue

            df.columns = [norm_col(c) for c in df.columns]
            out = pd.DataFrame()
            out["source_url"] = [page_url] * len(df)

            def pick(cols):
                for c in cols:
                    if c in df.columns:
                        return df[c]
                return pd.Series([None] * len(df))

            out["restaurant_name"] = pick(["restaurant", "name"])
            if out["restaurant_name"].isna().all():
                out["restaurant_name"] = df.iloc[:, 0].astype(str)

            out["city"] = pick(["city", "town", "location"])
            out["cuisine_type"] = pick(["cuisine", "style"])

            year_col = None
            for c in ["year", "since", "first_awarded", "notes"]:
                if c in df.columns:
                    year_col = df[c]
                    break
            if year_col is not None:
                out["year_first_starred"] = year_col.apply(try_parse_year)
            else:
                row_texts = df.astype(str).agg(" ".join, axis=1)
                out["year_first_starred"] = row_texts.apply(try_parse_year)

            rows = BeautifulSoup(str(t), "html.parser").find_all("tr")
            stars = [extract_stars_from_html(rw) for rw in rows]
            if len(stars) < len(df):
                stars += [None] * (len(df) - len(stars))
            out["stars"] = stars[:len(df)]

            all_parts.append(out)

    except:
        pass
    time.sleep(0.1)

if not all_parts:
    print("Нет данных")
else:
    combined = pd.concat(all_parts, ignore_index=True)
    combined.drop_duplicates(subset=["restaurant_name", "source_url", "stars"], inplace=True)
    with pd.ExcelWriter("finalochka_stars.xlsx", engine="openpyxl") as writer:
        combined.to_excel(writer, sheet_name="Michelin Restaurants", index=False)

    print("Файл создан")
    print("Строк:", len(combined))