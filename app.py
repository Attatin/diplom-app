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

# --- 1. Конфигурация страницы ---
st.set_page_config(
    page_title="RegRisk Audit | Оценка регуляторных рисков",
    page_icon=":material/account_balance:",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. Математическая модель (Веса из методики) ---
# Это наши w_i из формулы R = Σ(W_i * r_i)
WEIGHTS = {
    "Наличие политики ПДн": 0.08,
    "Отдельное согласие": 0.08,
    "Cookie-баннер": 0.05,
    "Отдельный чек-бокс согласия": 0.10,
    "Минимизация данных": 0.06,
    "Отзыв согласия": 0.06,
    "Наличие в реестре РКН": 0.10,
    "Уведомление об инцидентах 24/72": 0.06,
    "Отсутствие WhatsApp (Meta)": 0.05,
    "Отсутствие Google Analytics (трансгранично)": 0.06,
    "Информация о ПОД/ФТ": 0.05,
    "Порядок обращений субъектов": 0.05,
    "Корректность формулировок": 0.05,
    "Сроки хранения": 0.05,
    "Оценка вреда": 0.05,
    "Локализация БД": 0.05
}

# --- 3. Подключение к GigaChat ---
@st.cache_resource
def get_gigachat():
    try:
        key = st.secrets["GIGACHAT_KEY"]
    except KeyError:
        st.error("Ошибка конфигурации: Ключ GIGACHAT_KEY не найден в Secrets.")
        st.stop()
    return GigaChat(
        credentials=key,
        scope="GIGACHAT_API_PERS",
        model="GigaChat-2",
        verify_ssl_certs=False
    )

giga = get_gigachat()

# --- 4. Функции сбора данных ---
def download_policy_text(url):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        response = requests.get(url, headers=headers, timeout=20, verify=False)
        response.raise_for_status()
    except Exception as e:
        return None, None, f"Ошибка подключения: {e}"

    soup = BeautifulSoup(response.text, "html.parser")
    html_lower = response.text.lower()
    
    # Поиск технических маркеров (как у научрука)
    tech_markers = {
        "google_analytics": "google-analytics" in html_lower or "_ga" in html_lower,
        "yandex_metrika": "mc.yandex.ru" in html_lower or "_ym_" in html_lower,
        "whatsapp": "wa.me" in html_lower or "whatsapp" in html_lower
    }

    # Поиск ссылки на политику
    policy_link = None
    for link in soup.find_all("a"):
        href = link.get("href", "")
        text = link.get_text().lower()
        if any(w in text for w in ["политик", "персональн", "согласи", "обработк"]):
            if href and not href.startswith("#"):
                policy_link = href
                break

    if not policy_link:
        return None, tech_markers, "Ссылка на политику не обнаружена (Нарушение ст. 18.1 152-ФЗ)"

    full_url = policy_link if policy_link.startswith("http") else url.rstrip("/") + (policy_link if policy_link.startswith("/") else "/" + policy_link)

    try:
        r = requests.get(full_url, headers=headers, timeout=20, verify=False)
        r.raise_for_status()
    except Exception as e:
        return None, tech_markers, f"Ошибка скачивания документа: {e}"

    # Извлечение текста (PDF или HTML)
    if "pdf" in r.headers.get("Content-Type", "").lower() or full_url.lower().endswith(".pdf"):
        try:
            with pdfplumber.open(io.BytesIO(r.content)) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        except Exception as e:
            return None, tech_markers, f"Ошибка чтения PDF: {e}"
    else:
        soup2 = BeautifulSoup(r.text, "html.parser")
        text = soup2.get_text(separator="\n", strip=True)

    return text, tech_markers, full_url

# --- 5. Нейросетевой анализ (Строгий юрист) ---
def analyze_with_gigachat(text, tech_markers):
    text_short = text[:15000] if text else "Текст политики отсутствует."
    
    prompt = f"""
Ты — ведущий аудитор по защите персональных данных (152-ФЗ). Составь официальное заключение.

ТЕКСТ ПОЛИТИКИ:
---
{text_short}
---

ТЕХНИЧЕСКИЕ ДАННЫЕ (сканирование сайта):
- Google Analytics: {"Обнаружен" if tech_markers['google_analytics'] else "Не обнаружен"}
- Яндекс.Метрика: {"Обнаружен" if tech_markers['yandex_metrika'] else "Не обнаружен"}
- Ссылки WhatsApp (Meta): {"Обнаружены" if tech_markers['whatsapp'] else "Не обнаружены"}

ЗАДАЧА: Проверь каждый критерий. Если требование нарушено — опиши его строго по шаблону.

Ответь СТРОГО в формате JSON:
{{
  "criteria_results": {{
    "Наличие политики ПДн": true/false (true = есть нарушение),
    "Отдельное согласие": true/false,
    "Cookie-баннер": true/false,
    "Отдельный чек-бокс согласия": true/false,
    "Минимизация данных": true/false,
    "Отзыв согласия": true/false,
    "Наличие в реестре РКН": true/false,
    "Уведомление об инцидентах 24/72": true/false,
    "Отсутствие WhatsApp (Meta)": true/false,
    "Отсутствие Google Analytics (трансгранично)": true/false,
    "Информация о ПОД/ФТ": true/false,
    "Порядок обращений субъектов": true/false,
    "Корректность формулировок": true/false,
    "Сроки хранения": true/false,
    "Оценка вреда": true/false,
    "Локализация БД": true/false
  }},
  "findings": [
    {{
      "title": "Название нарушения",
      "law": "Статья 152-ФЗ / КоАП",
      "fine": "Размер штрафа",
      "description": "Подробное описание: почему нарушено и чем грозит."
    }}
  ],
  "recommendations": [
    "Конкретное действие 1",
    "Конкретное действие 2"
  ]
}}

ПРАВИЛА:
1. Если в технических данных есть Google Analytics, а в политике про него нет — ставь true для "Отсутствие Google Analytics (трансгранично)".
2. Если есть WhatsApp — ставь true для "Отсутствие WhatsApp (Meta)".
3. Пиши строго, как юрист (без воды).
"""

    try:
        response = giga.chat(prompt)
        content = response.choices[0].message.content
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        return None
    except Exception as e:
        st.error(f"Ошибка аналитического модуля: {e}")
        return None

# --- 6. Математический расчет риска ---
def calculate_risk(criteria_results):
    risk = 0.0
    total_weight = sum(WEIGHTS.values())
    
    for criterion, weight in WEIGHTS.items():
        # Если критерий нарушен (True), то риск = 1 (полный вклад)
        # Если не нарушен (False), то риск = 0
        is_violated = criteria_results.get(criterion, False)
        if is_violated:
            risk += weight * 1.0
            
    # Нормализация (на случай если сумма весов не равна 1)
    normalized_risk = risk / total_weight if total_weight > 0 else 0
    return round(normalized_risk, 2)

def get_risk_level(risk):
    if risk >= 0.75: return "Критический", "error"
    if risk >= 0.50: return "Высокий", "warning"
    if risk >= 0.25: return "Умеренный", "info"
    return "Допустимый", "success"

# --- 7. ИНТЕРФЕЙС ---

# Сайдбар
with st.sidebar:
    st.markdown("### :material/account_balance: RegRisk Audit")
    st.caption("Платформа оценки регуляторных рисков")
    st.divider()
    
    url_input = st.text_input("URL-адрес веб-ресурса", placeholder="https://example.ru")
    start_audit = st.button("Инициировать аудит", type="primary", use_container_width=True)
    
    st.divider()
    st.markdown("**Методология:**")
    st.caption("Оценка базируется на 152-ФЗ, 115-ФЗ и КоАП РФ. Расчет интегрального риска производится по формуле взвешенной суммы.")

# Основная область
if not start_audit:
    st.title("Система аудита регуляторных рисков")
    st.markdown("""
    Добро пожаловать в систему автоматизированной оценки соответствия веб-ресурсов требованиям Роскомнадзора и Росфинмониторинга.
    
    **Для начала работы:**
    1. Введите URL-адрес сайта в левой панели.
    2. Нажмите «Инициировать аудит».
    3. Ознакомьтесь с математическим расчетом и детальным заключением.
    """)
    st.info("Пример URL для тестирования: https://kubyshka-zaim.ru")
    
elif start_audit and not url_input:
    st.error("Необходимо указать URL-адрес для проведения проверки.")
    
else:
    with st.spinner("Сбор данных и анализ HTML-структуры..."):
        text, tech_markers, source = download_policy_text(url_input)

    if text is None and not tech_markers:
        st.error(f"Критическая ошибка: {source}")
    else:
        with st.spinner("Формирование юридического заключения..."):
            ai_result = analyze_with_gigachat(text, tech_markers)

        if ai_result:
            # Считаем риск по формуле Python, а не отдаем на откуп ИИ
            final_risk = calculate_risk(ai_result.get("criteria_results", {}))
            level_text, level_ui = get_risk_level(final_risk)
            
            # Заголовок отчета
            st.title("Отчет об аудите информационной безопасности")
            st.caption(f"Объект аудита: {url_input} | Источник документа: {source}")
            st.divider()

            # Вкладки
            tab1, tab2, tab3 = st.tabs(["📊 Сводка и Риск", "🧮 Математическая модель", "📑 Детальное заключение"])

            # --- ВКЛАДКА 1: СВОДКА ---
            with tab1:
                col1, col2, col3 = st.columns(3, border=True)
                with col1:
                    st.metric("Интегральный риск", f"{final_risk:.2f}")
                with col2:
                    if level_ui == "error": st.error(f"**{level_text}**")
                    elif level_ui == "warning": st.warning(f"**{level_text}**")
                    elif level_ui == "info": st.info(f"**{level_text}**")
                    else: st.success(f"**{level_text}**")
                with col3:
                    st.metric("Выявлено нарушений", len(ai_result.get("findings", [])))
                
                st.divider()
                
                # График (Радар)
                st.subheader("Профиль риска по категориям")
                
                # Группируем критерии для графика
                categories = {
                    "Документарные": ["Наличие политики ПДн", "Отдельное согласие", "Корректность формулировок"],
                    "Функциональные": ["Отдельный чек-бокс согласия", "Минимизация данных", "Отзыв согласия"],
                    "Технические": ["Cookie-баннер", "Отсутствие Google Analytics (трансгранично)", "Отсутствие WhatsApp (Meta)"],
                    "Процедурные": ["Наличие в реестре РКН", "Уведомление об инцидентах 24/72", "Порядок обращений субъектов"]
                }
                
                fig = go.Figure()
                for cat_name, crit_list in categories.items():
                    # Считаем средний риск в категории
                    cat_risk = sum([WEIGHTS.get(c, 0) for c in crit_list if ai_result["criteria_results"].get(c, False)])
                    fig.add_trace(go.Scatterpolar(
                        r=[cat_risk], theta=[cat_name], fill='toself', name=cat_name
                    ))
                
                fig.update_layout(
                    polar=dict(radialaxis=dict(visible=True, range=[0, 0.3])),
                    showlegend=False, margin=dict(t=30, b=30, l=30, r=30)
                )
                st.plotly_chart(fig, use_container_width=True)

            # --- ВКЛАДКА 2: МАТЕМАТИКА ---
            with tab2:
                st.subheader("Формализованная модель расчета риска")
                st.latex(r"R = \sum_{i=1}^{n} (W_i \times r_i)")
                st.markdown("Где **W_i** — весовой коэффициент критерия (из методики), **r_i** — бинарная оценка (1 = нарушение есть, 0 = нарушения нет).")
                st.divider()
                
                # Таблица расчета
                data = []
                for crit, weight in WEIGHTS.items():
                    is_viol = ai_result["criteria_results"].get(crit, False)
                    contribution = weight if is_viol else 0.0
                    data.append({
                        "Критерий": crit,
                        "Вес (W_i)": weight,
                        "Оценка (r_i)": 1 if is_viol else 0,
                        "Вклад в риск (W_i * r_i)": contribution
                    })
                
                df = pd.DataFrame(data)
                st.dataframe(df, use_container_width=True, hide_index=True)
                st.info(f"**Итоговый интегральный риск (R): {final_risk}** (Сумма вкладов / Сумма весов)")

            # --- ВКЛАДКА 3: ЗАКЛЮЧЕНИЕ ---
            with tab3:
                st.subheader("Детальное юридическое заключение")
                
                for idx, finding in enumerate(ai_result.get("findings", []), 1):
                    with st.expander(f"{idx}. {finding.get('title')}", expanded=True):
                        st.markdown(f"**Правовое обоснование:** `{finding.get('law')}`")
                        st.markdown(f"**Ответственность:** :red[**{finding.get('fine')}**]")
                        st.markdown(f"**Описание:** {finding.get('description')}")
                
                st.divider()
                st.subheader("Рекомендации по устранению")
                for rec in ai_result.get("recommendations", []):
                    st.markdown(f"- {rec}")