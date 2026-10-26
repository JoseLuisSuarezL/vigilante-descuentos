#!/usr/bin/env python3
"""
Vigilante de descuentos
=======================
Revisa las páginas de ofertas configuradas en config.yaml, busca artículos
rebajados más del porcentaje indicado y avisa por Telegram
(o por WhatsApp con CallMeBot, si se configura en lugar de Telegram).

Recuerda qué ha avisado ya en vistos.json para no repetir el mismo aviso,
salvo que el artículo baje todavía más de precio.

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
from urllib.parse import urljoin

import requests
import yaml
from bs4 import BeautifulSoup

BASE = os.path.dirname(os.path.abspath(__file__))
RUTA_CONFIG = os.path.join(BASE, "config.yaml")
RUTA_VISTOS = os.path.join(BASE, "vistos.json")

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

_NUM = r"\d{1,3}(?:[.  ]\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?"
PRECIO_RE = re.compile(
    rf"(?:€|EUR)\s*({_NUM})|({_NUM})\s*(?:€|EUR)", re.IGNORECASE
)


def numero(texto):
    """'1.299,95' -> 1299.95 ; '22,99' -> 22.99 ; '22.99' -> 22.99"""
    s = str(texto).replace(" ", "").replace(" ", "").strip()
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") == 1 and len(s.split(".")[1]) == 3:
        s = s.replace(".", "")  # 1.299 -> 1299
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v > 0 else None


def precios_en_texto(texto):
    # Une precios partidos en varias etiquetas: "129 ,95 €" -> "129,95 €"
    texto = re.sub(r"(\d)\s+([,.]\d)", r"\1\2", texto)
    encontrados = []
    for a, b in PRECIO_RE.findall(texto):
        v = numero(a or b)
        if v is not None:
            encontrados.append(v)
    return encontrados


def formato_euros(v, centimos=False):
    if centimos:
        v = v / 100
    return f"{v:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


# ---------------------------------------------------------------------------
# Descarga de páginas
# ---------------------------------------------------------------------------

def descargar(url):
    r = requests.get(url, headers=CABECERAS, timeout=30)
    return r.status_code, r.text


def descargar_con_navegador(url):
    """Abre la página en un Chrome invisible (para webs que cargan con JavaScript)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        nav = p.chromium.launch(headless=True)
        ctx = nav.new_context(
            user_agent=CABECERAS["User-Agent"],
            locale="es-ES",
            viewport={"width": 1366, "height": 900},
        )
        pagina = ctx.new_page()
        resp = pagina.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            pagina.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        # Bajar por la página para que carguen más productos
        for _ in range(8):
            pagina.mouse.wheel(0, 2500)
            pagina.wait_for_timeout(1200)
        html = pagina.content()
        estado = resp.status if resp else 0
        nav.close()
        return estado, html


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
        usados.add(id(tarjeta))

        enlace = tarjeta if tarjeta.name == "a" and tarjeta.get("href") else tarjeta.find("a", href=True)
        url = urljoin(base_url, enlace["href"]) if enlace else base_url

        nombre = ""
        for sel in ["[class*=name]", "[class*=title]", "[class*=Name]", "[class*=Title]",
                    "h2", "h3", "h4"]:
            n = tarjeta.select_one(sel)
            if n and _limpiar_nombre(n.get_text(" ", strip=True)):
                nombre = _limpiar_nombre(n.get_text(" ", strip=True))
                break
        if not nombre:
            img = tarjeta.find("img", alt=True)
            if img and img["alt"].strip():
                nombre = img["alt"].strip()[:90]
        if not nombre:
            nombre = _limpiar_nombre(tarjeta.get_text(" ", strip=True)) or "(sin nombre)"

        productos.append({
            "nombre": nombre,
            "url": url,
            "antes": max(precios),
            "ahora": min(precios),
        })
    return productos


# ---------------------------------------------------------------------------
# Tiendas Shopify (catálogo completo en /products.json)
# ---------------------------------------------------------------------------

def extraer_shopify(base, filtro=None, max_paginas=20):
    productos = []
    base = base.rstrip("/")
    for pagina in range(1, max_paginas + 1):
        r = requests.get(f"{base}/products.json", params={"limit": 250, "page": pagina},
                         headers=CABECERAS, timeout=30)
        if r.status_code != 200:
            print(f"    Shopify página {pagina}: HTTP {r.status_code}")
            break
        lista = r.json().get("products", [])
        if not lista:
            break
        for p in lista:
            texto = " ".join([p.get("title", ""), p.get("product_type", ""),
                              " ".join(p.get("tags", []) if isinstance(p.get("tags"), list)
                                       else [str(p.get("tags", ""))])]).lower()
            if filtro and filtro.lower() not in texto:
                continue
            for v in p.get("variants", []):
                antes = numero(v.get("compare_at_price") or "")
                ahora = numero(v.get("price") or "")
                if antes and ahora and antes > ahora:
                    productos.append({
                        "nombre": p.get("title", "(sin nombre)"),
                        "url": f"{base}/products/{p.get('handle', '')}",
                        "antes": antes,
                        "ahora": ahora,
                    })
                    break
    return productos


# ---------------------------------------------------------------------------
# Lógica principal
# ---------------------------------------------------------------------------

def descuento(p):
    return round((1 - p["ahora"] / p["antes"]) * 100)


def analizar_url(url, usar_navegador):
    if usar_navegador:
        estado, html = descargar_con_navegador(url)
    else:
        estado, html = descargar(url)
    if estado and estado >= 400:
        print(f"    HTTP {estado}: la web ha rechazado la visita (posible bloqueo).")
    soup = BeautifulSoup(html, "html.parser")
    productos = extraer_de_json(soup, url) + extraer_de_html(soup, url)
    # Quitar duplicados (mismo enlace o mismo nombre)
    unicos, claves = [], set()
    for p in productos:
        clave = (p["url"] if p["url"] != url else "") or p["nombre"].lower()
        if clave in claves:
            continue
        claves.add(clave)
        unicos.append(p)
    return unicos


def clave_de(tienda, p):
    base = p["url"] if p["url"] else p["nombre"]
    return hashlib.sha1(f"{tienda}|{base}|{p['nombre']}".encode()).hexdigest()[:16]


def cargar_vistos():
    try:
        with open(RUTA_VISTOS, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def guardar_vistos(vistos):
    limite = (dt.datetime.utcnow() - dt.timedelta(days=30)).isoformat()
    vistos = {k: v for k, v in vistos.items() if v.get("ultima_vez", "") >= limite}
    with open(RUTA_VISTOS, "w", encoding="utf-8") as f:
        json.dump(vistos, f, ensure_ascii=False, indent=1, sort_keys=True)


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


def main():
    accion = os.environ.get("ACCION", "normal").strip() or "normal"

    if accion == "averiguar_chat_id":
        averiguar_chat_id()
        sys.exit(0)

    if accion == "mensaje_de_prueba":
        ok = enviar_aviso("✅ Vigilante de descuentos: ¡funciona! A partir de ahora te avisaré aquí.")
        print("Mensaje de prueba enviado." if ok else "No se pudo enviar el mensaje de prueba.")
        sys.exit(0 if ok else 1)

    with open(RUTA_CONFIG, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    minimo = float(config.get("descuento_minimo", 60))
    max_avisos = int(config.get("max_avisos_por_ejecucion", 15))
    vistos = cargar_vistos()
    ahora_iso = dt.datetime.utcnow().isoformat()
    pendientes = []

    for tienda in config.get("tiendas", []):
        nombre_tienda = tienda.get("nombre", "Tienda")
        centimos = bool(tienda.get("precios_en_centimos", False))
        urls = [u for u in (tienda.get("urls") or []) if u and str(u).startswith("http")]
        shopify = tienda.get("shopify")
        if not urls and not shopify:
            print(f"\n== {nombre_tienda}: sin direcciones configuradas, se salta.")
            continue
        print(f"\n== {nombre_tienda}")

        productos = []
        if shopify:
            try:
                encontrados = extraer_shopify(shopify, tienda.get("filtro_shopify"))
                print(f"  {shopify} (Shopify) -> {len(encontrados)} artículos rebajados")
                productos += encontrados
            except Exception as e:
                print(f"  Error en Shopify {shopify}: {e}")
        for url in urls:
            try:
                encontrados = analizar_url(url, bool(tienda.get("navegador", False)))
                maximo = max((descuento(p) for p in encontrados), default=0)
                print(f"  {url}\n    -> {len(encontrados)} artículos rebajados leídos "
                      f"(máximo descuento visto: {maximo} %)")
                if not encontrados:
                    pista = ("pon 'navegador: true' en esta tienda"
                             if not tienda.get("navegador") else
                             "puede que la web bloquee las visitas automáticas")
                    print(f"    AVISO: no se ha leído ningún artículo. Prueba: {pista}.")
                productos += encontrados
            except Exception as e:
                print(f"  Error leyendo {url}: {e}")
            time.sleep(2)

        for p in productos:
            d = descuento(p)
            if d < minimo:
                continue
            k = clave_de(nombre_tienda, p)
            previo = vistos.get(k, {})
            ya_avisado = previo.get("avisado_precio")
            nuevo = ya_avisado is None or p["ahora"] < ya_avisado * 0.98
            vistos[k] = {
                "tienda": nombre_tienda,
                "nombre": p["nombre"],
                "precio": p["ahora"],
                "descuento": d,
                "avisado_precio": ya_avisado,
                "ultima_vez": ahora_iso,
            }
            if nuevo:
                pendientes.append((d, k, nombre_tienda, p, centimos))

    pendientes.sort(key=lambda x: -x[0])
    print(f"\nArtículos nuevos por encima del {minimo:.0f} %: {len(pendientes)}")

    a_enviar = pendientes[:max_avisos]
    lineas = []
    for d, k, tienda, p, cent in a_enviar:
        lineas.append(
            f"🔥 -{d}% · {tienda}\n{p['nombre']}\n"
            f"{formato_euros(p['antes'], cent)} → {formato_euros(p['ahora'], cent)}\n{p['url']}"
        )
    if len(pendientes) > max_avisos:
        lineas.append(f"…y {len(pendientes) - max_avisos} ofertas más. Te llegarán en el próximo aviso.")

    if not lineas:
        print("Nada nuevo que avisar.")
    elif accion == "prueba_sin_enviar":
        print("\n--- MODO PRUEBA: esto es lo que se enviaría ---\n")
        print("\n\n".join(lineas))
    else:
        todo_ok = True
        for bloque in trocear(lineas):
            if enviar_aviso(bloque):
                print("Aviso enviado.")
            else:
                todo_ok = False
            time.sleep(4)
        if todo_ok:
            for _, k, _, p, _ in a_enviar:
                vistos[k]["avisado_precio"] = p["ahora"]

    if accion != "prueba_sin_enviar":
        guardar_vistos(vistos)


if __name__ == "__main__":
    main()
