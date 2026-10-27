#!/usr/bin/env python3
"""
Vigilante de descuentos
=======================
Revisa las páginas de ofertas configuradas en config.yaml, busca artículos
rebajados más del porcentaje indicado y avisa por Telegram
(o por WhatsApp con CallMeBot, si se configura en lugar de Telegram).

Recuerda qué ha avisado ya (carpeta estado/, un archivo por tienda) para no
repetir el mismo aviso, salvo que el artículo baje todavía más de precio.

Uso:
  python vigilante.py                  revisa todas las tiendas
  python vigilante.py --tienda Fifty   revisa solo una tienda
  python vigilante.py --listar         lista las tiendas (lo usa GitHub)

Variables de entorno:
  TELEGRAM_TOKEN    token del bot que te da @BotFather
  TELEGRAM_CHAT_ID  tu número de chat (se averigua con ACCION=averiguar_chat_id)
  CALLMEBOT_PHONE / CALLMEBOT_APIKEY   (opcional, alternativa por WhatsApp)
  ACCION            normal | prueba_sin_enviar | mensaje_de_prueba | averiguar_chat_id
"""

import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
from urllib.parse import urljoin, urlparse

import requests
import yaml
from bs4 import BeautifulSoup

BASE = os.path.dirname(os.path.abspath(__file__))
RUTA_CONFIG = os.path.join(BASE, "config.yaml")


CABECERAS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9",
}

# ---------------------------------------------------------------------------
# Precios
# ---------------------------------------------------------------------------

_NUM = (r"\d{1,3}(?:[.  ]\d{3})+(?:,\d{1,2})?"   # 1.299,95
        r"|\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?"                # 1,299.95 (libras)
        r"|\d+(?:[.,]\d{1,2})?")                             # 22,99 / 22.99
_MON = r"(?:€|EUR|£|GBP)"
PRECIO_RE = re.compile(rf"{_MON}\s*({_NUM})|({_NUM})\s*{_MON}", re.IGNORECASE)


def numero(texto):
    """'1.299,95' / '1,299.95' / '22,99' / '22.99' / '1299' -> número"""
    s = str(texto).replace(" ", "").replace(" ", "").replace(" ", "").strip()
    if not s:
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")   # 1.299,95
        else:
            s = s.replace(",", "")                      # 1,299.95
    elif "," in s:
        partes = s.split(",")
        if len(partes) == 2 and len(partes[1]) == 3 and len(partes[0]) <= 3 and partes[0] != "0":
            s = s.replace(",", "")                      # 1,299 (miles en inglés)
        else:
            s = s.replace(",", ".")                     # 22,99
    elif s.count(".") == 1 and len(s.split(".")[1]) == 3:
        s = s.replace(".", "")                          # 1.299
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v > 0 else None


def precios_en_texto(texto):
    # Une precios partidos en varias etiquetas: "129 ,95 €" -> "129,95 €"
    texto = re.sub(r"(\d)\s+([,.]\d)", r"\1\2", texto)
    # Quita cifras de ahorro ("Ahorras 90,00 €", "Save £20", "Risparmi 10 €")
    texto = re.sub(
        rf"(ahorr\w*|ahorro|sav(e|ing)\w*|descuento de|risparmi\w*|sconto di|you save)\s*:?\s*{_MON}?\s*(?:{_NUM})\s*{_MON}?",
        " ", texto, flags=re.IGNORECASE,
    )
    encontrados = []
    for a, b in PRECIO_RE.findall(texto):
        v = numero(a or b)
        if v is not None:
            encontrados.append(v)
    return encontrados


MONEDA = "€"


def formato_euros(v, centimos=False, moneda=None):
    if centimos:
        v = v / 100
    moneda = moneda or MONEDA
    if moneda == "£":
        return f"£{v:,.2f}"
    return f"{v:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


# ---------------------------------------------------------------------------
# Descarga de páginas
# ---------------------------------------------------------------------------

def descargar(url):
    r = requests.get(url, headers=CABECERAS, timeout=30)
    return r.status_code, r.text


TEXTOS_CARGAR_MAS = re.compile(
    r"^\W*(cargar|ver|mostrar)\s+m\S{1,2}s\b|^\W*load\s+more\b",
    re.IGNORECASE,
)
TEXTOS_COOKIES = re.compile(
    r"^\s*(aceptar(\s+todas?)?(\s+las)?(\s+cookies)?|accept(\s+all)?(\s+cookies)?|acepto|entendido|de acuerdo)\s*$",
    re.IGNORECASE,
)


def descargar_con_navegador(url, max_cargas=80, max_segundos=480):
    """
    Abre la página en un Chrome invisible (para webs que cargan con JavaScript).
    Baja hasta el final y pulsa "Cargar más" / "Ver más" una y otra vez hasta
    que no aparezcan productos nuevos. Además guarda los datos (JSON) que la
    web descarga por detrás, que suelen traer todos los precios.
    Devuelve (estado_http, html_final, lista_de_json).
    """
    from playwright.sync_api import sync_playwright

    jsons = []
    inicio = time.time()

    def al_recibir(resp):
        try:
            tipo = (resp.headers.get("content-type") or "").lower()
            if "json" in tipo and resp.request.resource_type in ("xhr", "fetch"):
                cuerpo = resp.text()
                if 200 < len(cuerpo) < 8_000_000:
                    jsons.append(json.loads(cuerpo))
        except Exception:
            pass

    with sync_playwright() as p:
        nav = p.chromium.launch(headless=True)
        ctx = nav.new_context(
            user_agent=CABECERAS["User-Agent"],
            locale="es-ES",
            timezone_id="Europe/Madrid",
            viewport={"width": 1366, "height": 900},
        )
        pagina = ctx.new_page()
        pagina.on("response", al_recibir)
        resp = pagina.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            pagina.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass

        # Aceptar cookies si sale el aviso (a veces tapa el botón "Cargar más")
        try:
            pagina.get_by_role("button", name=TEXTOS_COOKIES).first.click(timeout=3000)
        except Exception:
            pass

        alturas_iguales = 0
        cargas = 0
        ultima_altura = 0
        while cargas < max_cargas and time.time() - inicio < max_segundos:
            pagina.mouse.wheel(0, 4000)
            pagina.wait_for_timeout(900)
            pulsado = False
            try:
                boton = pagina.get_by_role("button", name=TEXTOS_CARGAR_MAS).first
                if boton.count() and boton.is_visible():
                    boton.scroll_into_view_if_needed(timeout=3000)
                    boton.click(timeout=5000)
                    pulsado = True
            except Exception:
                pass
            if not pulsado:
                try:
                    enlace = pagina.get_by_role("link", name=TEXTOS_CARGAR_MAS).first
                    if enlace.count() and enlace.is_visible():
                        enlace.click(timeout=5000)
                        pulsado = True
                except Exception:
                    pass
            try:
                pagina.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            altura = pagina.evaluate("document.body.scrollHeight")
            if pulsado:
                cargas += 1
            if altura == ultima_altura and not pulsado:
                alturas_iguales += 1
                if alturas_iguales >= 3:
                    break  # ya no carga nada más
            else:
                alturas_iguales = 0
            ultima_altura = altura

        print(f"    Navegador: {cargas} veces 'cargar más', "
              f"{len(jsons)} respuestas de datos, {int(time.time() - inicio)} s")
        html = pagina.content()
        estado = resp.status if resp else 0
        nav.close()
        return estado, html, jsons


# ---------------------------------------------------------------------------
# Extracción: datos JSON escondidos en la página
# ---------------------------------------------------------------------------

CLAVES_ANTES = {
    "oldprice", "originalprice", "compareatprice", "compare_at_price",
    "listprice", "regularprice", "pricebefore", "crossedprice",
    "strikeprice", "strikethroughprice", "previousprice", "wasprice",
    "fullprice", "initialprice", "basepricebefore", "original", "was",
    "regular", "rrp", "pvp", "precioanterior", "oldpricevalue",
}
CLAVES_AHORA = {
    "price", "saleprice", "finalprice", "currentprice", "sellingprice",
    "offerprice", "specialprice", "discountedprice", "current", "now",
    "final", "sale", "precio", "pricevalue", "amount",
}
CLAVES_NOMBRE = {"name", "title", "productname", "displayname", "nombre"}
CLAVES_URL = {"url", "link", "href", "producturl", "canonicalurl", "uri"}


def _valor_precio(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if v > 0 else None
    if isinstance(v, str):
        p = precios_en_texto(v)
        return p[0] if p else numero(v)
    if isinstance(v, dict):
        for k in ("value", "amount", "price", "centAmount"):
            if k in v:
                return _valor_precio(v[k])
    return None


def _buscar_json(obj, base_url, salida, contexto, prof=0):
    if prof > 40:
        return
    if isinstance(obj, dict):
        bajas = {str(k).lower(): k for k in obj}
        nombre = next(
            (obj[bajas[k]] for k in CLAVES_NOMBRE
             if k in bajas and isinstance(obj[bajas[k]], str) and obj[bajas[k]].strip()),
            None,
        )
        url = next(
            (obj[bajas[k]] for k in CLAVES_URL
             if k in bajas and isinstance(obj[bajas[k]], str) and obj[bajas[k]].strip()),
            None,
        )
        ctx = dict(contexto)
        if nombre:
            ctx["nombre"] = nombre.strip()
        if url:
            ctx["url"] = urljoin(base_url, url.strip())

        antes = next((_valor_precio(obj[bajas[k]]) for k in CLAVES_ANTES if k in bajas), None)
        ahora = next((_valor_precio(obj[bajas[k]]) for k in CLAVES_AHORA if k in bajas), None)
        if antes and ahora and antes > ahora and ctx.get("nombre"):
            salida.append({
                "nombre": ctx["nombre"],
                "url": ctx.get("url", base_url),
                "antes": antes,
                "ahora": ahora,
            })
        for v in obj.values():
            _buscar_json(v, base_url, salida, ctx, prof + 1)
    elif isinstance(obj, list):
        for v in obj:
            _buscar_json(v, base_url, salida, contexto, prof + 1)


def extraer_de_json(soup, base_url):
    productos = []
    decoder = json.JSONDecoder()
    for s in soup.find_all("script"):
        texto = s.string or s.get_text() or ""
        if len(texto) < 50:
            continue
        candidatos = []
        tipo = (s.get("type") or "").lower()
        if "json" in tipo:
            try:
                candidatos.append(json.loads(texto))
            except Exception:
                pass
        else:
            # Objetos del tipo window.__ESTADO__ = {...};
            for m in re.finditer(r"=\s*([\[{])", texto):
                try:
                    obj, _ = decoder.raw_decode(texto[m.start(1):])
                    if isinstance(obj, (dict, list)) and len(json.dumps(obj)) > 40:
                        candidatos.append(obj)
                except Exception:
                    continue
        for c in candidatos:
            _buscar_json(c, base_url, productos, {})
    return productos


# ---------------------------------------------------------------------------
# Extracción: tarjetas de producto visibles en el HTML
# ---------------------------------------------------------------------------

def _limpiar_nombre(texto):
    t = PRECIO_RE.sub(" ", texto)
    t = re.sub(r"-?\d{1,2}\s?%", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" -|·")
    return t[:90]


def _enlace_y_nombre(tarjeta, base_url, nombre_attr=None):
    enlace = tarjeta if tarjeta.name == "a" and tarjeta.get("href") else tarjeta.find("a", href=True)
    url = urljoin(base_url, enlace["href"]) if enlace else base_url
    nombre = (nombre_attr or "").strip()
    if not nombre:
        for sel in ["[class*=name]", "[class*=title]", "[class*=Name]", "[class*=Title]",
                    "h2", "h3", "h4"]:
            n = tarjeta.select_one(sel)
            if n and _limpiar_nombre(n.get_text(" ", strip=True)):
                nombre = _limpiar_nombre(n.get_text(" ", strip=True))
                break
    if not nombre and enlace is not None and enlace.get("title"):
        nombre = enlace["title"].strip()
    if not nombre:
        img = tarjeta.find("img", alt=True)
        if img and img["alt"].strip():
            nombre = img["alt"].strip()
    if not nombre:
        nombre = _limpiar_nombre(tarjeta.get_text(" ", strip=True)) or "(sin nombre)"
    return url.split("#")[0], nombre[:90]


def _num_atributo(el, *nombres):
    for n in nombres:
        v = el.get(n)
        if v not in (None, ""):
            x = numero(str(v).replace("€", "").replace("£", ""))
            if x:
                return x
    return None


def extraer_de_atributos(soup, base_url):
    """
    Formatos estructurados, más fiables que leer el texto:
    - Precio y % de descuento en atributos (PcComponentes, Fulham/Coventry/Hull…)
    - Magento: data-price-type="oldPrice" / "finalPrice"
    - PrestaShop: tarjetas .product-miniature con .regular-price y .price
    """
    productos = []
    # 1) precio + % de descuento en atributos
    for el in soup.select("[data-product-total-discount][data-product-price], [data-discount][data-price]"):
        d = _num_atributo(el, "data-product-total-discount", "data-discount")
        ahora = _num_atributo(el, "data-product-price", "data-price")
        if not d or not ahora or not (0 < d < 100):
            continue
        url, nombre = _enlace_y_nombre(el, base_url, el.get("data-product-name") or el.get("data-title"))
        productos.append({"nombre": nombre, "url": url,
                          "antes": round(ahora / (1 - d / 100), 2), "ahora": ahora})
    if productos:
        return productos
    # 2) Magento
    for item in soup.select(".product-item, li.item.product, .product-item-info"):
        viejo = item.select_one("[data-price-type=oldPrice]")
        final = item.select_one("[data-price-type=finalPrice]")
        if not viejo or not final:
            continue
        antes = _num_atributo(viejo, "data-price-amount")
        ahora = _num_atributo(final, "data-price-amount")
        if antes and ahora and antes > ahora:
            url, nombre = _enlace_y_nombre(item, base_url)
            productos.append({"nombre": nombre, "url": url, "antes": antes, "ahora": ahora})
    if productos:
        return productos
    # 3) PrestaShop
    for item in soup.select(".product-miniature, article[data-id-product]"):
        reg = item.select_one(".regular-price")
        pr = item.select_one("[itemprop=price]") or item.select_one(".price")
        if not reg or not pr:
            continue
        a = precios_en_texto(reg.get_text(" ", strip=True)) or [numero(reg.get_text(strip=True))]
        b = [_num_atributo(pr, "content")] if pr.get("content") else precios_en_texto(pr.get_text(" ", strip=True))
        antes, ahora = (a[0] if a else None), (b[0] if b else None)
        if antes and ahora and antes > ahora:
            url, nombre = _enlace_y_nombre(item, base_url)
            productos.append({"nombre": nombre, "url": url, "antes": antes, "ahora": ahora})
    if productos:
        return productos
    # 4) Tarjetas ScandiPWA (El Ganso): <del class="ProductPrice-HighPrice"> + .ProductPrice-PriceValue
    for item in soup.select(".ProductCard, li.ProductCard"):
        viejo = item.select_one(".ProductPrice-HighPrice")
        final = item.select_one(".ProductPrice-PriceValue")
        if not viejo or not final:
            continue
        a = precios_en_texto(viejo.get_text(" ", strip=True))
        b = precios_en_texto(final.get_text(" ", strip=True))
        antes, ahora = (a[0] if a else None), (b[0] if b else None)
        if antes and ahora and antes > ahora:
            url, nombre = _enlace_y_nombre(item, base_url)
            productos.append({"nombre": nombre, "url": url, "antes": antes, "ahora": ahora})
    return productos


_RANGO_RE = re.compile(rf"{_MON}?\s*(?:{_NUM})\s*{_MON}?\s*[-–]\s*{_MON}?\s*(?:{_NUM})", re.IGNORECASE)


def extraer_de_html(soup, base_url):
    for t in soup(["script", "style", "noscript", "svg", "template"]):
        t.decompose()

    elementos = soup.find_all(True)
    textos = {}
    califica = set()
    for el in elementos:
        txt = el.get_text(" ", strip=True)
        if len(txt) > 600:
            continue
        precios = set(precios_en_texto(txt))
        if len(precios) >= 2:
            textos[id(el)] = (txt, precios)
            califica.add(id(el))

    # Quedarse con los bloques más pequeños que contienen dos precios
    minimos = []
    for el in elementos:
        if id(el) not in califica:
            continue
        if any(id(d) in califica for d in el.find_all(True)):
            continue
        minimos.append(el)

    productos = []
    usados = set()
    for el in minimos:
        txt, precios = textos[id(el)]
        # Descarta rangos de filtros ("10 € - 20 €") y conversiones de moneda ("£20 (€23)")
        if _RANGO_RE.search(txt) or ("£" in txt and ("€" in txt or "EUR" in txt.upper())):
            continue
        if len(precios) > 3:
            continue  # demasiados precios: probablemente mezcla varios productos
        tarjeta = el
        # Subir hasta encontrar la "tarjeta" con enlace, sin mezclar productos
        for _ in range(6):
            if tarjeta.find("a", href=True) or tarjeta.name == "a":
                break
            padre = tarjeta.parent
            if padre is None:
                break
            ptxt = padre.get_text(" ", strip=True)
            if len(ptxt) > 600 or set(precios_en_texto(ptxt)) != precios:
                break
            tarjeta = padre
        if id(tarjeta) in usados:
            continue
        # Si el propio bloque de precios enlaza a varios productos distintos,
        # es que mezcla productos (las tarjetas sí pueden tener un enlace por color)
        enlaces = {urljoin(base_url, a["href"]).split("#")[0].split("?")[0]
                   for a in ([el] if el.name == "a" else []) + el.find_all("a", href=True)
                   if a.get("href") and not a["href"].startswith(("#", "javascript"))}
        if len(enlaces) > 1:
            continue
        usados.add(id(tarjeta))
        url, nombre = _enlace_y_nombre(tarjeta, base_url)
        productos.append({
            "nombre": nombre,
            "url": url,
            "antes": max(precios),
            "ahora": min(precios),
        })
    return productos


# ---------------------------------------------------------------------------
# Tiendas Shopify (catálogo completo y colecciones)
# ---------------------------------------------------------------------------

def _shopify_paginas(url_json, max_paginas=40):
    """Descarga todas las páginas de un products.json de Shopify."""
    todos = []
    for pagina in range(1, max_paginas + 1):
        r = requests.get(url_json, params={"limit": 250, "page": pagina},
                         headers=CABECERAS, timeout=30)
        if r.status_code != 200:
            print(f"    {url_json} página {pagina}: HTTP {r.status_code}")
            break
        lista = r.json().get("products", [])
        if not lista:
            break
        todos += lista
        if len(lista) < 250:
            break
        time.sleep(1)
    return todos


def _shopify_productos(lista, base, filtro=None):
    productos = []
    for p in lista:
        texto = " ".join([p.get("title", ""), p.get("product_type", ""),
                          " ".join(p.get("tags", []) if isinstance(p.get("tags"), list)
                                   else [str(p.get("tags", ""))])]).lower()
        if filtro and filtro.lower() not in texto:
            continue
        mejor = None
        for v in p.get("variants", []):
            antes = numero(v.get("compare_at_price") or "")
            ahora = numero(v.get("price") or "")
            if antes and ahora and antes > ahora:
                cand = {"nombre": p.get("title", "(sin nombre)"),
                        "url": f"{base}/products/{p.get('handle', '')}",
                        "antes": antes, "ahora": ahora}
                if mejor is None or descuento(cand) > descuento(mejor):
                    mejor = cand
        if mejor:
            productos.append(mejor)
    return productos


def extraer_shopify(base, colecciones=None, filtro=None, solo_colecciones=False):
    """Revisa el catálogo completo (salvo solo_colecciones) y cada colección indicada."""
    base = base.rstrip("/")
    productos = []
    fuentes = [] if solo_colecciones else [("catálogo completo", f"{base}/products.json")]
    for c in colecciones or []:
        c = str(c).strip().strip("/").split("/")[-1].split("?")[0]
        if c:
            fuentes.append((f"colección {c}", f"{base}/collections/{c}/products.json"))
    for nombre, url_json in fuentes:
        try:
            lista = _shopify_paginas(url_json)
            rebajados = _shopify_productos(lista, base, filtro)
            maximo = max((descuento(p) for p in rebajados), default=0)
            print(f"  Shopify · {nombre}: {len(lista)} artículos, {len(rebajados)} rebajados "
                  f"(máximo {maximo} %)")
            productos += rebajados
        except Exception as e:
            print(f"  Error en Shopify · {nombre}: {e}")
    return productos


# ---------------------------------------------------------------------------
# Lógica principal
# ---------------------------------------------------------------------------

def descuento(p):
    return round((1 - p["ahora"] / p["antes"]) * 100)


def sin_duplicados(productos, url_base=""):
    """Quita repetidos: mismo enlace, o mismo nombre y mismos precios (otro color)."""
    unicos, claves = [], set()
    for p in productos:
        url = p["url"] if p["url"] != url_base else ""
        # quita solo los parámetros de color/talla (dwvar_..., color=...), no la búsqueda
        url_limpia = re.sub(r"([?&])(dwvar_[^=&]*|color|colour|variant)=[^&]*", r"\1", url)
        url_limpia = re.sub(r"[?&]+$", "", re.sub(r"&{2,}|\?&", lambda m: m.group(0)[0], url_limpia))
        k1 = url_limpia or p["nombre"].lower()
        k2 = (p["nombre"].strip().lower(), round(p["antes"], 2), round(p["ahora"], 2))
        if k1 in claves or k2 in claves:
            continue
        claves.add(k1)
        claves.add(k2)
        unicos.append(p)
    return unicos


def extraer_eci(html, base_url):
    """El Corte Inglés: los precios vienen en el bloque 'dataLayer' de la página."""
    m = re.search(r"dataLayer\s*=\s*(\[.*?\]);\s*</script>", html, re.S) or \
        re.search(r"dataLayer\s*=\s*(\[.*?\]);", html, re.S)
    if not m:
        return []
    try:
        datos = json.loads(m.group(1))
    except Exception:
        return []
    prods = []
    for bloque in datos if isinstance(datos, list) else []:
        for p in (bloque or {}).get("products") or []:
            pr = p.get("price") or {}
            antes, ahora = numero(pr.get("o_price") or ""), numero(pr.get("f_price") or "")
            if antes and ahora and antes > ahora:
                prods.append((p.get("name") or "(sin nombre)", p.get("brand") or "", antes, ahora))
    if not prods:
        return []
    # Enlaces de producto de la página, para emparejarlos por nombre
    enlaces = list(dict.fromkeys(re.findall(r'href="(/[a-z0-9-]+/A\d{6,}[^"#?]*)', html)))
    productos = []
    for nombre, marca, antes, ahora in prods:
        clave = slug(nombre)
        url = next((e for e in enlaces if clave and clave in e), None)
        if not url:
            url = "/search-nwx/1/?s=" + requests.utils.quote(f"{marca} {nombre}".strip())
        productos.append({"nombre": f"{marca} · {nombre}" if marca else nombre,
                          "url": urljoin("https://www.elcorteingles.es/", url),
                          "antes": antes, "ahora": ahora})
    return productos


def extraer_amazon(html, base_url):
    """Amazon: resultados de búsqueda; descuento real calculado con el precio tachado."""
    soup = BeautifulSoup(html, "html.parser")
    productos = []
    for card in soup.select('[data-component-type="s-search-result"][data-asin]'):
        asin = card.get("data-asin")
        if not asin or re.search(r"Patrocinado|Sponsored", card.get_text(" ", strip=True)[:400]):
            continue
        tachado = card.select_one('.a-price[data-a-strike="true"] .a-offscreen')
        actual = next((p for p in card.select(".a-price .a-offscreen")
                       if not p.find_parent(attrs={"data-a-strike": "true"})), None)
        if not tachado or not actual:
            continue
        antes = (precios_en_texto(tachado.get_text()) or [None])[0]
        ahora = (precios_en_texto(actual.get_text()) or [None])[0]
        if not (antes and ahora and antes > ahora):
            continue
        titulo = " ".join(t.get_text(" ", strip=True) for t in card.select("h2")) or \
            ((card.find("img", alt=True) or {}).get("alt") or "(sin nombre)")
        productos.append({"nombre": re.sub(r"\s+", " ", titulo)[:90],
                          "url": f"https://{urlparse(base_url).netloc}/dp/{asin}",
                          "antes": antes, "ahora": ahora})
    return productos


def analizar_html(html, url, jsons=()):
    if re.search(r"//(www\.)?amazon\.", url):
        return sin_duplicados(extraer_amazon(html, url), url), None
    if "elcorteingles." in url:
        eci = extraer_eci(html, url)
        if eci:
            return sin_duplicados(eci, url), None
    soup = BeautifulSoup(html, "html.parser")
    atributos = extraer_de_atributos(soup, url)
    if atributos:
        return sin_duplicados(atributos, url), None
    productos = []
    for j in jsons:
        _buscar_json(j, url, productos, {})
    productos += extraer_de_json(soup, url) + extraer_de_html(soup, url)
    return sin_duplicados(productos, url), None


def analizar_url(url, usar_navegador, max_cargas=80):
    jsons = []
    if usar_navegador:
        estado, html, jsons = descargar_con_navegador(url, max_cargas=max_cargas)
    else:
        estado, html = descargar(url)
    if es_bloqueo(estado, html):
        print(f"    BLOQUEADA: la web ha rechazado la visita (HTTP {estado}, protección antibots).")
        return [], estado
    if estado and estado >= 400:
        print(f"    HTTP {estado}: la web ha rechazado la visita.")
    productos, _ = analizar_html(html, url, jsons)
    return productos, estado


def analizar_paginado(plantilla, usar_navegador, estado_tienda, paginas_max, paginas_por_vez,
                      por_pagina=1, ordenado=False, minimo=60, silencioso=False):
    """
    Lee una sección repartida en páginas. La dirección lleva {n} (número de
    página: 1, 2, 3…) o {inicio} (posición del primer artículo: 0, 120, 240…,
    según por_pagina).
    ordenado=True: la sección está ordenada de mayor a menor descuento, así que
    deja de leer en cuanto una página ya no tiene nada por encima del mínimo.
    Si paginas_por_vez es menor que el total, va rotando: en cada ejecución
    continúa donde lo dejó la anterior, y así acaba recorriéndolas todas.
    """
    cursores = estado_tienda.setdefault("cursores", {})
    inicio = 1 if ordenado else int(cursores.get(plantilla, 1))
    if inicio > paginas_max:
        inicio = 1
    productos = []
    leidas = 0
    n = inicio
    while leidas < paginas_por_vez:
        url = plantilla.replace("{n}", str(n)).replace("{inicio}", str((n - 1) * por_pagina))
        try:
            encontrados, estado = analizar_url(url, usar_navegador)
        except Exception as e:
            print(f"    Página {n}: error {e}")
            encontrados, estado = [], 0
        leidas += 1
        if estado in (404, 410):
            print(f"    Página {n}: no existe. Fin de la sección.")
            n = 1
            break
        if estado and estado >= 400:
            print(f"    Página {n}: HTTP {estado}. Se para aquí y se reintenta en la próxima ejecución.")
            cursores[plantilla] = n
            return productos, leidas
        vistas = {q["url"] for q in productos}
        nuevos = [p for p in encontrados if p["url"] not in vistas]
        productos += nuevos
        if not nuevos or n >= paginas_max:
            n = 1  # se ha llegado al final: la próxima vez empieza desde el principio
            break
        if ordenado and max(descuento(p) for p in nuevos) < minimo:
            n = 1  # lo que queda ya está por debajo del mínimo
            break
        n += 1
        time.sleep(1.5)
    if not ordenado:
        cursores[plantilla] = n
    if not silencioso:
        print(f"    {leidas} página(s) leída(s)"
              + ("" if ordenado or n == 1 else f"; la próxima vez continúa en la {n}") + ".")
    return productos, leidas


def urls_de_sitemap(url_sitemap, patron):
    """Saca del mapa del sitio las direcciones que encajan con el patrón (expresión regular)."""
    r = requests.get(url_sitemap, headers=CABECERAS, timeout=60)
    r.raise_for_status()
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r.text)
    reg = re.compile(patron)
    return sorted({u for u in locs if reg.search(u)})


def revisar_categorias(conf, estado_tienda, usar_navegador, minimo):
    """
    Recorre todas las categorías de una tienda (sacadas de su mapa del sitio),
    cada una ordenada por descuento. Si son muchas, va por turnos: cada
    ejecución revisa un grupo y la siguiente continúa con el resto.
    """
    try:
        cats = urls_de_sitemap(conf["sitemap"], conf.get("patron", "."))
    except Exception as e:
        print(f"  No se pudo leer el mapa del sitio: {e}")
        return []
    if not cats:
        print("  El mapa del sitio no tiene categorías que encajen con el patrón.")
        return []
    por_vez = int(conf.get("por_vez", 60))
    cursores = estado_tienda.setdefault("cursores", {})
    clave = "categorias:" + conf["sitemap"]
    ini = int(cursores.get(clave, 0)) % len(cats)
    turno = (cats + cats)[ini:ini + min(por_vez, len(cats))]
    sufijo = conf.get("sufijo", "")
    productos = []
    bloqueos = 0
    for i, cat in enumerate(turno):
        plantilla = cat.rstrip("/") + sufijo
        try:
            encontrados, _ = analizar_paginado(plantilla, usar_navegador, estado_tienda,
                                               int(conf.get("paginas_max", 10)), 10,
                                               ordenado=True, minimo=minimo, silencioso=True)
            productos += encontrados
            bloqueos = 0
        except Exception as e:
            print(f"    {cat}: error {e}")
            bloqueos += 1
            if bloqueos >= 5:
                print("    Demasiados errores seguidos: se para y continúa en la próxima ejecución.")
                turno = turno[:i]
                break
        time.sleep(1.5)
    cursores[clave] = (ini + len(turno)) % len(cats)
    print(f"  Categorías: {len(cats)} en total; revisadas {len(turno)} en esta vuelta "
          f"(la próxima empieza en la nº {cursores[clave] + 1}).")
    return productos


# ---------------------------------------------------------------------------
# Tiendas del grupo Inditex (Lefties, Zara…) mediante su API pública de catálogo
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# WooCommerce (API pública de la tienda)
# ---------------------------------------------------------------------------

def extraer_woo(base):
    """Lee todo lo rebajado de una tienda WooCommerce con su API pública."""
    base = base.rstrip("/")
    productos, pagina, total = [], 1, None
    while pagina <= 50:
        r = requests.get(f"{base}/wp-json/wc/store/v1/products",
                         params={"per_page": 100, "page": pagina, "on_sale": "true"},
                         headers=dict(CABECERAS, Accept="application/json"), timeout=40)
        if r.status_code != 200:
            print(f"  WooCommerce página {pagina}: HTTP {r.status_code}")
            break
        lista = r.json()
        total = r.headers.get("x-wp-total", total)
        if not lista:
            break
        for p in lista:
            pr = p.get("prices") or {}
            dec = int(pr.get("currency_minor_unit", 2) or 2)
            antes = numero(pr.get("regular_price") or "")
            ahora = numero(pr.get("sale_price") or pr.get("price") or "")
            if antes and ahora and antes > ahora:
                productos.append({"nombre": p.get("name") or "(sin nombre)",
                                  "url": p.get("permalink") or base,
                                  "antes": antes / 10 ** dec, "ahora": ahora / 10 ** dec})
        if len(lista) < 100:
            break
        pagina += 1
        time.sleep(1)
    maximo = max((descuento(p) for p in productos), default=0)
    print(f"  WooCommerce: {total or len(productos)} artículos rebajados (máximo {maximo} %)")
    return productos


# ---------------------------------------------------------------------------
# Modo automático: busca las secciones de ofertas y recorre sus páginas
# ---------------------------------------------------------------------------

PALABRAS_OFERTA = re.compile(
    r"\b(sale|outlet|clearance|offers?|reduced|black[\s-]?friday|cyber|"
    r"rebajas?|rebaixes|rebaixas|ofertas?|descuentos?|promoci[oó]n|promos?|liquidaci[oó]n|"
    r"saldi|offert[ae]|sconti|promozion[ei]|deskontu|merkealdi|"
    r"precios?[\s-]+especial(?:es)?|special[\s-]+prices?|prezzi[\s-]+speciali|"
    r"[uú]ltimas[\s-]+unidades|last[\s-]+chance|ultimi[\s-]+pezzi|mid[\s-]+season)\b",
    re.IGNORECASE)
NO_OFERTA = re.compile(
    r"account|cuenta|login|logon|signin|sign-in|cart|basket|carrito|checkout|faq|help|ayuda|"
    r"policy|politica|privacy|terms|condiciones|returns?|devoluci|guest|track|blog|news|"
    r"salesforce|wholesale|presale|pre-sale|resale|sales/order|newsletter|cookie|contact",
    re.IGNORECASE)
MARCAS_BOT = re.compile(r"api-services-support@amazon|/errors/validateCaptcha|sec-if-cpt|_Incapsula_|challenge-platform|cf-chl|cf_chl|captcha-delivery|"
                        r"px-captcha|Access Denied|Request unsuccessful", re.IGNORECASE)


def es_bloqueo(estado, html):
    return (estado in (401, 403, 429, 503) or (estado == 202 and len(html or "") < 500) or
            (html is not None and len(html) < 60000 and bool(MARCAS_BOT.search(html[:60000]))))


def descubrir_secciones(inicio, html, maximo=6, filtro=None):
    """Enlaces de la propia tienda que llevan a secciones de ofertas."""
    filtro_re = re.compile(filtro, re.IGNORECASE) if filtro else None
    soup = BeautifulSoup(html, "html.parser")
    dominio = re.sub(r"^www\.", "", urlparse(inicio).netloc)
    vistos, candidatos = set(), []
    for a in soup.find_all("a", href=True):
        url = urljoin(inicio, a["href"]).split("#")[0]
        if re.sub(r"^www\.", "", urlparse(url).netloc) != dominio:
            continue
        texto = (a.get_text(" ", strip=True) or "")[:60]
        ruta = urlparse(url).path + "?" + urlparse(url).query
        if not (PALABRAS_OFERTA.search(texto) or PALABRAS_OFERTA.search(ruta.replace("-", " ").replace("/", " "))):
            continue
        if NO_OFERTA.search(ruta) or NO_OFERTA.search(texto):
            continue
        if filtro_re and not filtro_re.search(url):
            continue
        if url.rstrip("/") == inicio.rstrip("/") or url in vistos:
            continue
        vistos.add(url)
        candidatos.append(url)
    # Las más generales primero (rutas más cortas)
    candidatos.sort(key=lambda u: (len(urlparse(u).path.strip("/").split("/")), len(u)))
    return candidatos[:maximo]


def siguiente_pagina(soup, url_actual, n_actual):
    """Busca el enlace a la página siguiente (rel=next, ?p=, ?page=…)."""
    for sel in ["link[rel=next]", "a[rel=next]", "a.next", "li.next a", "a[aria-label*=Next]",
                "a[aria-label*=Siguiente]", "a[aria-label*=Successiv]", ".pagination-next a",
                "a.pagination__next", "a.action.next"]:
        el = soup.select_one(sel)
        if el and el.get("href"):
            u = urljoin(url_actual, el["href"])
            if u != url_actual:
                return u
    objetivo = n_actual + 1
    for a in soup.find_all("a", href=True):
        h = a["href"]
        if re.search(rf"[?&](p|page|pg|pagina|pageNumber)={objetivo}(?:&|$)", h):
            return urljoin(url_actual, h)
    return None


def leer_seccion(url, navegador, max_paginas=15, max_cargas=60):
    """Lee una sección (y sus páginas siguientes). Devuelve (productos, info)."""
    productos, n, actual = [], 1, url
    bloqueada = False
    while actual and n <= max_paginas:
        try:
            estado, html = descargar(actual)
        except Exception as e:
            print(f"    {actual}: error {e}")
            break
        if es_bloqueo(estado, html):
            bloqueada = True
            break
        soup = BeautifulSoup(html, "html.parser")
        encontrados, _ = analizar_html(html, actual)
        vistas = {p["url"] for p in productos}
        nuevos = [p for p in encontrados if p["url"] not in vistas or p["url"] == actual]
        productos += nuevos
        if n > 1 and not nuevos:
            break
        sig = siguiente_pagina(soup, actual, n)
        actual, n = sig, n + 1
        if actual:
            time.sleep(1.2)
    if (not productos) and navegador:
        try:
            estado, html, jsons = descargar_con_navegador(url, max_cargas=max_cargas)
            if es_bloqueo(estado, html):
                bloqueada = True
            else:
                bloqueada = False
                encontrados, _ = analizar_html(html, url, jsons)
                productos += encontrados
                n = max(n, 2)
        except Exception as e:
            print(f"    Navegador: error {e}")
    return sin_duplicados(productos), {"paginas": max(n - 1, 0), "bloqueada": bloqueada}


def revisar_auto(tienda, navegador):
    """Busca las secciones de ofertas en la portada y las recorre."""
    inicio = tienda["auto"]
    secciones = [str(u) for u in (tienda.get("urls") or [])]
    html = None
    try:
        estado, html = descargar(inicio)
        if es_bloqueo(estado, html) or len(html or "") < 100:
            html = None
            if navegador:
                estado, html, _ = descargar_con_navegador(inicio, max_cargas=0)
                if es_bloqueo(estado, html):
                    html = None
    except Exception as e:
        print(f"  Portada: error {e}")
    if html is None and not secciones:
        print("  BLOQUEADA: la web tiene una protección antibots que no deja leerla desde GitHub.")
        return []
    if html:
        encontradas = descubrir_secciones(inicio, html, int(tienda.get("max_secciones", 6)),
                                          tienda.get("filtro_secciones"))
        for u in encontradas:
            if u not in secciones:
                secciones.append(u)
    if not secciones:
        print("  Ahora mismo la tienda no tiene secciones de ofertas visibles en la portada.")
        return []
    productos = []
    for u in secciones:
        encontrados, info = leer_seccion(u, navegador, int(tienda.get("paginas_max", 15)))
        maximo = max((descuento(p) for p in encontrados), default=0)
        estado_txt = " · BLOQUEADA por antibots" if info["bloqueada"] else ""
        print(f"  {u}\n    -> {len(encontrados)} artículos rebajados en {info['paginas']} página(s) "
              f"(máximo {maximo} %){estado_txt}")
        productos += encontrados
        time.sleep(1.5)
    return productos


def extraer_zara(conf):
    """
    Zara: revisa el catálogo completo de la sección (una sola consulta trae
    todos los artículos) y, además, cada categoría de ofertas que exista en ese
    momento (Special Prices, Rebajas, Black Friday…), que se detectan solas.
    """
    web = conf.get("web", "https://www.zara.com").rstrip("/")
    ruta = conf.get("ruta", "es/es").strip("/")
    seccion = conf.get("seccion", "HOMBRE").upper()
    patron = re.compile(conf.get("patron_ofertas",
                                 r"special price|precios? especial|rebaj|\bsale\b|black|outlet|%"),
                        re.IGNORECASE)
    cab = dict(CABECERAS, Accept="application/json", Referer=f"{web}/{ruta}/")

    r = requests.get(f"{web}/{ruta}/categories", params={"ajax": "true"}, headers=cab, timeout=30)
    r.raise_for_status()
    raiz = next((c for c in r.json().get("categories", [])
                 if (c.get("name") or "").upper().startswith(seccion)), None)
    if not raiz:
        raise RuntimeError(f"no encuentro la sección '{seccion}'")

    fuentes = [(raiz["id"], f"{seccion} (catálogo completo)")]

    def recorrer(lista, camino, en_oferta):
        for c in lista or []:
            nombre = c.get("name") or ""
            oferta = en_oferta or bool(patron.search(nombre))
            if oferta and not c.get("subcategories"):
                fuentes.append((c["id"], camino + " > " + nombre))
            recorrer(c.get("subcategories"), camino + " > " + nombre, oferta)
    recorrer(raiz.get("subcategories"), seccion, False)

    productos = []
    for cat_id, nombre_cat in fuentes:
        try:
            rc = requests.get(f"{web}/{ruta}/category/{cat_id}/products",
                              params={"ajax": "true"}, headers=cab, timeout=90)
            if rc.status_code != 200:
                print(f"    {nombre_cat}: HTTP {rc.status_code}")
                continue
            datos = rc.json()
        except Exception as e:
            print(f"    {nombre_cat}: error {e}")
            continue
        encontrados = []
        total = 0

        def buscar(o):
            nonlocal total
            if isinstance(o, list):
                for x in o:
                    buscar(x)
            elif isinstance(o, dict):
                if "price" in o and o.get("name") and isinstance(o.get("seo"), dict):
                    total += 1
                    ahora, antes = numero(o.get("price") or ""), numero(o.get("oldPrice") or "")
                    if ahora and antes and antes > ahora:
                        seo = o["seo"]
                        encontrados.append({
                            "nombre": o["name"],
                            "url": f"{web}/{ruta}/{seo.get('keyword', 'producto')}-p{seo.get('seoProductId', '')}.html"
                                   + (f"?v1={seo['discernProductId']}" if seo.get("discernProductId") else ""),
                            "antes": antes / 100,
                            "ahora": ahora / 100,
                        })
                    return
                for v in o.values():
                    buscar(v)
        buscar(datos)
        maximo = max((descuento(p) for p in encontrados), default=0)
        print(f"    {nombre_cat}: {total} artículos, {len(encontrados)} rebajados (máximo {maximo} %)")
        productos += encontrados
        time.sleep(1)
    return productos


def extraer_inditex(conf, estado_tienda):
    """
    Lee el catálogo de una sección (p. ej. Hombre) de Lefties/Zara.
    - Las categorías de ofertas (Promoción, Rebajas, Special Prices, Black
      Friday…) se detectan solas por su nombre y se revisan enteras siempre.
    - El resto del catálogo se revisa por turnos (por_vez artículos en cada
      ejecución), porque la ficha de cada artículo pesa mucho.
    """
    web = conf["web"].rstrip("/")
    tienda_id = conf["store"]
    catalogo = conf["catalogo"]
    seccion = conf.get("seccion", "hombre").lower()
    idioma = conf.get("idioma", -5)
    pais = conf.get("ruta_pais", "es")
    por_vez = int(conf.get("por_vez", 200))
    patron = re.compile(conf.get("patron_ofertas",
                                 r"promo|rebaj|oferta|precio|outlet|special|sale|black|%|liquid|[uú]ltimas"),
                        re.IGNORECASE)
    base3 = f"{web}/itxrest/3/catalog/store/{tienda_id}/{catalogo}"
    cab = dict(CABECERAS, Accept="application/json", Referer=web + "/")

    arbol = requests.get(
        f"{web}/itxrest/2/catalog/store/{tienda_id}/{catalogo}/category",
        params={"languageId": idioma, "typeCatalog": 1, "appId": 1}, headers=cab, timeout=30,
    )
    arbol.raise_for_status()
    raiz = next((c for c in arbol.json().get("categories", [])
                 if seccion in (c.get("name") or "").lower()), None)
    if not raiz:
        raise RuntimeError(f"no encuentro la sección '{seccion}'")

    hojas, de_ofertas = [], []

    def recorrer(nodo, en_oferta, ruta):
        for c in nodo.get("subcategories") or []:
            nombre = c.get("name") or ""
            oferta = en_oferta or bool(patron.search(nombre))
            if c.get("subcategories"):
                recorrer(c, oferta, ruta + " > " + nombre)
            elif not c.get("viewCategoryId"):
                hojas.append(c["id"])
                if oferta:
                    de_ofertas.append((c["id"], ruta + " > " + nombre))
    recorrer(raiz, False, raiz.get("name", ""))

    def ids_de(cat):
        try:
            r = requests.get(f"{base3}/category/{cat}/product",
                             params={"languageId": idioma, "showProducts": "false", "appId": 1},
                             headers=cab, timeout=30)
            if r.status_code == 200:
                return r.json().get("productIds") or []
        except Exception:
            pass
        return []

    ids_ofertas = []
    for cat, ruta in de_ofertas:
        nuevos = ids_de(cat)
        print(f"    Sección de ofertas: {ruta} ({len(nuevos)} artículos)")
        ids_ofertas += nuevos
        time.sleep(0.3)
    if not de_ofertas:
        print("    Ahora mismo no hay secciones de ofertas en esta sección de la web.")

    todos, vistos = [], set()
    for cat in hojas:
        for i in ids_de(cat):
            if i not in vistos:
                vistos.add(i)
                todos.append(i)
        time.sleep(0.2)
    todos.sort()

    cursores = estado_tienda.setdefault("cursores", {})
    clave = f"inditex:{web}:{seccion}"
    ini = int(cursores.get(clave, 0)) % max(len(todos), 1)
    turno = (todos + todos)[ini:ini + min(por_vez, len(todos))]
    cursores[clave] = (ini + len(turno)) % max(len(todos), 1)

    a_leer = list(dict.fromkeys(ids_ofertas + turno))
    productos = []
    leidos = 0
    for i in range(0, len(a_leer), 20):
        lote = ",".join(str(x) for x in a_leer[i:i + 20])
        try:
            r = requests.get(f"{base3}/productsArray",
                             params={"productIds": lote, "languageId": idioma, "appId": 1},
                             headers=cab, timeout=60)
        except Exception as e:
            print(f"    Lote {i // 20 + 1}: error {e}")
            continue
        if r.status_code != 200:
            print(f"    Lote {i // 20 + 1}: HTTP {r.status_code}")
            continue
        for p in r.json().get("products") or []:
            leidos += 1
            mejor = None
            for b in p.get("bundleProductSummaries") or [p]:
                for col in (b.get("detail") or {}).get("colors") or []:
                    for s in col.get("sizes") or []:
                        ahora = numero(s.get("price") or "")
                        antes = numero(s.get("oldPrice") or "")
                        if ahora and antes and antes > ahora:
                            if mejor is None or ahora / antes < mejor["ahora"] / mejor["antes"]:
                                mejor = {"antes": antes / 100, "ahora": ahora / 100}
            if mejor:
                slug_p = re.sub(r"-l\d+$", "", p.get("productUrl") or "producto")
                mejor.update(nombre=p.get("name") or "(sin nombre)",
                             url=f"{web}/{pais}/{slug_p}-c0p{p.get('id')}.html")
                productos.append(mejor)
        time.sleep(0.5)
    print(f"  Catálogo de {seccion}: {len(todos)} artículos en {len(hojas)} categorías. "
          f"Revisados ahora {leidos} (ofertas + turno {ini + 1}–{ini + len(turno)}); "
          f"vuelta completa cada ~{-(-len(todos) // max(por_vez, 1))} ejecuciones.")
    maximo = max((descuento(p) for p in productos), default=0)
    print(f"    -> {len(productos)} artículos rebajados (máximo descuento visto: {maximo} %)")
    return productos


def clave_de(tienda, p):
    base = p["url"] if p["url"] else p["nombre"]
    return hashlib.sha1(f"{tienda}|{base}|{p['nombre']}".encode()).hexdigest()[:16]


def slug(texto):
    t = texto.lower()
    for a, b in zip("áéíóúüñ", "aeiouun"):
        t = t.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-") or "tienda"


def ruta_estado(nombre_tienda):
    return os.path.join(BASE, "estado", f"{slug(nombre_tienda)}.json")


def cargar_estado(nombre_tienda):
    try:
        with open(ruta_estado(nombre_tienda), encoding="utf-8") as f:
            datos = json.load(f)
            datos.setdefault("vistos", {})
            datos.setdefault("cursores", {})
            return datos
    except Exception:
        return {"vistos": {}, "cursores": {}}


def guardar_estado(nombre_tienda, datos):
    limite = (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(days=30)).isoformat()
    datos["vistos"] = {k: v for k, v in datos["vistos"].items()
                       if v.get("ultima_vez", "") >= limite}
    os.makedirs(os.path.join(BASE, "estado"), exist_ok=True)
    with open(ruta_estado(nombre_tienda), "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1, sort_keys=True)
def enviar_telegram(texto):
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    for intento in range(3):
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data={"chat_id": chat, "text": texto, "disable_web_page_preview": "true"},
                timeout=30,
            )
            if r.status_code == 200 and r.json().get("ok"):
                return True
            print(f"    Telegram respondió HTTP {r.status_code}: {r.text[:200]}")
            if r.status_code in (400, 401, 403, 404):
                print("    Revisa los secretos TELEGRAM_TOKEN y TELEGRAM_CHAT_ID, "
                      "y que le hayas escrito /start a tu bot.")
                return False
        except Exception as e:
            print(f"    Error enviando a Telegram: {e}")
        time.sleep(5 * (intento + 1))
    return False


def averiguar_chat_id():
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    if not token:
        print("ERROR: falta el secreto TELEGRAM_TOKEN.")
        sys.exit(1)
    r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30)
    datos = r.json()
    if not datos.get("ok"):
        print(f"ERROR: Telegram no acepta el token: {datos.get('description')}")
        sys.exit(1)
    chats = {}
    for u in datos.get("result", []):
        msg = u.get("message") or u.get("edited_message") or {}
        c = msg.get("chat")
        if c:
            chats[c["id"]] = c.get("first_name") or c.get("title") or ""
    if not chats:
        print("No hay mensajes. Abre tu bot en Telegram, escríbele /start "
              "y vuelve a ejecutar esta acción en menos de 24 horas.")
        sys.exit(1)
    print("\n================================================")
    for cid, nombre in chats.items():
        print(f"  TU CHAT ID ES:  {cid}   ({nombre})")
    print("================================================")
    print("Copia ese número y guárdalo como secreto TELEGRAM_CHAT_ID.\n")


def enviar_aviso(texto):
    if os.environ.get("TELEGRAM_TOKEN", "").strip() and os.environ.get("TELEGRAM_CHAT_ID", "").strip():
        return enviar_telegram(texto)
    if os.environ.get("CALLMEBOT_PHONE", "").strip() and os.environ.get("CALLMEBOT_APIKEY", "").strip():
        return enviar_whatsapp(texto)
    print("ERROR: faltan los secretos TELEGRAM_TOKEN y TELEGRAM_CHAT_ID.")
    return False


def enviar_whatsapp(texto):
    telefono = os.environ.get("CALLMEBOT_PHONE", "").strip()
    clave = os.environ.get("CALLMEBOT_APIKEY", "").strip()
    for intento in range(3):
        try:
            r = requests.get(
                "https://api.callmebot.com/whatsapp.php",
                params={"phone": telefono, "text": texto, "apikey": clave},
                timeout=40,
            )
            ok = r.status_code == 200 and "error" not in r.text.lower()[:300]
            if ok:
                return True
            print(f"    CallMeBot respondió HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"    Error enviando WhatsApp: {e}")
        time.sleep(10 * (intento + 1))
    return False


def trocear(lineas, max_chars=900):
    bloques, actual = [], ""
    for linea in lineas:
        if actual and len(actual) + len(linea) + 2 > max_chars:
            bloques.append(actual)
            actual = ""
        actual += ("\n\n" if actual else "") + linea
    if actual:
        bloques.append(actual)
    return bloques



def revisar_tienda(tienda, config, accion):
    nombre_tienda = tienda.get("nombre", "Tienda")
    minimo = float(config.get("descuento_minimo", 60))
    max_avisos = int(config.get("max_avisos_por_ejecucion", 15))
    centimos = bool(tienda.get("precios_en_centimos", False))
    navegador = bool(tienda.get("navegador", False))
    urls = [str(u) for u in (tienda.get("urls") or []) if u and str(u).startswith("http")]
    paginadas = [str(u) for u in (tienda.get("paginadas") or []) if u and ("{n}" in str(u) or "{inicio}" in str(u))]
    shopify = tienda.get("shopify")

    print(f"\n== {nombre_tienda}")
    if not (urls or paginadas or shopify or tienda.get("categorias") or tienda.get("inditex")
            or tienda.get("zara") or tienda.get("woo") or tienda.get("auto")):
        print("  Sin direcciones configuradas, se salta.")
        return

    moneda = tienda.get("moneda", "€")
    primera_vez = not os.path.exists(ruta_estado(nombre_tienda))
    estado = cargar_estado(nombre_tienda)
    vistos = estado["vistos"]
    productos = []

    if shopify:
        productos += extraer_shopify(shopify, tienda.get("colecciones"), tienda.get("filtro_shopify"),
                                     bool(tienda.get("solo_colecciones", False)))

    if tienda.get("woo"):
        try:
            productos += extraer_woo(tienda["woo"])
        except Exception as e:
            print(f"  Error leyendo WooCommerce: {e}")

    if tienda.get("auto"):
        try:
            productos += revisar_auto(tienda, bool(tienda.get("navegador", True)))
        except Exception as e:
            print(f"  Error en la revisión automática: {e}")
        urls = []  # en modo automático las urls ya se han leído ahí

    for url in urls:
        try:
            encontrados, _ = analizar_url(url, navegador, int(tienda.get("max_cargas", 80)))
            maximo = max((descuento(p) for p in encontrados), default=0)
            print(f"  {url}\n    -> {len(encontrados)} artículos rebajados leídos "
                  f"(máximo descuento visto: {maximo} %)")
            if not encontrados:
                pista = ("pon 'navegador: true' en esta tienda" if not navegador else
                         "puede que la web bloquee las visitas automáticas")
                print(f"    AVISO: no se ha leído ningún artículo. Prueba: {pista}.")
            productos += encontrados
        except Exception as e:
            print(f"  Error leyendo {url}: {e}")
        time.sleep(2)

    for plantilla in paginadas:
        print(f"  {plantilla}")
        encontrados, _ = analizar_paginado(
            plantilla, navegador, estado,
            int(tienda.get("paginas_max", 200)),
            int(tienda.get("paginas_por_vez", 200)),
            por_pagina=int(tienda.get("por_pagina", 1)),
            ordenado=bool(tienda.get("ordenado_por_descuento", False)),
            minimo=minimo,
        )
        maximo = max((descuento(p) for p in encontrados), default=0)
        print(f"    -> {len(encontrados)} artículos rebajados leídos (máximo descuento visto: {maximo} %)")
        if not encontrados:
            print("    AVISO: no se ha leído ningún artículo en esta sección.")
        productos += encontrados

    if tienda.get("categorias"):
        encontrados = revisar_categorias(tienda["categorias"], estado, navegador, minimo)
        maximo = max((descuento(p) for p in encontrados), default=0)
        print(f"    -> {len(encontrados)} artículos rebajados leídos en categorías "
              f"(máximo descuento visto: {maximo} %)")
        productos += encontrados

    if tienda.get("zara"):
        try:
            productos += extraer_zara(tienda["zara"])
        except Exception as e:
            print(f"  Error leyendo el catálogo de Zara: {e}")
            print("  (Si sale HTTP 403, la web está bloqueando a GitHub; avísame y lo cambiamos.)")

    if tienda.get("inditex"):
        try:
            productos += extraer_inditex(tienda["inditex"], estado)
        except Exception as e:
            print(f"  Error leyendo el catálogo: {e}")
            print("  (Si sale HTTP 403, la web está bloqueando a GitHub; avísame y lo cambiamos.)")
            if tienda.get("urls_respaldo"):
                print("  Se usa la lectura con navegador como respaldo.")
                for url in tienda["urls_respaldo"]:
                    try:
                        encontrados, _ = analizar_url(url, True)
                        print(f"  {url} -> {len(encontrados)} artículos rebajados")
                        productos += encontrados
                    except Exception as e2:
                        print(f"  Error leyendo {url}: {e2}")

    productos = sin_duplicados(productos)
    ahora_iso = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).isoformat()
    pendientes = []
    for p in productos:
        d = descuento(p)
        if d < minimo:
            continue
        k = clave_de(nombre_tienda, p)
        ya_avisado = vistos.get(k, {}).get("avisado_precio")
        nuevo = ya_avisado is None or p["ahora"] < ya_avisado * 0.98
        vistos[k] = {
            "nombre": p["nombre"],
            "precio": p["ahora"],
            "descuento": d,
            "avisado_precio": ya_avisado,
            "ultima_vez": ahora_iso,
        }
        if nuevo:
            pendientes.append((d, k, p))

    pendientes.sort(key=lambda x: -x[0])
    print(f"\n  Artículos nuevos con descuento de {minimo:.0f} % o más: {len(pendientes)}")

    resumen_inicial = (primera_vez and bool(config.get("resumen_primera_vez", True))
                       and len(pendientes) > 5)
    if resumen_inicial:
        # Primera revisión de esta tienda: un solo mensaje resumen en vez de decenas
        a_enviar = pendientes
        top = pendientes[:5]
        lineas = [f"🆕 {nombre_tienda}: ahora mismo hay {len(pendientes)} artículos rebajados un "
                  f"{minimo:.0f} % o más. Los 5 mejores:"]
        lineas += [f"🔥 -{d}% {p['nombre']}\n{formato_euros(p['antes'], centimos, moneda)} → "
                   f"{formato_euros(p['ahora'], centimos, moneda)}\n{p['url']}" for d, _, p in top]
        lineas.append("A partir de ahora solo te avisaré de las ofertas nuevas de esta tienda.")
    else:
        a_enviar = pendientes[:max_avisos]
        lineas = [
            f"🔥 -{d}% · {nombre_tienda}\n{p['nombre']}\n"
            f"{formato_euros(p['antes'], centimos, moneda)} → {formato_euros(p['ahora'], centimos, moneda)}\n{p['url']}"
            for d, _, p in a_enviar
        ]
    if not resumen_inicial and len(pendientes) > max_avisos:
        lineas.append(f"…y {len(pendientes) - max_avisos} ofertas más de {nombre_tienda}. "
                      "Te llegarán en el próximo aviso.")

    if not lineas:
        print("  Nada nuevo que avisar.")
    elif accion == "prueba_sin_enviar":
        print("\n--- MODO PRUEBA: esto es lo que se enviaría ---\n")
        print("\n\n".join(lineas))
    else:
        todo_ok = True
        for bloque in trocear(lineas):
            if enviar_aviso(bloque):
                print("  Aviso enviado.")
            else:
                todo_ok = False
            time.sleep(3)
        if todo_ok:
            for _, k, p in a_enviar:
                vistos[k]["avisado_precio"] = p["ahora"]

    if accion != "prueba_sin_enviar":
        guardar_estado(nombre_tienda, estado)


def main():
    accion = os.environ.get("ACCION", "normal").strip() or "normal"
    args = sys.argv[1:]

    with open(RUTA_CONFIG, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    tiendas = config.get("tiendas", []) or []

    tiendas = [t for t in tiendas if t.get("activa", True) is not False]

    def grupo_de(t):
        return t.get("grupo") or t.get("nombre", "Tienda")

    # Usado por GitHub: una tarea en paralelo por grupo de tiendas
    if args[:1] == ["--listar"]:
        print(json.dumps(list(dict.fromkeys(grupo_de(t) for t in tiendas)), ensure_ascii=False))
        return

    # Usado por GitHub: ¿hay que instalar el navegador invisible para este grupo?
    if args[:1] == ["--necesita-navegador"] and len(args) > 1:
        necesita = any(grupo_de(t) == args[1] and (t.get("navegador") or
                       (t.get("auto") and t.get("navegador", True))) for t in tiendas)
        sys.exit(0 if necesita else 1)

    if accion == "averiguar_chat_id":
        averiguar_chat_id()
        sys.exit(0)

    if accion == "mensaje_de_prueba":
        ok = enviar_aviso("✅ Vigilante de descuentos: ¡funciona! A partir de ahora te avisaré aquí.")
        print("Mensaje de prueba enviado." if ok else "No se pudo enviar el mensaje de prueba.")
        sys.exit(0 if ok else 1)

    solo = None
    if args[:1] == ["--tienda"] and len(args) > 1:
        solo = args[1]

    for tienda in tiendas:
        if solo and solo not in (tienda.get("nombre"), grupo_de(tienda)):
            continue
        try:
            revisar_tienda(tienda, config, accion)
        except Exception as e:
            print(f"  Error inesperado en {tienda.get('nombre')}: {e}")


if __name__ == "__main__":
    main()
