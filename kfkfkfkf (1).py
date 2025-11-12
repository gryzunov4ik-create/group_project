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

# 1. Сбор всех ссылок
links = set()
for entry in ENTRY_PAGES:
    url = WIKI_BASE + entry
    print(f"Парсим: {entry}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        if r.status_code != 200:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "List_of_Michelin" in href and "restaurant" in href:
                links.add(href)
    except:
        pass
    time.sleep(0.1)

links = sorted(list(links))
print(f"Найдено ссылок: {len(links)}")

# 2. Фильтрация по Европе
filtered = []
for l in links:
    l_norm = l.lower().replace("-", "_")
    country_ok = any(c.lower().replace(" ", "_") in l_norm for c in EU_COUNTRIES)
    city_ok = any(city.lower().replace(" ", "_") in l_norm for city in BIG_CITIES)
    if country_ok or city_ok:
        filtered.append(l)

print(f"Европейских страниц: {len(filtered)}")

# 3. Сбор таблиц с ресторанов
all_parts = []

for i, href in enumerate(filtered, start=1):
    page_url = WIKI_BASE + href
    context = href.split("/")[-1].replace("_", " ")
    print(f"{i}/{len(filtered)}: {context}")

    try:
        r = requests.get(page_url, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            print("Не удалось получить страницу")
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        tables = soup.find_all("table", class_="wikitable")
        if not tables:
            print("Нет таблиц")
            continue

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
            out["context"] = [context] * len(df)

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

            if "chef" in df.columns:
                out["chef"] = df["chef"]
            elif "head_chef" in df.columns:
                out["chef"] = df["head_chef"]
            elif "owner" in df.columns:
                out["chef"] = df["owner"]
            else:
                row_texts = df.astype(str).agg(" ".join, axis=1)
                chefs = []
                for txt in row_texts:
                    m = re.search(r"(?:chef|head chef|run by|by)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})", str(txt))
                    chefs.append(m.group(1) if m else None)
                out["chef"] = chefs

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

    except Exception as e:
        print("Ошибка:", e)
    time.sleep(0.1)

# 4. Сохранение
if not all_parts:
    print("Нет данных")
else:
    combined = pd.concat(all_parts, ignore_index=True)
    combined.drop_duplicates(subset=["restaurant_name", "context", "stars"], inplace=True)

    total = len(combined)
    years_found = combined["year_first_starred"].notna().sum()
    chefs_found = combined["chef"].notna().sum()

    print(f"Найдено годов: {years_found}/{total}, шефов: {chefs_found}/{total}")

    top_chefs = combined["chef"].dropna().value_counts().head(10).reset_index()
    top_chefs.columns = ["chef", "restaurant_count"]

    with pd.ExcelWriter("michelin_europe_v3_simple.xlsx", engine="openpyxl") as writer:
        combined.to_excel(writer, sheet_name="Michelin Restaurants", index=False)
        top_chefs.to_excel(writer, sheet_name="Top Chefs", index=False)

    print(f"Готово. {len(combined)} строк сохранено в michelin_europe_v3_simple.xlsx")