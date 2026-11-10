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

# --- БАЗА ЗНАНИЙ ---
LAW_BASE = """
[152-ФЗ Статья 9. Согласие] Согласие должно быть конкретным, предметным, информированным и однозначным. Оформляется отдельно. (Штраф по ч. 1 ст. 13.11 КоАП: до 300 000 руб.)
[152-ФЗ Статья 6. Поручение] Оператор вправе поручить обработку ПДн другому лицу (например, хостингу) на основании договора.
[152-ФЗ Статья 12. Трансгранично] До начала трансграничной передачи (например, Google Analytics) нужно уведомить РКН.
[152-ФЗ Статья 18.1. Политика] Оператор обязан опубликовать политику в свободном доступе. (Штраф по ст. 13.11 КоАП: до 60 000 руб.)
[152-ФЗ Статья 21. Инциденты] Уведомление РКН: 24 часа (факт), 72 часа (результаты). (Штраф по ч. 8 ст. 13.11 КоАП: до 3 000 000 руб.)
[149-ФЗ Статья 10.2-1. Рекомендации] Владелец сайта обязан разместить правила применения рекомендательных технологий.
[38-ФЗ Статья 18. Реклама] Реклама по сетям связи только с предварительного согласия. (Штраф по ст. 14.3 КоАП: до 500 000 руб.)
"""

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
        return None, None, None, None, f"Ошибка доступа к сайту: {e}"

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

    # Если ссылка на согласие не найдена отдельно, но есть на политике - попробуем взять оттуда
    target_url = policy_link or consent_link or url

    try:
        r = requests.get(target_url, headers=headers, timeout=20, verify=False)
        r.raise_for_status()
    except Exception as e:
        return None, policy_link, consent_link, tech_markers, f"Ошибка скачивания документа: {e}"

    if "pdf" in r.headers.get("Content-Type", "").lower() or target_url.lower().endswith(".pdf"):
        try:
            with pdfplumber.open(io.BytesIO(r.content)) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        except Exception as e:
            return None, policy_link, consent_link, tech_markers, f"Ошибка чтения PDF: {e}"
    else:
        soup2 = BeautifulSoup(r.text, "html.parser")
        text = soup2.get_text(separator="\n", strip=True)

    return text, policy_link, consent_link, tech_markers, None

def analyze_with_gigachat(text, tech_markers):
    text_short = text[:12000] if text else "Текст отсутствует."
    prompt = f"""
Ты — строгий аудитор по защите персональных данных. Найди нарушения.
БАЗА ЗНАНИЙ: {LAW_BASE}
ТЕКСТ: {text_short}
ТЕХ. ДАННЫЕ: GA: {"Да" if tech_markers['google_analytics'] else "Нет"}, WA: {"Да" if tech_markers['whatsapp'] else "Нет"}, Хостинг: {"Да" if tech_markers['hosting'] else "Нет"}, Избранное: {"Да" if tech_markers['recommendations'] else "Нет"}

Ответь СТРОГО в JSON:
{{
  "findings": [ {{ "criteria_id": "ID из списка", "title": "...", "law": "...", "description": "..." }} ],
  "recommendations": ["..."]
}}
СПИСОК КРИТЕРИЕВ: {list(WEIGHTS.keys())}
"""
    try:
        response = giga.chat(prompt)
        content = response.choices[0].message.content
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match: return json.loads(json_match.group())
        return None
    except Exception as e:
        st.error(f"Ошибка ИИ: {e}")
        return None

def calculate_risk(findings):
    risk = 0.0
    total_weight = sum(WEIGHTS.values())
    found_ids = [f.get("criteria_id") for f in findings]
    for criterion, weight in WEIGHTS.items():
        if criterion in found_ids: risk += weight
    return round(risk / total_weight, 2) if total_weight > 0 else 0

def get_risk_level(risk):
    if risk >= 0.75: return "Критический", "inverse"
    if risk >= 0.50: return "Высокий", "inverse"
    if risk >= 0.25: return "Умеренный", "off"
    return "Допустимый", "normal"

# --- ИНТЕРФЕЙС ---
with st.sidebar:
    st.markdown("### :material/account_balance: RegRisk Audit")
    st.divider()
    url_input = st.text_input("URL-адрес веб-ресурса", placeholder="https://example.ru")
    start_audit = st.button("Инициировать аудит", type="primary", use_container_width=True)
    st.divider()
    st.caption("Модуль оценки соответствия 152-ФЗ, 149-ФЗ и 115-ФЗ. Расчет интегрального риска по методу взвешенной суммы.")

if start_audit and url_input:
    with st.spinner("Сканирование веб-ресурса и извлечение документов..."):
        text, policy_url, consent_url, tech_markers, error = download_documents(url_input)

    if error:
        st.error(f"Критическая ошибка: {error}")
    else:
        with st.spinner("Формирование юридического заключения..."):
            ai_result = analyze_with_gigachat(text, tech_markers)

        if ai_result:
            findings = ai_result.get("findings", [])
            final_risk = calculate_risk(findings)
            level_text, delta_col = get_risk_level(final_risk)
            
            # --- ШАПКА ОТЧЕТА ---
            st.title("Отчет об аудите")
            
            # Красивые ссылки в плашках
            col_urls1, col_urls2, col_urls3 = st.columns(3)
            with col_urls1:
                st.info(f"**Объект аудита:**\n[{url_input}]({url_input})")
            with col_urls2:
                if policy_url:
                    st.success(f"**Найдена Политика:**\n[{policy_url[:30]}...]({policy_url})")
                else:
                    st.error("**Политика не найдена**")
            with col_urls3:
                if consent_url:
                    st.success(f"**Найдено Согласие:**\n[{consent_url[:30]}...]({consent_url})")
                else:
                    st.warning("**Отдельное Согласие не найдено**")
            
            st.divider()
            
            # --- ВКЛАДКИ ---
            tab1, tab2, tab3 = st.tabs(["📊 Дашборд рисков", "🧮 Математическая модель", "📑 Юридическое заключение"])

            with tab1:
                col_gauge, col_metrics = st.columns([1, 2])
                
                # График-спидометр
                with col_gauge:
                    fig = go.Figure(go.Indicator(
                        mode = "gauge+number",
                        value = final_risk * 100,
                        title = {'text': "Уровень риска (%)"},
                        gauge = {
                            'axis': {'range': [0, 100]},
                            'bar': {'color': "#1E293B"},
                            'steps': [
                                {'range': [0, 25], 'color': "#D1FAE5"},
                                {'range': [25, 50], 'color': "#FEF3C7"},
                                {'range': [50, 75], 'color': "#FEE2E2"},
                                {'range': [75, 100], 'color': "#FCA5A5"}
                            ],
                        }
                    ))
                    fig.update_layout(margin=dict(l=20, r=20, t=40, b=20), height=250)
                    st.plotly_chart(fig, use_container_width=True)
                
                # Карточки
                with col_metrics:
                    st.markdown("### Результаты анализа")
                    st.metric(label="Интегральный риск", value=f"{final_risk:.2f}", delta=level_text, delta_color=delta_col)
                    st.metric(label="Выявлено нарушений", value=len(findings))
                    
                    if final_risk > 0.5:
                        st.error("**Рекомендация:** Незамедлительно устранить выявленные нарушения. Риск привлечения к ответственности по КоАП РФ крайне высок.")
                    else:
                        st.success("**Рекомендация:** Провести плановую доработку документов для исключения потенциальных рисков.")

            with tab2:
                st.subheader("Расчет интегрального риска")
                st.info("Модель: \(R = \\frac{\\sum (W_i \\times r_i)}{\\sum W_i}\)")
                data = []
                found_ids = [f.get("criteria_id") for f in findings]
                for crit, weight in WEIGHTS.items():
                    is_viol = 1 if crit in found_ids else 0
                    data.append({"Критерий": crit, "Вес (W)": weight, "Нарушено (1/0)": is_viol, "Вклад в риск": weight if is_viol == 1 else 0})
                
                df = pd.DataFrame(data)
                # Раскрасим строки, где есть нарушения
                st.dataframe(
                    df.style.apply(lambda x: ['background: #FEE2E2' if v == 1 else '' for v in x], subset=['Нарушено (1/0)'], axis=1),
                    use_container_width=True, hide_index=True
                )

            with tab3:
                st.subheader("Детальное юридическое заключение")
                if not findings:
                    st.success("Нарушений не выявлено (по данным ИИ).")
                for idx, finding in enumerate(findings, 1):
                    with st.expander(f"{idx}. {finding.get('title')}", expanded=True):
                        st.markdown(f"**Правовое обоснование:** \n> {finding.get('law')}")
                        st.markdown(f"**Суть нарушения:** {finding.get('description')}")
                
                st.divider()
                st.subheader("План мероприятий по устранению")
                for rec in ai_result.get("recommendations", []):
                    st.markdown(f"- {rec}")

elif start_audit and not url_input:
    st.error("Введите URL-адрес.")
else:
    # Красивая стартовая страница
    st.title("Система аудита регуляторных рисков")
    st.markdown("""
    Добро пожаловать в **RegRisk Audit**. 
    
    Система автоматически сканирует веб-ресурс, извлекает Политику обработки персональных данных и Согласие, а затем проводит аудит на соответствие требованиям **152-ФЗ, 149-ФЗ и КоАП РФ**.
    
    **Как начать:**
    1. Введите URL сайта в левой панели.
    2. Нажмите «Инициировать аудит».
    3. Изучите спидометр риска и юридическое заключение.
    """)
