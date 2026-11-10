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
LAW_DATABASE = {
    "Наличие отдельного согласия": {
        "law": "Ст. 9 152-ФЗ: Согласие оформляется отдельно от иных документов.",
        "fine": "150 000 – 300 000 руб. (ч. 1 ст. 13.11 КоАП)",
        "explanation": "Согласие не оформлено как отдельный документ или чек-бокс, а включено в общий текст.",
        "recommendation": "Разработать отдельный документ «Согласие на обработку ПДн» и разместить его на сайте."
    },
    "Отсутствие презумпции согласия": {
        "law": "Ст. 9 152-ФЗ: Согласие должно быть конкретным, предметным и однозначным.",
        "fine": "150 000 – 300 000 руб. (ч. 1 ст. 13.11 КоАП)",
        "explanation": "Политика содержит фразу «использование сайта означает согласие», что недопустимо.",
        "recommendation": "Удалить фразы, приравнивающие использование сайта к согласию. Ввести явный чек-бокс."
    },
    "Cookie-баннер и согласие": {
        "law": "Ст. 9 152-ФЗ: Использование cookie требует предварительного согласия.",
        "fine": "150 000 – 300 000 руб. (ч. 1 ст. 13.11 КоАП)",
        "explanation": "На сайте используются аналитические cookie (Яндекс.Метрика, Google Analytics) без баннера согласия.",
        "recommendation": "Внедрить cookie-баннер с опцией «Принять» / «Отклонить» до загрузки скриптов аналитики."
    },
    "Отзыв согласия (любая форма)": {
        "law": "Ст. 9 152-ФЗ: Согласие может быть отозвано в любой момент.",
        "fine": "150 000 – 300 000 руб. (ч. 1 ст. 13.11 КоАП)",
        "explanation": "Политика ограничивает отзыв согласия только письменной формой по почте.",
        "recommendation": "Добавить возможность отзыва согласия через email или форму на сайте."
    },
    "Наличие в реестре РКН": {
        "law": "Ст. 22 152-ФЗ: Оператор обязан уведомить РКН.",
        "fine": "150 000 – 300 000 руб. (ч. 1 ст. 13.11 КоАП)",
        "explanation": "Оператор не подавал уведомление в Роскомнадзор об обработке ПДн.",
        "recommendation": "Подать уведомление в РКН через портал pd.rkn.gov.ru."
    },
    "Уведомление об инцидентах 24/72": {
        "law": "Ст. 21 ч. 3.1 152-ФЗ: Уведомление РКН в течение 24 и 72 часов.",
        "fine": "1 000 000 – 3 000 000 руб. (ч. 8 ст. 13.11 КоАП)",
        "explanation": "В политике отсутствует описание процедуры уведомления об утечках.",
        "recommendation": "Разработать регламент реагирования на инциденты с указанием сроков 24/72 часа."
    },
    "Отсутствие WhatsApp (Meta)": {
        "law": "Ст. 13.15 КоАП / Закон о рекламе",
        "fine": "800 000 – 1 000 000 руб. (ст. 13.15 КоАП)",
        "explanation": "На сайте присутствуют ссылки на WhatsApp (Meta признана экстремистской организацией).",
        "recommendation": "Удалить ссылки на WhatsApp или заменить на российские мессенджеры."
    },
    "Отсутствие Google Analytics": {
        "law": "Ст. 12 152-ФЗ: Уведомление РКН о трансграничной передаче.",
        "fine": "150 000 – 300 000 руб. (ст. 13.11 КоАП)",
        "explanation": "Используется Google Analytics, что является трансграничной передачей без уведомления.",
        "recommendation": "Заменить Google Analytics на Яндекс.Метрику или уведомить РКН о трансграничной передаче."
    },
    "Договор с хостингом (поручение)": {
        "law": "Ст. 6 ч. 3 152-ФЗ: Поручение обработки ПДн оформляется договором.",
        "fine": "150 000 – 300 000 руб. (ст. 13.11 КоАП)",
        "explanation": "В политике не указано, что обработка ПДн поручена хостинг-провайдеру на основании договора.",
        "recommendation": "Заключить договор поручения обработки с хостингом и упомянуть это в политике."
    },
    "Правила рекомендаций": {
        "law": "Ст. 10.2-1 149-ФЗ: Правила применения рекомендательных технологий.",
        "fine": "150 000 – 300 000 руб. (ст. 13.11 КоАП)",
        "explanation": "На сайте есть функция «Избранное», но отсутствуют правила рекомендательных технологий.",
        "recommendation": "Разработать и разместить правила работы рекомендательных алгоритмов."
    },
    "Информация о ПОД/ФТ": {
        "law": "Ст. 7 115-ФЗ: Обязанность идентификации клиентов.",
        "fine": "50 000 – 100 000 руб. (ч. 1 ст. 15.27 КоАП)",
        "explanation": "На сайте отсутствует информация о порядке идентификации клиентов в рамках 115-ФЗ.",
        "recommendation": "Добавить раздел о процедурах идентификации и ПОД/ФТ."
    }
    "Сроки хранения (конкретные)": {
        "law": "Ст. 5 ч. 7 152-ФЗ: Хранение не дольше, чем требуют цели.",
        "fine": "150 000 – 300 000 руб. (ч. 1 ст. 13.11 КоАП)",
        "explanation": "Размытые сроки хранения.",
        "recommendation": "Указать конкретные сроки."
    },
    "Контакты ответственного": {
        "law": "Ст. 18.1 ч. 1 п. 1 152-ФЗ: Назначение ответственного.",
        "fine": "150 000 – 300 000 руб. (ч. 1 ст. 13.11 КоАП)",
        "explanation": "Нет ФИО и контактов ответственного.",
        "recommendation": "Добавить контакты ответственного."
    },
    "Оценка вреда": {
        "law": "Ст. 18.1 ч. 1 п. 5 152-ФЗ: Оценка вреда субъектам.",
        "fine": "150 000 – 300 000 руб. (ч. 1 ст. 13.11 КоАП)",
        "explanation": "Нет оценки потенциального вреда.",
        "recommendation": "Провести оценку вреда."
    },
    "Локализация БД": {
        "law": "Ст. 18 ч. 5 152-ФЗ: Базы данных должны быть в РФ.",
        "fine": "1 000 000 – 18 000 000 руб. (ч. 8-9 ст. 13.11 КоАП)",
        "explanation": "Нет упоминания о локализации серверов в РФ.",
        "recommendation": "Указать, что серверы в РФ."
    },
    "Минимизация данных": {
        "law": "Ст. 5 ч. 5 152-ФЗ: Объем ПДн должен соответствовать целям.",
        "fine": "150 000 – 300 000 руб. (ч. 1 ст. 13.11 КоАП)",
        "explanation": "Нет указаний на минимизацию.",
        "recommendation": "Пересмотреть формы сбора данных."
    },
    "Отдельное согласие на рекламу": {
        "law": "Ст. 18 ч. 1 38-ФЗ «О рекламе»: Реклама только с согласия.",
        "fine": "до 500 000 руб. (ст. 14.3 КоАП)",
        "explanation": "Нет отдельного согласия на рассылки.",
        "recommendation": "Внедрить отдельный чек-бокс на рекламу."
    }
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
    if not text or len(text) < 100:
        st.warning("⚠️ Текст политики не найден или слишком короткий.")
        return {"findings": []}

    # Берем кусок текста (чтобы не перегружать контекст)
    text_short = text[:12000]
    
    # Формируем блок технических данных
    tech_data = f"""
    Внимание, техническая проверка сайта показала:
    - Google Analytics: {"ДА (НАРУШЕНИЕ)" if tech_markers['google_analytics'] else "НЕТ"}
    - Ссылки на WhatsApp: {"ДА (НАРУШЕНИЕ)" if tech_markers['whatsapp'] else "НЕТ"}
    - Упоминание хостинга в HTML: {"ЕСТЬ" if tech_markers['hosting'] else "НЕТ"}
    - Функция Избранное (рекомендации): {"ЕСТЬ (НАРУШЕНИЕ)" if tech_markers['recommendations'] else "НЕТ"}
    """

    prompt = f"""
Ты — строгий инспектор Роскомнадзора. Твоя задача — провести аудит текста политики и найти ВСЕ нарушения.
Если ты не найдешь нарушения, тебя уволят. Будь максимально придирчив. 

Вот текст политики:
---
{text_short}
---

Вот технические данные сайта:
{tech_data}

ИНСТРУКЦИЯ: Прочитай текст и ответь на 20 вопросов ниже. 
Если ответ на вопрос — "НЕТ" (требования нет), значит это НАРУШЕНИЕ.
Если ответ "ДА" (требование выполнено), значит нарушения НЕТ.

1. Есть ли фраза "24 часа" и "72 часа" (уведомление об утечках)? (Если нет -> ID: "Уведомление об инцидентах 24/72")
2. Есть ли слова "реестр", "Роскомнадзор" (уведомление о начале обработки)? (Если нет -> ID: "Наличие в реестре РКН")
3. Указаны ли конкретные сроки хранения (например, "5 лет"), а не просто "до достижения цели"? (Если нет -> ID: "Сроки хранения (конкретные)")
4. Указаны ли ФИО и контакты ответственного за обработку ПДн? (Если нет -> ID: "Контакты ответственного")
5. Есть ли раздел про оценку вреда субъектам? (Если нет -> ID: "Оценка вреда")
6. Есть ли слова "локализация", "серверы в РФ", "территория РФ"? (Если нет -> ID: "Локализация БД")
7. Указано ли, что обработка поручена хостингу (по договору)? (Если нет -> ID: "Договор с хостингом (поручение)")
8. В тех.данных есть Google Analytics? (Если ДА -> ID: "Отсутствие Google Analytics")
9. В тех.данных есть WhatsApp? (Если ДА -> ID: "Отсутствие WhatsApp (Meta)")
10. В тех.данных есть Избранное, но в тексте нет правил рекомендаций? (Если ДА -> ID: "Правила рекомендаций")
11. Есть ли фраза "использование сайта означает согласие" или "продолжая использовать"? (Если ДА -> ID: "Отсутствие презумпции согласия")
12. Есть ли фраза "согласие считается принятым с момента нажатия кнопки"? (Если ДА -> ID: "Отдельный чек-бокс согласия")
13. Написано ли, что отзыв согласия возможен ТОЛЬКО письменно по почте? (Если ДА -> ID: "Отзыв согласия (любая форма)")
14. Есть ли упоминание о сборе минимально необходимых данных? (Если нет -> ID: "Минимизация данных")
15. Есть ли отдельный документ "Согласие" (упоминание ссылки на него)? (Если нет -> ID: "Наличие отдельного согласия")
16. Есть ли в тексте раздел про 115-ФЗ и идентификацию клиентов? (Если нет -> ID: "Информация о ПОД/ФТ")
17. Есть ли описание порядка обращений субъектов (как подать запрос)? (Если нет -> ID: "Порядок обращений субъектов")
18. Есть ли отдельное согласие на рекламные рассылки (упоминание чек-бокса)? (Если нет -> ID: "Отдельное согласие на рекламу")
19. Упоминается ли согласие работников на публикацию их ФИО? (Если нет -> ID: "Согласие работников на ФИО")
20. Упоминается ли согласие на использование Cookie (баннер)? (Если нет -> ID: "Cookie-баннер и согласие")

СПИСОК ВАЛИДНЫХ ID (используй только их!):
{list(WEIGHTS.keys())}

Ответь СТРОГО в формате JSON:
{{
  "findings": [
    {{ "criteria_id": "НАЗВАНИЕ ID", "reason": "Почему это нарушение (до 10 слов)" }}
  ]
}}
"""
    
    try:
        # Отправляем запрос с минимальной температурой (чтобы не фантазировал)
        response = giga.chat({
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0 
        })
        content = response.choices[0].message.content
        
        # Ищем JSON в ответе
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match: 
            data = json.loads(json_match.group())
            # Фильтруем галлюцинации (если ИИ выдумал ID, которого нет в списке)
            valid_findings = []
            for f in data.get("findings", []):
                if f.get("criteria_id") in WEIGHTS:
                    valid_findings.append(f)
            return {"findings": valid_findings}
            
        return {"findings": []}
    except Exception as e:
        st.error(f"Ошибка ИИ: {e}")
        # Если JSON не распарсился, выводим сырой ответ для отладки
        if 'content' in locals():
            st.code(content)
        return {"findings": []}

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
        st.write("")
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
            ai_result = analyze_with_gigachat(text, tech_markers)

        if ai_result:
            findings = ai_result.get("findings", [])
            final_risk = calculate_risk(findings)
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
                    st.metric(label="Нарушений", value=len(findings))

            with tab2:
                st.subheader("Расчет риска")
                st.latex(r"R = \frac{\sum (W_i \times r_i)}{\sum W_i}")
                data = []
                found_ids = [f.get("criteria_id") for f in findings]
                for crit, weight in WEIGHTS.items():
                    is_viol = 1 if crit in found_ids else 0
                    data.append({"Критерий": crit, "Вес (W)": weight, "Факт": is_viol, "Вклад": weight if is_viol == 1 else 0})
                
                df = pd.DataFrame(data)
                st.dataframe(df.style.apply(lambda x: ['background: #FEE2E2' if v == 1 else '' for v in x], subset=['Факт'], axis=1), use_container_width=True, hide_index=True)

            with tab3:
                st.subheader("Детальное заключение")
                if not findings:
                    st.success("Нарушений не выявлено.")
                
                recommendations = []
                for idx, finding in enumerate(findings, 1):
                    crit_id = finding.get("criteria_id")
                    reason = finding.get("reason", "Нарушение.")
                    
                    info = LAW_DATABASE.get(crit_id, {
                        "law": "См. законодательство РФ", "fine": "КоАП РФ",
                        "explanation": reason, "recommendation": "Устранить нарушение."
                    })
                    
                    if info["recommendation"] not in recommendations:
                        recommendations.append(info["recommendation"])
                    
                    with st.expander(f"{idx}. {crit_id}", expanded=True):
                        st.markdown(f"**Норма:** {info['law']}")
                        st.markdown(f"**Штраф:** :red[**{info['fine']}**]")
                        st.markdown(f"**Пояснение:** {info['explanation']}")
                
                st.divider()
                st.subheader("План мероприятий по устранению")
                if recommendations:
                    for rec in recommendations:
                        st.markdown(f"- {rec}")
                else:
                    st.success("Рекомендаций нет.")
