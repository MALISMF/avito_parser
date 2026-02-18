"""
Парсер объявлений Авито: квартиры посуточно в Иркутской области.
Режимы: requests (быстро, но возможна блокировка 429) и browser (Playwright — обход блокировки).
"""
import os
import sys
import csv
import json
import time
from pathlib import Path
from datetime import date, timedelta
from urllib.parse import urlencode, urljoin

import requests

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Иркутская область
LOCATION_ID = 628780
# Категория: квартиры
CATEGORY_ID = 24
BASE_URL = "https://www.avito.ru"
ITEMS_API = "https://www.avito.ru/web/1/js/items"
# Страница каталога для открытия в браузере (получаем куки)
CATALOG_URL = "https://www.avito.ru/irkutskaya_oblast/kvartiry/sdam/posutochno"


def _default_headers():
    return {
        'accept': 'application/json',
        'accept-language': 'en-US,en;q=0.9,ru-RU;q=0.8,ru;q=0.7',
        'cache-control': 'no-cache',
        'pragma': 'no-cache',
        'referer': 'https://www.avito.ru/irkutskaya_oblast/kvartiry/sdam/posutochno/-ASgBAgICAkSSA8gQ8AeSUg',
        'sec-ch-ua': '"Not(A:Brand";v="8", "Chromium";v="144", "Google Chrome";v="144"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
        'x-requested-with': 'XMLHttpRequest',
        'x-source': 'client-browser',
    }


def _build_params(page=1, date_from=None, date_to=None):
    """Параметры запроса: квартиры посуточно, Иркутская область."""
    if date_from is None:
        date_from = date.today()
    if date_to is None:
        date_to = date_from + timedelta(days=1)
    from_str = date_from.strftime('%Y%m%d')
    to_str = date_to.strftime('%Y%m%d')
    guests = json.dumps({
        "version": 1,
        "totalCount": 2,
        "adultsCount": 2,
        "children": []
    }, separators=(',', ':'))

    params = {
        'categoryId': CATEGORY_ID,
        'locationId': LOCATION_ID,
        'cd': 0,
        'p': page,
        'params[201]': 1060,           # сдам
        'params[504]': 5257,           # посуточно
        'params[2900][from]': from_str,
        'params[2900][to]': to_str,
        'params[123093]': 3022414,
        'params[170408]': guests,
        'params[178133]': 1,
        'params[183058]': 3331813,
        'verticalCategoryId': 1,
        'rootCategoryId': 4,
        'localPriority': 0,
        'spaFlow': 'true',
        'updateListOnly': 'true',
    }
    # Минимальный набор features (как в curl)
    params['features[imageAspectRatio]'] = '1:1'
    params['features[noPlaceholders]'] = 'true'
    params['features[justSpa]'] = 'true'
    params['features[responsive]'] = 'true'
    params['features[useReload]'] = 'true'
    params['features[simpleCounters]'] = 'true'
    return params


def _extract_items_from_response(data):
    """
    Извлекает список объявлений из ответа API Авито.
    Реальная структура: catalog.items — массив полных объектов объявлений.
    """
    items = []
    if not data or not isinstance(data, dict):
        return items

    # Авито: catalog.items — массив объявлений
    catalog = data.get('catalog')
    if isinstance(catalog, dict):
        arr = catalog.get('items')
        if isinstance(arr, list):
            return arr

    result = data.get('result') or data.get('data')
    if not isinstance(result, dict):
        return items

    # Запасной вариант: result.results + result.items (id -> данные)
    result_ids = result.get('results')
    result_items = result.get('items')
    if isinstance(result_ids, list) and isinstance(result_items, dict):
        for iid in result_ids:
            sid = str(iid)
            if sid in result_items:
                item = dict(result_items[sid])
                item['id'] = item.get('id') or iid
                items.append(item)
        return items

    for list_key in ('results', 'items', 'list'):
        arr = result.get(list_key)
        if isinstance(arr, list) and len(arr) > 0:
            return arr
    if isinstance(data.get('items'), list):
        return data['items']
    return items


def _item_to_row(item, base_url=BASE_URL):
    """Превращает один элемент API Авито (catalog.items) в строку для CSV."""
    if not isinstance(item, dict):
        return None
    item_id = item.get('id') or item.get('itemId') or ''
    item_id = str(item_id).strip()
    title = str(item.get('title') or item.get('name') or '').strip()

    # priceDetailed.value или priceDetailed.fullString
    price_det = item.get('priceDetailed') or {}
    price = ''
    if isinstance(price_det, dict):
        if 'value' in price_det and price_det['value'] is not None:
            price = str(price_det['value'])
        elif price_det.get('fullString'):
            price = str(price_det['fullString']).strip()
    if not price:
        price = str(item.get('price') or item.get('priceValue') or '')

    # urlPath: "/irkutsk/kvartiry/..."
    url = item.get('urlPath') or item.get('url') or item.get('link') or ''
    if url and not url.startswith('http'):
        url = urljoin(base_url, url)
    if not url and item_id:
        url = urljoin(base_url, f'/irkutskaya_oblast/kvartiry/sdam/posutochno/{item_id}')

    # addressDetailed.locationName или location.name
    addr_det = item.get('addressDetailed') or {}
    location = item.get('location') or {}
    address = ''
    if isinstance(addr_det, dict) and addr_det.get('locationName'):
        address = str(addr_det['locationName']).strip()
    if not address and isinstance(location, dict) and location.get('name'):
        address = str(location['name']).strip()
    if not address:
        address = str(item.get('address') or '').strip()

    description = str(item.get('description') or '').strip()
    if len(description) > 500:
        description = description[:500]

    return {
        'id': item_id,
        'title': title,
        'price': price,
        'address': address,
        'description': description,
        'url': url,
    }


class AvitoApartmentsParser:
    """Парсер объявлений Авито: квартиры (посуточно) в Иркутской области."""

    def __init__(self, session=None, cookies=None):
        self.session = session or requests.Session()
        self.session.headers.update(_default_headers())
        if cookies:
            self.session.cookies.update(cookies)
        self.current_dir = Path(__file__).parent
        self.all_items = []

    def fetch_page(self, page=1, date_from=None, date_to=None, context=None, debug=False):
        """Загружает одну страницу объявлений. Возвращает (list of items, has_more)."""
        params = _build_params(page=page, date_from=date_from, date_to=date_to)
        if context:
            params['context'] = context
        url = ITEMS_API + '?' + urlencode(params, doseq=True)
        last_error = None
        for attempt in range(4):  # 0..3: до 4 попыток
            try:
                r = self.session.get(url, timeout=30)
                if debug or r.status_code != 200:
                    print(f"  HTTP {r.status_code}, Content-Type: {r.headers.get('Content-Type', '')}")
                if r.status_code == 429:
                    wait = (attempt + 1) * 10
                    print(f"  429 Too Many Requests. Ждём {wait} с перед повтором...")
                    time.sleep(wait)
                    last_error = f"429 Too Many Requests (попытка {attempt + 1})"
                    continue
                r.raise_for_status()
                ct = r.headers.get('Content-Type', '')
                if 'json' not in ct:
                    if debug:
                        out = self.current_dir / 'output' / 'avito_debug_response.html'
                        out.parent.mkdir(exist_ok=True)
                        out.write_bytes(r.content[:50000])
                        print(f"  Ответ не JSON, сохранён фрагмент в {out}")
                    return [], False
                data = r.json()
                last_error = None
                break
            except requests.exceptions.HTTPError as e:
                last_error = e
                if e.response is not None and e.response.status_code == 429:
                    wait = (attempt + 1) * 10
                    print(f"  429 Too Many Requests. Ждём {wait} с...")
                    time.sleep(wait)
                    continue
                raise
            except Exception as e:
                last_error = e
                print(f"Ошибка запроса страницы {page}: {e}")
                return [], False
        else:
            print(f"Ошибка после повторных попыток: {last_error}")
            print("  Совет: откройте в браузере avito.ru, скопируйте куки и передайте в парсер (см. код).")
            return [], False

        items = _extract_items_from_response(data)
        if debug and not items and isinstance(data, dict):
            out = self.current_dir / 'output' / 'avito_debug.json'
            out.parent.mkdir(exist_ok=True)
            with open(out, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"  Ключи ответа: {list(data.keys())}")
            result = data.get('result') or data.get('data')
            if isinstance(result, dict):
                print(f"  result.keys(): {list(result.keys())}")
            print(f"  Сохранён полный ответ в {out}")
        rows = []
        for it in items:
            row = _item_to_row(it)
            if row:
                rows.append(row)

        # Следующая страница: в ответе totalCount и itemsOnPage на верхнем уровне
        has_more = False
        if isinstance(data, dict):
            total = data.get('totalCount') or data.get('count') or data.get('mainCount')
            per_page = data.get('itemsOnPage') or data.get('itemsOnPageMainSection') or 50
            if total is not None:
                try:
                    total = int(total)
                    per_page = int(per_page)
                    if page * per_page < total:
                        has_more = True
                except (TypeError, ValueError):
                    pass
        if not has_more and len(rows) >= 50:
            has_more = True
        return rows, has_more

    def get_all_apartments(self, max_pages=100, date_from=None, date_to=None):
        """Собирает объявления со всех страниц и сохраняет в CSV."""
        if date_from is None:
            date_from = date.today()
        if date_to is None:
            date_to = date_from + timedelta(days=1)
        print(f"Регион: Иркутская область (locationId={LOCATION_ID})")
        print(f"Категория: квартиры посуточно (categoryId={CATEGORY_ID})")
        print(f"Даты: {date_from.strftime('%d.%m.%Y')} — {date_to.strftime('%d.%m.%Y')}")
        self.all_items = []
        context = None
        page = 1
        while page <= max_pages:
            print(f"Страница {page}...")
            debug = (page == 1)
            rows, has_more = self.fetch_page(page, date_from, date_to, context, debug=debug)
            if not rows:
                if page == 1:
                    print("Нет объявлений. Проверьте output/avito_debug.json (структура ответа) или куки.")
                break
            self.all_items.extend(rows)
            print(f"  получено {len(rows)} объявлений, всего {len(self.all_items)}")
            if not has_more:
                break
            page += 1
            time.sleep(0.5)
        if self.all_items:
            self._save_to_csv()
            print(f"\nПарсинг завершён. Всего объявлений: {len(self.all_items)}")
        else:
            print("\nНе удалось извлечь объявления.")
        return self.all_items

    def get_all_apartments_browser(self, max_pages=100, date_from=None, date_to=None, headless=True):
        """
        Сбор объявлений через браузер (Playwright). Запросы идут от браузера — обход блокировки по IP.
        Требует: pip install playwright && playwright install chromium
        """
        if not HAS_PLAYWRIGHT:
            print("Установите Playwright: pip install playwright && playwright install chromium")
            return []

        if date_from is None:
            date_from = date.today()
        if date_to is None:
            date_to = date_from + timedelta(days=1)
        print(f"Режим: браузер (обход блокировки)")
        print(f"Регион: Иркутская область. Категория: квартиры посуточно.")
        print(f"Даты: {date_from.strftime('%d.%m.%Y')} — {date_to.strftime('%d.%m.%Y')}")
        self.all_items = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="ru-RU",
            )
            page = context.new_page()
            # Открываем каталог — сайт выставит куки
            print("Открываю страницу каталога...")
            try:
                page.goto(CATALOG_URL, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                print(f"Ошибка загрузки каталога: {e}")
                browser.close()
                return []
            page.wait_for_timeout(2000)
            # Если Авито показал «Доступ ограничен: проблема с IP» — нажмите «Продолжить», решите капчу
            print("\nЕсли видите блокировку — нажмите в браузере «Продолжить», решите капчу.")

            page_num = 1
            while page_num <= max_pages:
                print(f"Страница {page_num}...")
                params = _build_params(page=page_num, date_from=date_from, date_to=date_to)
                api_url = ITEMS_API + "?" + urlencode(params, doseq=True)
                api_url_js = json.dumps(api_url)

                try:
                    data = page.evaluate(
                        """
                        async (url) => {
                            const r = await fetch(url, {
                                headers: { 'accept': 'application/json', 'x-requested-with': 'XMLHttpRequest' }
                            });
                            if (!r.ok) return { _status: r.status };
                            return await r.json();
                        }
                        """,
                        api_url,
                    )
                except Exception as e:
                    print(f"  Ошибка: {e}")
                    break

                if isinstance(data, dict) and data.get("_status") == 429:
                    print("  429 — ждём 15 с и повторяем...")
                    time.sleep(15)
                    continue

                if not isinstance(data, dict) or "catalog" not in data:
                    if page_num == 1:
                        print("  Нет данных (возможно блокировка или изменился API).")
                    break

                items = _extract_items_from_response(data)
                rows = []
                for it in items:
                    row = _item_to_row(it)
                    if row:
                        rows.append(row)
                if not rows:
                    break
                self.all_items.extend(rows)
                print(f"  получено {len(rows)} объявлений, всего {len(self.all_items)}")

                total = data.get("totalCount") or data.get("mainCount")
                per_page = data.get("itemsOnPage") or 50
                try:
                    if total is not None and (page_num * int(per_page)) >= int(total):
                        break
                except (TypeError, ValueError):
                    pass
                page_num += 1
                time.sleep(1)

            browser.close()

        if self.all_items:
            self._save_to_csv()
            print(f"\nПарсинг завершён. Всего объявлений: {len(self.all_items)}")
        else:
            print("\nНе удалось извлечь объявления.")
        return self.all_items

    def _save_to_csv(self):
        """Сохраняет объявления в output/avito_apartments.csv."""
        if not self.all_items:
            return
        output_dir = self.current_dir / 'output'
        output_dir.mkdir(exist_ok=True)
        csv_path = output_dir / 'avito_apartments.csv'
        fieldnames = ['id', 'title', 'price', 'address', 'description', 'url']
        try:
            with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=',', quoting=csv.QUOTE_MINIMAL)
                writer.writeheader()
                writer.writerows(self.all_items)
            print(f"Сохранено в {csv_path}")
        except Exception as e:
            print(f"Ошибка сохранения CSV: {e}")


def _cookies_from_string(cookie_string):
    """Парсит строку куки из браузера (Copy as cURL → -b '...') в dict."""
    out = {}
    for part in cookie_string.split(';'):
        part = part.strip()
        if '=' in part:
            k, _, v = part.partition('=')
            out[k.strip()] = v.strip()
    return out


if __name__ == "__main__":
    USE_BROWSER = True
    HEADLESS = os.environ.get("GITHUB_ACTIONS") == "true"

    parser = AvitoApartmentsParser()
    if USE_BROWSER and HAS_PLAYWRIGHT:
        parser.get_all_apartments_browser(headless=HEADLESS)
    else:
        if USE_BROWSER and not HAS_PLAYWRIGHT:
            print("Playwright не установлен. Запуск в режиме requests (может быть 429).")
        parser.get_all_apartments()
