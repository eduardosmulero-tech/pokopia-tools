"""Deteccion de idioma por script y palabras funcionales, sin dependencias.

Suficiente para lo que hace falta aqui: distinguir es/en/de/fr/it/jp/kr/zh-CN/
zh-TW en textos de tablas del juego, y **poder enseñar la cuenta** de por que
sale cada veredicto (muestras, aciertos por idioma, margen sobre el segundo).

Nada de modelos ni de paquetes externos: reglas medibles y reproducibles.
"""

from __future__ import annotations

import re
import unicodedata

#: Palabras funcionales por idioma. Listas cortas a proposito: suman senal y se
#: pueden auditar a ojo. Se comparan en minusculas y sin signos.
PARADAS: dict[str, set[str]] = {
    "es": {"el", "la", "los", "las", "un", "una", "de", "del", "que", "y", "en",
           "es", "no", "se", "lo", "con", "por", "para", "muy", "pero", "como",
           "mas", "si", "tu", "mi", "te", "al", "su", "ya", "aqui", "esto",
           "esta", "este", "bien", "todo", "hay", "ser", "tiene", "me", "nos"},
    "en": {"the", "and", "you", "to", "of", "is", "it", "that", "in", "with",
           "for", "have", "what", "this", "are", "was", "not", "on", "be",
           "your", "my", "me", "we", "so", "there", "here", "just", "can",
           "will", "well", "do", "but", "at", "as"},
    "de": {"der", "die", "das", "und", "ich", "nicht", "ist", "du", "wir", "ein",
           "eine", "mit", "auf", "sehr", "hier", "was", "wie", "auch", "aber",
           "dich", "mir", "mich", "denn", "noch", "schon", "mal", "doch", "zu",
           "es", "sie", "er", "haben", "bin", "bist", "war", "dem", "den"},
    "fr": {"le", "la", "les", "de", "et", "est", "un", "une", "que", "pour",
           "dans", "avec", "pas", "vous", "je", "des", "du", "au", "ce", "sur",
           "qui", "mais", "bien", "tres", "mon", "ton", "nous", "ils", "elle"},
    "it": {"il", "la", "che", "di", "e", "un", "una", "per", "con", "non",
           "sono", "questo", "molto", "perche", "dei", "delle", "anche", "come",
           "cosa", "mio", "mia", "tuo", "noi", "ma", "piu", "qui", "bene"},
}

#: Letras con diacritico que apuntan a un idioma (senal secundaria, vale menos).
DIACRITICOS: dict[str, str] = {
    "es": "ñ¿¡",
    "de": "äöüß",
    "fr": "èêàçùœ",
    "it": "ìòàù",
}

#: Pares simplificado/tradicional para separar zh-CN de zh-TW. Solo caracteres
#: que **solo** existen en una de las dos variantes (los compartidos no suman).
SIMPLIFICADO = set(
    "这们说个国东车门时间对开长为发后里还会没现实电脑见样觉让从来过给与无"
    "关系听问学爱买卖话语读写认识谁谢请应该么几万亿义乐书习云亚产亲仅优传"
    "伤众儿党内军农决况净减凤刘则刚创别动务劳势勋医华协单卫厂层岁师帅带帮"
    "广庆应张归当录彻径忆怀总恶惊惯愿战户执扩扫扬护报担拟拥择挂挤挥损换据"
    "检验楼欢欧残毕气汉汤沟没测济浑浓涂润涨渐温湾满滨滚灭灯灵炉烂热爱爷牵"
    "犹独狮猎献玛环现疗盐监盘确础礼祸离种积称稳穷窃竞笔筑简类紧纠红级纪纯"
    "纳纵纷纸线练组织细终绍经结绕绘给络统继绩续维综绿缓编缘缩网罗罚联职聪"
    "肃胜脉脏脑脸腾舍舰艺节芦苍苏荐荡药莱获营蒋虽蚕蛮补装观规视览觉誉计订"
    "认讨让训议讯记讲讳讶许论讼讽设访证评识诉诊词译试诗诚话诞询该详语误说"
    "请诸读课谁调谈谊谋谓谜谢谣谦谨谱贝负贡财责贤败账货质贩贪贫购贯贴贵贷"
    "贸费贺贼资赋赌赏赐赔赚赛赞赠赢赵赶趋趣跃践踪轨轩转轮软轰轻载较辅辆辈"
    "辉辑输辞边达迁运还进远违连迟迹适选逊递逻遗邓邮郑酱释鉴针钉钓钟钢钥钦"
    "钱铁铃铅铜银铺链销锁锅错锻锋锐锦键镇镜长门闪闭问闯闲间闻阀阁阅阐阔队"
    "阳阴阵阶际陆陈陕险随隐雾静韦韩页顶项顺须顽顾顿预领颇颈频颗题颜额风飞"
    "饭饮饰饱饲饶饼馆驰驱驳驻驾骂验骑骗骚骤鱼鲁鲜鸟鸡鸣鸭鹅鹰麦黄齐齿龄龙")
TRADICIONAL = set(
    "這們說個國東車門時間對開長為發後裡還會沒現實電腦見樣覺讓從來過給與無"
    "關係聽問學愛買賣話語讀寫認識誰謝請應該麼幾萬億義樂書習雲亞產親僅優傳"
    "傷眾兒黨內軍農決況淨減鳳劉則剛創別動務勞勢勳醫華協單衛廠層歲師帥帶幫"
    "廣慶應張歸當錄徹徑憶懷總惡驚慣願戰戶執擴掃揚護報擔擬擁擇掛擠揮損換據"
    "檢驗樓歡歐殘畢氣漢湯溝沒測濟渾濃塗潤漲漸溫灣滿濱滾滅燈靈爐爛熱愛爺牽"
    "猶獨獅獵獻瑪環現療鹽監盤確礎禮禍離種積稱穩窮竊競筆築簡類緊糾紅級紀純"
    "納縱紛紙線練組織細終紹經結繞繪給絡統繼績續維綜綠緩編緣縮網羅罰聯職聰"
    "肅勝脈臟腦臉騰捨艦藝節蘆蒼蘇薦蕩藥萊獲營蔣雖蠶蠻補裝觀規視覽覺譽計訂"
    "認討讓訓議訊記講諱訝許論訟諷設訪證評識訴診詞譯試詩誠話誕詢該詳語誤說"
    "請諸讀課誰調談誼謀謂謎謝謠謙謹譜貝負貢財責賢敗賬貨質販貪貧購貫貼貴貸"
    "貿費賀賊資賦賭賞賜賠賺賽贊贈贏趙趕趨趣躍踐蹤軌軒轉輪軟轟輕載較輔輛輩"
    "輝輯輸辭邊達遷運還進遠違連遲跡適選遜遞邏遺鄧郵鄭醬釋鑑針釘釣鐘鋼鑰欽"
    "錢鐵鈴鉛銅銀鋪鏈銷鎖鍋錯鍛鋒銳錦鍵鎮鏡長門閃閉問闖閒間聞閥閣閱闡闊隊"
    "陽陰陣階際陸陳陝險隨隱霧靜韋韓頁頂項順須頑顧頓預領頗頸頻顆題顏額風飛"
    "飯飲飾飽飼饒餅館馳驅駁駐駕罵驗騎騙騷驟魚魯鮮鳥雞鳴鴨鵝鷹麥黃齊齒齡龍")
#: Kana (hiragana + katakana) y hangul.
KANA = ((0x3040, 0x30FF), (0x31F0, 0x31FF))
HANGUL = ((0xAC00, 0xD7AF), (0x1100, 0x11FF), (0x3130, 0x318F))
HAN = ((0x4E00, 0x9FFF), (0x3400, 0x4DBF))

_TOKEN = re.compile(r"[^\W\d_]+", re.UNICODE)


def _en_rangos(ch: str, rangos) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in rangos)


def _limpia(texto: str) -> str:
    """Fuera el marcado del juego: `<...>` no es texto del idioma."""
    limpio = re.sub(r"<[^<>]*>", " ", texto)
    limpio = unicodedata.normalize("NFC", limpio)
    return limpio


def perfil(texto: str) -> dict:
    """Cuenta de script y de palabras funcionales de un texto."""
    limpio = _limpia(texto)
    letras = [ch for ch in limpio if ch.isalpha()]
    total = len(letras) or 1
    cuenta = {"kana": 0, "hangul": 0, "han": 0, "latin": 0,
              "simplificado": 0, "tradicional": 0}
    for ch in letras:
        if _en_rangos(ch, KANA):
            cuenta["kana"] += 1
        elif _en_rangos(ch, HANGUL):
            cuenta["hangul"] += 1
        elif _en_rangos(ch, HAN):
            cuenta["han"] += 1
            if ch in TRADICIONAL:
                cuenta["tradicional"] += 1
            if ch in SIMPLIFICADO:
                cuenta["simplificado"] += 1
        else:
            cuenta["latin"] += 1
    palabras = [p.lower() for p in _TOKEN.findall(limpio)]
    aciertos = {idi: sum(1 for p in palabras if p in paradas)
                for idi, paradas in PARADAS.items()}
    diacriticos = {idi: sum(1 for ch in limpio if ch in DIACRITICOS.get(idi, ""))
                   for idi in PARADAS}
    return {"letras": total, "cuenta": cuenta, "palabras": len(palabras),
            "aciertos": aciertos, "diacriticos": diacriticos}


def detectar(texto: str) -> dict:
    """Idioma mas probable con su puntuacion y el margen sobre el segundo.

    Devuelve `{"idioma", "puntos", "segundo", "margen", "perfil"}`. Las reglas
    de script manda; las palabras funcionales solo deciden entre lenguas
    latinas.
    """
    p = perfil(texto)
    letras = p["letras"]
    c = p["cuenta"]
    if letras >= 20:
        frac_kana = c["kana"] / letras
        frac_hangul = c["hangul"] / letras
        frac_han = c["han"] / letras
        if frac_hangul >= 0.30:
            return {"idioma": "kr", "puntos": round(frac_hangul, 3), "segundo": None,
                    "margen": round(frac_hangul - max(frac_kana, frac_han), 3), "perfil": p}
        if frac_kana >= 0.10:
            return {"idioma": "jp", "puntos": round(frac_kana, 3), "segundo": None,
                    "margen": round(frac_kana - frac_hangul, 3), "perfil": p}
        if frac_han >= 0.30:
            sim, tra = c["simplificado"], c["tradicional"]
            idioma = "zh-TW" if tra > sim else "zh-CN"
            return {"idioma": idioma, "puntos": round(frac_han, 3), "segundo": None,
                    "margen": round(abs(tra - sim) / max(1, tra + sim), 3), "perfil": p}
    # lenguas latinas: palabras funcionales sobre el total de palabras + diacriticos
    palabras = max(1, p["palabras"])
    puntos = {}
    for idi in PARADAS:
        puntos[idi] = 100.0 * p["aciertos"][idi] / palabras + 0.5 * p["diacriticos"][idi]
    orden = sorted(puntos.items(), key=lambda kv: -kv[1])
    primero, segundo = orden[0], orden[1]
    return {"idioma": primero[0], "puntos": round(primero[1], 1),
            "segundo": {segundo[0]: round(segundo[1], 1)},
            "margen": round(primero[1] - segundo[1], 1), "perfil": p}


def consenso(veredictos: list[dict]) -> dict:
    """Idioma mayoritario de una lista de veredictos y cuantos lo apoyan."""
    cuenta: dict[str, int] = {}
    for v in veredictos:
        cuenta[v["idioma"]] = cuenta.get(v["idioma"], 0) + 1
    idioma = max(cuenta.items(), key=lambda kv: kv[1])[0]
    return {"idioma": idioma, "votos": cuenta[idioma], "total": len(veredictos),
            "reparto": dict(sorted(cuenta.items(), key=lambda kv: -kv[1]))}
