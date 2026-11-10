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
from urllib.parse import urljoin

st.set_page_config(page_title="RegRisk Audit", page_icon=":material/account_balance:", layout="wide")

LAW_DATABASE = {
    "Наличие отдельного согласия": {"law": "Ст. 9 152-ФЗ: Согласие оформляется отдельно от иных документов.", "fine": "до 300 000 руб. (ч. 1 ст. 13.11 КоАП)"},
    "Отдельный чек-бокс согласия": {"law": "Ст. 9 152-ФЗ: Согласие должно быть конкретным и однозначным.", "fine": "до 300 000 руб. (ч. 1 ст. 13.11 КоАП)"},
    "Отсутствие презумпции согласия": {"law": "Ст. 9 152-ФЗ: Молчание или бездействие не является согласием.", "fine": "до 300 000 руб. (ч. 1 ст. 13.11 КоАП)"},
    "Cookie-баннер и согласие": {"law": "Ст. 9 152-ФЗ: Использование cookie требует предварительного согласия.", "fine": "до 300 000 руб. (ч. 1 ст. 13.11 КоАП)"},
    "Минимизация данных": {"law": "Ст. 5 ч. 5 152-ФЗ: Данные не должны быть избыточными.", "fine": "до 300 000 руб. (ч. 1 ст. 13.11 КоАП)"},
    "Отзыв согласия (любая форма)": {"law": "Ст. 9 152-ФЗ: Согласие может быть отозвано в любой момент.", "fine": "до 300 000 руб. (ч. 1 ст. 13.11 КоАП)"},
    "Наличие в реестре РКН": {"law": "Ст. 22 152-ФЗ: Оператор обязан уведомить РКН.", "fine": "до 300 000 руб. (ст. 13.11 КоАП)"},
    "Уведомление об инцидентах 24/72": {"law": "Ст. 21 ч. 3.1 152-ФЗ: Уведомление РКН об инцидентах (24 и 72 часа).", "fine": "до 3 000 000 руб. (ч. 8 ст. 13.11 КоАП)"},
    "Отсутствие WhatsApp (Meta)": {"law": "Ст. 10.2-1 149-ФЗ / Закон о рекламе", "fine": "до 1 000 000 руб. (ст. 13.15 КоАП)"},
    "Отсутствие Google Analytics": {"law": "Ст. 12 152-ФЗ: До начала трансграничной передачи нужно уведомить РКН.", "fine": "до 300 000 руб. (ст. 13.11 КоАП)"},
    "Информация о ПОД/ФТ": {"law": "Ст. 7 115-ФЗ: Обязанность идентификации клиентов.", "fine": "до 1 000 000 руб. (ст. 15.27 КоАП)"},
    "Порядок обращений субъектов": {"law": "Ст. 20 152-ФЗ: Обязанность сообщать информацию по запросу.", "fine": "до 300 000 руб. (ст. 13.11 КоАП)"},
    "Сроки хранения (конкретные)": {"law": "Ст. 5 ч. 7 152-ФЗ: Хранение не дольше, чем требуют цели.", "fine": "до 300 000 руб. (ст. 13.11 КоАП)"},
    "Оценка вреда": {"law": "Ст. 18.1 ч. 1 п. 5 152-ФЗ: Оценка вреда субъектам.", "fine": "до 300 000 руб. (ст. 13.11 КоАП)"},
    "Локализация БД": {"law": "Ст. 18 ч. 5 152-ФЗ: Базы данных должны быть в РФ.", "fine": "до 1 000 000 руб. (ч. 8 ст. 13.11 КоАП)"},
    "Контакты ответственного": {"law": "Ст. 18.1 ч. 1 п. 1 152-ФЗ: Назначение ответственного.", "fine": "до 300 000 руб. (ст. 13.11 КоАП)"},
    "Договор с хостингом (поручение)": {"law": "Ст. 6 ч. 3 152-ФЗ: Поручение обработки ПДн оформляется договором.", "fine": "до 300 000 руб. (ст. 13.11 КоАП)"},
    "Правила рекомендаций": {"law": "Ст. 10.2-1 149-ФЗ: Правила применения рекомендательных технологий.", "fine": "до 300 000 руб. (ст. 13.11 КоАП)"},
    "Согласие работников на ФИО": {"law": "Ст. 9 152-ФЗ: Согласие на публикацию данных работников.", "fine": "до 300 000 руб. (ст. 13.11 КоАП)"},
    "Отдельное согласие на рекламу": {"law": "Ст. 15 152-ФЗ / Ст. 18 38-ФЗ: Согласие на рекламу.", "fine": "до 500 000 руб. (ст. 14.3 КоАП)"}
}

WEIGHTS = {
    "Наличие отдельного согласия": 0.10, "Отдельный чек-бокс согласия": 0.10,
    "Отсутствие презумпции согласия": 0.08, "Cookie-баннер и согласие": 0.06,
    "Минимизация данных": 0.06, "Отзыв согласия (любая форма)": 0.06,
    "Наличие в реестре РКН": 0.06, "Уведомление об инцидентах 24/72": 0.06,
    "Отсутствие WhatsApp (Meta)": 0.04, "Отсутствие Google Analytics": 0.04,
    "Информация о ПОД/ФТ": 0.04, "Порядок обращений субъектов": 0.04,
    "Сроки хранения (конкретные)": 0.04, "Оценка вреда": 0.04,
    "Локализация БД": 0.04, "Контакты ответственного": 0.04,
    "Договор с хостингом (поручение)": 0.04, "Правила рекомендаций": 0.04,
    "Согласие работников на ФИО": 0.04, "Отдельное согласие на рекламу": 0.02
}

@st.cache_resource
def get_gigachat():
    key = os.environ.get("GIGACHAT_KEY") or st.secrets.get("GIGACHAT_KEY")
    if not key:
        st.error("Ключ GIGACHAT_KEY не найден.")
        st.stop()
    return GigaChat(credentials=key, scope="GIGACHAT_API_PERS", model="GigaChat-2", verify_ssl_certs=False)

giga = get_gigachat()

def download_documents(url):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        response = requests.get(url, headers=headers, timeout=20, verify=False)
        response.raise_for_status()
    except Exception as e:
        return None, None, None, None, f"Ошибка доступа: {e}"

    soup = BeautifulSoup(response.text, "html.parser")
    html_lower = response.text.lower()
    
    tech_markers = {
        "google_analytics": "google-analytics" in html_lower or "_ga" in html_lower,
        "whatsapp": "wa.me" in html_lower or "whatsapp" in html_lower,
        "hosting": "хостинг" in html_lower,
        "recommendations": "избранное" in html_lower or "favorites" in html_lower
    }

    policy_link, consent_link = None, None
    for link in soup.find_all("a"):
        href = link.get("href", "")
        text = link.get_text().lower()
        if not href or href.startswith("#"): continue
        
        full_link = urljoin(url, href)
        if ("политик" in text or "политик" in href.lower()) and not policy_link:
            policy_link = full_link
        if ("согласи" in text or "согласи" in href.lower()) and not consent_link:
            consent_link = full_link

    target_url = policy_link or consent_link or url

    try:
        r = requests.get(target_url, headers=headers, timeout=20, verify=False)
        r.raise_for_status()
    except Exception as e:
        return None, policy_link, consent_link, tech_markers, f"Ошибка: {e}"

    if "pdf" in r.headers.get("Content-Type", "").lower() or target_url.lower().endswith(".pdf"):
        try:
            with pdfplumber.open(io.BytesIO(r.content)) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        except Exception as e:
            return None, policy_link, consent_link, tech_markers, f"Ошибка PDF: {e}"
    else:
        soup2 = BeautifulSoup(r.text, "html.parser")
        text = soup2.get_text(separator="\n", strip=True)

    return text, policy_link, consent_link, tech_markers, None

def analyze_with_gigachat(text, tech_markers):
    text_short = text[:12000] if text else "Текст отсутствует."
    
    # УМНЫЙ ПРОМПТ (С четкими инструкциями)
    prompt = f"""
Ты — аудитор. Проверь текст и поставь 1, если нарушение ЕСТЬ, и 0, если нарушения НЕТ.
Вот четкие правила, как проверять:

1. "Наличие отдельного согласия": Если в тексте НЕТ отдельного документа согласия — ставь 1.
2. "Отдельный чек-бокс согласия": Если в тексте написано про кнопку/галочку/чек-бокс — ставь 0. Если нет — 1.
3. "Отсутствие презумпции согласия": Если есть фраза "использование сайта означает согласие" — ставь 1.
4. "Cookie-баннер и согласие": Если в тексте есть слово "cookie" и описан баннер — 0. Если нет — 1.
5. "Минимизация данных": Если в тексте есть список целей и данных — 0. Если нет — 1.
6. "Отзыв согласия (любая форма)": Если написано "только по почте" — 1. Если можно отозвать на сайте — 0.
7. "Наличие в реестре РКН": Если в тексте упоминается реестр/номер — 0. Если нет — 1.
8. "Уведомление об инцидентах 24/72": Если есть слова "24 часа", "72 часа", "инцидент" — 0. Если нет — 1.
9. "Информация о ПОД/ФТ": Если есть раздел про 115-ФЗ или идентификацию — 0. Если нет — 1.
10. "Порядок обращений субъектов": Если описан порядок отправки запросов (email, адрес) — 0. Если нет — 1.
11. "Сроки хранения (конкретные)": Если указаны конкретные сроки (например, "5 лет") — 0. Если "до достижения цели" — 1.
12. "Оценка вреда": Если есть раздел про оценку вреда — 0. Если нет — 1.
13. "Локализация БД": Если есть фраза "базы данных на территории РФ" — 0. Если нет — 1.
14. "Контакты ответственного": Если указано ФИО ответственного или его email — 0. Если нет — 1.
15. "Договор с хостингом (поручение)": Если упоминается хостинг/поручение — 0. Если нет — 1.
16. "Согласие работников на ФИО": Если в тексте есть раздел про работников — 0. Если нет — 1.
17. "Отдельное согласие на рекламу": Если упоминается отдельное согласие на рекламу — 0. Если нет — 1.

ТЕКСТ: {text_short}
ДАННЫЕ: GA: {"Да" if tech_markers['google_analytics'] else "Нет"}, WA: {"Да" if tech_markers['whatsapp'] else "Нет"}, Хостинг: {"Да" if tech_markers['hosting'] else "Нет"}, Избранное: {"Да" if tech_markers['recommendations'] else "Нет"}

Ответь СТРОГО в формате JSON (ключ = название, значение = 1 или 0):
{{
  "Наличие отдельного согласия": 1,
  "Отдельный чек-бокс согласия": 1,
  "Отсутствие презумпции согласия": 1,
  "Cookie-баннер и согласие": 1,
  "Минимизация данных": 1,
  "Отзыв согласия (любая форма)": 1,
  "Наличие в реестре РКН": 1,
  "Уведомление об инцидентах 24/72": 1,
  "Отсутствие WhatsApp (Meta)": 1,
  "Отсутствие Google Analytics": 1,
  "Информация о ПОД/ФТ": 1,
  "Порядок обращений субъектов": 1,
  "Сроки хранения (конкретные)": 1,
  "Оценка вреда": 1,
  "Локализация БД": 1,
  "Контакты ответственного": 1,
  "Договор с хостингом (поручение)": 1,
  "Правила рекомендаций": 1,
  "Согласие работников на ФИО": 1,
  "Отдельное согласие на рекламу": 1
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

def get_final_results(ai_result, tech_markers):
    """Гибридная логика: ИИ + технические маркеры"""
    final = ai_result.copy() if ai_result else {k: 0 for k in WEIGHTS.keys()}
    
    # Принудительно ставим нарушения, если техника их нашла
    if tech_markers['google_analytics']: final["Отсутствие Google Analytics"] = 1
    if tech_markers['whatsapp']: final["Отсутствие WhatsApp (Meta)"] = 1
    if tech_markers['recommendations']: final["Правила рекомендаций"] = 1
    
    return final

def calculate_risk(final_results):
    risk = 0.0
    total_weight = sum(WEIGHTS.values())
    for criterion, weight in WEIGHTS.items():
        if final_results.get(criterion) == 1:
            risk += weight
    return round(risk / total_weight, 2) if total_weight > 0 else 0

def get_risk_level(risk):
    if risk >= 0.75: return "Критический", "inverse"
    if risk >= 0.50: return "Высокий", "inverse"
    if risk >= 0.25: return "Умеренный", "off"
    return "Допустимый", "normal"

# ==========================================
# ИНТЕРФЕЙС
# ==========================================

if "audit_started" not in st.session_state:
    st.session_state.audit_started = False

if not st.session_state.audit_started:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.title(":material/account_balance: RegRisk Audit")
        st.markdown("""
        Система автоматизированного аудита веб-ресурсов на соответствие требованиям 
        **152-ФЗ**, **149-ФЗ** и **115-ФЗ**.
        """)
        with st.container(border=True):
            st.subheader("Начать проверку")
            url_input = st.text_input("URL-адрес сайта", placeholder="https://example.ru")
            if st.button("Запустить аудит", type="primary", use_container_width=True):
                if url_input:
                    st.session_state.url_to_check = url_input
                    st.session_state.audit_started = True
                    st.rerun()
                else:
                    st.error("Введите URL")
else:
    url_input = st.session_state.url_to_check
    
    if st.button("← Новый аудит", type="secondary"):
        st.session_state.audit_started = False
        st.session_state.url_to_check = ""
        st.rerun()

    with st.spinner("Сканирование и анализ..."):
        text, policy_url, consent_url, tech_markers, error = download_documents(url_input)

    if error:
        st.error(f"Критическая ошибка: {error}")
    else:
        with st.spinner("Формирование заключения..."):
            ai_raw = analyze_with_gigachat(text, tech_markers)
            final_results = get_final_results(ai_raw, tech_markers)

        if final_results:
            final_risk = calculate_risk(final_results)
            level_text, delta_col = get_risk_level(final_risk)
            
            st.title("Отчет об аудите")
            
            c1, c2, c3 = st.columns(3)
            with c1: st.info(f"**Объект:** [{url_input}]({url_input})")
            with c2: 
                if policy_url: st.success(f"**Политика:** [{policy_url[:25]}...]({policy_url})")
                else: st.error("**Политика не найдена**")
            with c3: 
                if consent_url: st.success(f"**Согласие:** [{consent_url[:25]}...]({consent_url})")
                else: st.warning("**Согласие не найдено**")
            
            st.divider()
            
            tab1, tab2, tab3 = st.tabs(["📊 Дашборд", "🧮 Математика", "📑 Заключение"])

            with tab1:
                col_gauge, col_metrics = st.columns([1, 2])
                with col_gauge:
                    fig = go.Figure(go.Indicator(
                        mode = "gauge+number", value = final_risk * 100, title = {'text': "Риск (%)"},
                        gauge = {
                            'axis': {'range': [0, 100]}, 'bar': {'color': "#1E293B"},
                            'steps': [
                                {'range': [0, 25], 'color': "#D1FAE5"}, {'range': [25, 50], 'color': "#FEF3C7"},
                                {'range': [50, 75], 'color': "#FEE2E2"}, {'range': [75, 100], 'color': "#FCA5A5"}
                            ],
                        }
                    ))
                    fig.update_layout(margin=dict(l=10, r=10, t=30, b=10), height=220)
                    st.plotly_chart(fig, use_container_width=True)
                
                with col_metrics:
                    st.markdown("### Итоги")
                    st.metric(label="Интегральный риск", value=f"{final_risk:.2f}", delta=level_text, delta_color=delta_col)
                    violations_count = sum(1 for v in final_results.values() if v == 1)
                    st.metric(label="Выявлено нарушений", value=violations_count)

            with tab2:
                st.subheader("Расчет риска")
                st.latex(r"R = \frac{\sum (W_i \times r_i)}{\sum W_i}")
                data = []
                for crit, weight in WEIGHTS.items():
                    is_viol = final_results.get(crit, 0)
                    data.append({"Критерий": crit, "Вес (W)": weight, "Факт (1/0)": is_viol, "Вклад": weight if is_viol == 1 else 0})
                
                df = pd.DataFrame(data)
                st.dataframe(df.style.apply(lambda x: ['background: #FEE2E2' if v == 1 else '' for v in x], subset=['Факт (1/0)'], axis=1), use_container_width=True, hide_index=True)

            with tab3:
                st.subheader("Заключение")
                violations_found = False
                for idx, (crit, val) in enumerate(final_results.items(), 1):
                    if val == 1:
                        violations_found = True
                        law_info = LAW_DATABASE.get(crit, {"law": "См. законодательство РФ", "fine": "КоАП РФ"})
                        
                        with st.expander(f"{idx}. {crit}", expanded=True):
                            st.markdown(f"**Норма:** {law_info['law']}")
                            st.markdown(f"**Штраф:** :red[**{law_info['fine']}**]")
                
                if not violations_found:
                    st.success("Нарушений не выявлено.")
