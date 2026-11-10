import streamlit as st
import requests
from bs4 import BeautifulSoup
import pdfplumber
import io
import re
import json
import pandas as pd
import plotly.graph_objects as go
from gigachat import GigaChat
import os

st.set_page_config(page_title="RegRisk Audit", page_icon=":material/account_balance:", layout="wide")

# --- РАСШИРЕННАЯ БАЗА ЗНАНИЙ ---
LAW_BASE = """
[152-ФЗ Статья 6. Условия обработки]
3. Оператор вправе поручить обработку персональных данных другому лицу с согласия субъекта... на основании договора (поручение оператора).

[152-ФЗ Статья 9. Согласие]
1. Согласие должно быть конкретным, предметным, информированным, сознательным и однозначным.
2. Согласие оформляется отдельно от иных документов.

[152-ФЗ Статья 12. Трансграничная передача]
1. До начала осуществления трансграничной передачи оператор обязан уведомить Роскомнадзор.

[152-ФЗ Статья 18.1. Меры по обеспечению]
2. Оператор, осуществляющий сбор ПДн через Интернет, обязан опубликовать политику.

[152-ФЗ Статья 21. Устранение нарушений]
3.1. Уведомление РКН об инцидентах: 24 часа (о факте), 72 часа (о результатах).

[149-ФЗ Статья 10.2-1. Рекомендательные технологии]
1. Владелец сайта обязан разместить правила применения рекомендательных технологий.

[149-ФЗ Статья 16. Защита информации]
1. Защита информации представляет собой принятие правовых, организационных и технических мер...

[38-ФЗ Статья 18. Реклама по сетям электросвязи]
1. Распространение рекламы по сетям электросвязи допускается только при предварительном согласии абонента.
"""

# --- ОБНОВЛЕННЫЕ КРИТЕРИИ ---
WEIGHTS = {
    "Наличие отдельного согласия": 0.10,
    "Отдельный чек-бокс согласия": 0.10,
    "Отсутствие презумпции согласия": 0.08,
    "Cookie-баннер и согласие": 0.06,
    "Минимизация данных": 0.06,
    "Отзыв согласия (любая форма)": 0.06,
    "Наличие в реестре РКН": 0.06,
    "Уведомление об инцидентах 24/72": 0.06,
    "Отсутствие WhatsApp (Meta)": 0.04,
    "Отсутствие Google Analytics": 0.04,
    "Информация о ПОД/ФТ": 0.04,
    "Порядок обращений субъектов": 0.04,
    "Сроки хранения (конкретные)": 0.04,
    "Оценка вреда": 0.04,
    "Локализация БД": 0.04,
    "Контакты ответственного": 0.04,
    "Договор с хостингом (поручение)": 0.04,      # НОВЫЙ
    "Правила рекомендаций": 0.04,                 # НОВЫЙ
    "Согласие работников на ФИО": 0.04,           # НОВЫЙ
    "Отдельное согласие на рекламу": 0.02         # НОВЫЙ
}

@st.cache_resource
def get_gigachat():
    key = os.environ.get("GIGACHAT_KEY") or st.secrets.get("GIGACHAT_KEY")
    if not key:
        st.error("Ключ GIGACHAT_KEY не найден.")
        st.stop()
    return GigaChat(credentials=key, scope="GIGACHAT_API_PERS", model="GigaChat-2", verify_ssl_certs=False)

giga = get_gigachat()

def download_policy_text(url):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        response = requests.get(url, headers=headers, timeout=20, verify=False)
        response.raise_for_status()
    except Exception as e:
        return None, None, f"Ошибка: {e}"

    soup = BeautifulSoup(response.text, "html.parser")
    html_lower = response.text.lower()
    
    tech_markers = {
        "google_analytics": "google-analytics" in html_lower or "_ga" in html_lower,
        "yandex_metrika": "mc.yandex.ru" in html_lower or "_ym_" in html_lower,
        "whatsapp": "wa.me" in html_lower or "whatsapp" in html_lower,
        "hosting": "хостинг" in html_lower or "hosting" in html_lower, # Ищем упоминание хостинга
        "recommendations": "избранное" in html_lower or "favorites" in html_lower, # Ищем рекомендации
        "employees": "контакты" in html_lower or "о компании" in html_lower # Ищем страницы с сотрудниками
    }

    policy_link = None
    for link in soup.find_all("a"):
        href = link.get("href", "")
        text = link.get_text().lower()
        if any(w in text for w in ["политик", "персональн", "согласи", "обработк"]):
            if href and not href.startswith("#"):
                policy_link = href
                break

    if not policy_link:
        return None, tech_markers, "Ссылка на политику не найдена"

    full_url = policy_link if policy_link.startswith("http") else url.rstrip("/") + (policy_link if policy_link.startswith("/") else "/" + policy_link)

    try:
        r = requests.get(full_url, headers=headers, timeout=20, verify=False)
        r.raise_for_status()
    except Exception as e:
        return None, tech_markers, f"Ошибка: {e}"

    if "pdf" in r.headers.get("Content-Type", "").lower() or full_url.lower().endswith(".pdf"):
        try:
            with pdfplumber.open(io.BytesIO(r.content)) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        except Exception as e:
            return None, tech_markers, f"Ошибка PDF: {e}"
    else:
        soup2 = BeautifulSoup(r.text, "html.parser")
        text = soup2.get_text(separator="\n", strip=True)

    return text, tech_markers, full_url

def analyze_with_gigachat(text, tech_markers):
    text_short = text[:12000] if text else "Текст отсутствует."
    
    prompt = f"""
Ты — строгий аудитор по защите персональных данных. Составь юридическое заключение.
Используй ТОЛЬКО предоставленную базу знаний (выдержки из ФЗ).

БАЗА ЗНАНИЙ:
{LAW_BASE}

ТЕКСТ ПОЛИТИКИ:
---
{text_short}
---

ТЕХНИЧЕСКИЕ ДАННЫЕ:
- Google Analytics: {"Есть" if tech_markers['google_analytics'] else "Нет"}
- WhatsApp: {"Есть" if tech_markers['whatsapp'] else "Нет"}
- Хостинг: {"Упоминается" if tech_markers['hosting'] else "Не найден"}
- Рекомендации (Избранное): {"Есть" if tech_markers['recommendations'] else "Нет"}

ПРОВЕРЬ КРИТЕРИИ (1 = нарушение есть, 0 = нет):
1. "Наличие отдельного согласия"
2. "Отдельный чек-бокс согласия"
3. "Отсутствие презумпции согласия" (фразы "использование означает согласие" = 1)
4. "Cookie-баннер и согласие"
5. "Минимизация данных"
6. "Отзыв согласия (любая форма)" ("только по почте" = 1)
7. "Наличие в реестре РКН"
8. "Уведомление об инцидентах 24/72"
9. "Отсутствие WhatsApp (Meta)"
10. "Отсутствие Google Analytics" (трансграничная передача)
11. "Информация о ПОД/ФТ" (115-ФЗ)
12. "Порядок обращений субъектов"
13. "Сроки хранения (конкретные)"
14. "Оценка вреда"
15. "Локализация БД"
16. "Контакты ответственного"
17. "Договор с хостингом (поручение)" (если в политике нет упоминания о поручении хостингу = 1)
18. "Правила рекомендаций" (если есть "Избранное", но нет правил = 1)
19. "Согласие работников на ФИО" (если на сайте есть ФИО сотрудников, а в политике нет упоминания = 1)
20. "Отдельное согласие на рекламу" (если есть рассылки, но нет отдельного согласия = 1)

Ответь СТРОГО в формате JSON:
{{
  "criteria_results": {{
    "Название критерия": 1 или 0
  }},
  "findings": [
    {{
      "title": "Название нарушения",
      "law": "Точная цитата из Базы Знаний",
      "fine": "Штраф",
      "description": "Обоснование"
    }}
  ],
  "recommendations": ["Рекомендация 1", "Рекомендация 2"]
}}
"""

    try:
        response = giga.chat(prompt)
        content = response.choices[0].message.content
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        return None
    except Exception as e:
        st.error(f"Ошибка ИИ: {e}")
        return None

def calculate_risk(criteria_results):
    risk = 0.0
    total_weight = sum(WEIGHTS.values())
    for criterion, weight in WEIGHTS.items():
        if criteria_results.get(criterion, 0) == 1:
            risk += weight
    return round(risk / total_weight, 2) if total_weight > 0 else 0

def get_risk_level(risk):
    if risk >= 0.75: return "Критический", "error"
    if risk >= 0.50: return "Высокий", "warning"
    if risk >= 0.25: return "Умеренный", "info"
    return "Допустимый", "success"

# --- ИНТЕРФЕЙС ---
with st.sidebar:
    st.markdown("### :material/account_balance: RegRisk Audit")
    url_input = st.text_input("URL-адрес веб-ресурса", placeholder="https://example.ru")
    start_audit = st.button("Инициировать аудит", type="primary", use_container_width=True)

if start_audit and url_input:
    with st.spinner("Сбор данных..."):
        text, tech_markers, source = download_policy_text(url_input)

    if text is None and not tech_markers:
        st.error(f"Ошибка: {source}")
    else:
        with st.spinner("Формирование заключения..."):
            ai_result = analyze_with_gigachat(text, tech_markers)

        if ai_result:
            final_risk = calculate_risk(ai_result.get("criteria_results", {}))
            level_text, level_ui = get_risk_level(final_risk)
            
            st.title("Отчет об аудите")
            st.caption(f"Объект: {url_input}")
            
            tab1, tab2, tab3 = st.tabs(["📊 Сводка", "🧮 Математика", "📑 Заключение"])

            with tab1:
                col1, col2, col3 = st.columns(3, border=True)
                with col1: st.metric("Интегральный риск", f"{final_risk:.2f}")
                with col2:
                    if level_ui == "error": st.error(f"**{level_text}**")
                    elif level_ui == "warning": st.warning(f"**{level_text}**")
                    elif level_ui == "info": st.info(f"**{level_text}**")
                    else: st.success(f"**{level_text}**")
                with col3: st.metric("Нарушений", len(ai_result.get("findings", [])))

            with tab2:
                st.subheader("Расчет риска")
                st.latex(r"R = \frac{\sum (W_i \times r_i)}{\sum W_i}")
                data = []
                for crit, weight in WEIGHTS.items():
                    is_viol = ai_result["criteria_results"].get(crit, 0)
                    val = 1 if (is_viol == 1 or is_viol is True) else 0
                    data.append({"Критерий": crit, "Вес": weight, "Нарушено": val, "Вклад": weight if val == 1 else 0})
                st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)
                st.info(f"**Итоговый риск: {final_risk}**")

            with tab3:
                st.subheader("Юридическое заключение")
                for idx, finding in enumerate(ai_result.get("findings", []), 1):
                    with st.expander(f"{idx}. {finding.get('title')}", expanded=True):
                        st.markdown(f"**Правовое обоснование:** \n> {finding.get('law')}")
                        st.markdown(f"**Ответственность:** :red[**{finding.get('fine')}**]")
                        st.markdown(f"**Описание:** {finding.get('description')}")
                st.divider()
                st.subheader("Рекомендации")
                for rec in ai_result.get("recommendations", []):
                    st.markdown(f"- {rec}")
elif start_audit and not url_input:
    st.error("Введите URL")
else:
    st.title("Система аудита регуляторных рисков")
