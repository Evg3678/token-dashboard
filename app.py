import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import io
import requests
from dateutil import parser
import numpy as np
import xml.etree.ElementTree as ET

# Настройка страницы
st.set_page_config(page_title="Анализ токенов ИИ", layout="wide")
st.title("🤖 Дашборд аналитики токенов ИИ")

# Кэширование курсов валют (обновляем каждый час)
@st.cache_data(ttl=3600)
def get_cbr_rates_alternative(target_date):
    """
    Получает курсы валют от ЦБ РФ через зеркало cbr-xml-daily.ru
    Возвращает словарь {код_валюты: курс}
    """
    # Форматируем дату для API
    if isinstance(target_date, (datetime, pd.Timestamp)):
        date_str = target_date.strftime('%Y-%m-%d')
    else:
        date_str = target_date
    
    # Используем альтернативное API, которое не блокирует запросы
    url = f"https://www.cbr-xml-daily.ru/archive/{date_str}/daily.xml"
    
    try:
        response = requests.get(url, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        if response.status_code != 200:
            # Пробуем без даты (последний доступный курс)
            url = "https://www.cbr-xml-daily.ru/daily.xml"
            response = requests.get(url, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            if response.status_code != 200:
                return None
        
        # Парсим XML
        root = ET.fromstring(response.content)
        
        rates = {}
        for valute in root.findall('.//Valute'):
            char_code = valute.find('CharCode')
            value = valute.find('Value')
            nominal = valute.find('Nominal')
            
            if char_code is not None and value is not None and nominal is not None:
                code = char_code.text
                rate_value = float(value.text.replace(',', '.'))
                rate_nominal = float(nominal.text)
                rates[code] = rate_value / rate_nominal
        
        # Добавляем рубль
        rates['RUB'] = 1.0
        
        return rates
    except Exception as e:
        return None

def get_closest_rates_alternative(dates_list, max_age_days=7):
    """
    Получает курсы для набора дат через альтернативное API
    """
    if isinstance(dates_list, np.ndarray):
        dates_list = dates_list.tolist()
    
    unique_dates = sorted(set(dates_list))
    rates_cache = {}
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for i, date in enumerate(unique_dates):
        status_text.text(f"Загрузка курсов... {i+1}/{len(unique_dates)}")
        progress_bar.progress((i + 1) / len(unique_dates))
        
        rates = get_cbr_rates_alternative(date)
        
        if rates is None:
            current_date = date - timedelta(days=1)
            attempts = 0
            while attempts < max_age_days and current_date >= date - timedelta(days=max_age_days):
                rates = get_cbr_rates_alternative(current_date)
                if rates is not None:
                    st.info(f"ℹ️ Для даты {date} использован курс от {current_date}")
                    break
                current_date -= timedelta(days=1)
                attempts += 1
        
        if rates is not None:
            rates_cache[date] = rates
        else:
            st.warning(f"⚠️ Не удалось получить курс для даты {date}")
    
    progress_bar.empty()
    status_text.empty()
    
    return rates_cache

def convert_to_rub(row, rates_cache):
    """Конвертирует сумму из USD в RUB по курсу на дату операции"""
    date = row['date']
    amount_usd = row['cost_total']
    
    if pd.isna(amount_usd) or amount_usd == 0:
        return 0
    
    if date in rates_cache and rates_cache[date] is not None:
        usd_rate = rates_cache[date].get('USD')
        if usd_rate:
            return amount_usd * usd_rate
    
    return 0

# Загрузка файла
uploaded_file = st.file_uploader("Загрузите CSV с логами", type=['csv'])

if uploaded_file is not None:
    # Читаем данные
    df = pd.read_csv(uploaded_file)
    
    # Показываем сырые данные для отладки
    with st.expander("🔍 Предпросмотр данных"):
        st.write(f"Всего записей: {len(df)}")
        st.write("Первые 5 строк:")
        st.dataframe(df.head())
        st.write("Типы данных:")
        st.write(df.dtypes)
    
    # Приводим дату к нормальному виду
    df['created_at'] = pd.to_datetime(df['created_at'])
    df['date'] = df['created_at'].dt.date
    
    # ОЧИСТКА ДАННЫХ
    df['app_name'] = df['app_name'].fillna('unknown').astype(str)
    df['app_name'] = df['app_name'].replace('nan', 'unknown').replace('None', 'unknown')
    
    df['api_key_name'] = df['api_key_name'].fillna('unknown').astype(str)
    df['api_key_name'] = df['api_key_name'].replace('nan', 'unknown').replace('None', 'unknown')
    
    df['model_permaslug'] = df['model_permaslug'].fillna('unknown').astype(str)
    df['provider_name'] = df['provider_name'].fillna('unknown').astype(str)
    
    # Заполняем числовые поля
    df['tokens_prompt'] = df['tokens_prompt'].fillna(0)
    df['tokens_completion'] = df['tokens_completion'].fillna(0)
    df['tokens_cached'] = df['tokens_cached'].fillna(0)
    df['tokens_reasoning'] = df['tokens_reasoning'].fillna(0)
    df['cost_total'] = df['cost_total'].fillna(0)
    df['generation_time_ms'] = df['generation_time_ms'].fillna(0)
    df['time_to_first_token_ms'] = df['time_to_first_token_ms'].fillna(0)
    
    # ===== ВЫБОР ВАЛЮТЫ =====
    st.sidebar.header("💱 Настройки")
    
    # Чекбокс для выбора валюты
    use_rub = st.sidebar.checkbox(
        "💰 Показывать цены в рублях",
        value=False,
        help="Включите для отображения всех цен в рублях. Выключите для отображения в долларах США."
    )
    
    # Получаем курсы валют, если нужны рубли
    if use_rub:
        with st.spinner("🔄 Загрузка курсов валют ЦБ РФ..."):
            unique_dates = df['date'].unique()
            rates_cache = get_closest_rates_alternative(unique_dates, max_age_days=30)
            
            if rates_cache:
                # Добавляем колонку со стоимостью в рублях
                df['cost_rub'] = df.apply(
                    lambda row: convert_to_rub(row, rates_cache), 
                    axis=1
                )
                
                # Создаём колонку с ценой в выбранной валюте
                df['cost_display'] = df['cost_rub']
                currency_symbol = "₽"
                currency_name = "рублях"
                
                st.sidebar.success(f"✅ Курсы загружены ({len(rates_cache)} дат)")
                
                # Показываем текущий курс
                if rates_cache:
                    latest_date = max(rates_cache.keys())
                    if rates_cache[latest_date]:
                        usd_rate = rates_cache[latest_date].get('USD', 0)
                        if usd_rate > 0:
                            st.sidebar.metric("Курс USD", f"{usd_rate:.2f} ₽")
                            st.sidebar.caption(f"на {latest_date}")
            else:
                st.sidebar.error("❌ Не удалось загрузить курсы. Используются доллары.")
                use_rub = False
                df['cost_display'] = df['cost_total']
                currency_symbol = "$"
                currency_name = "долларах"
    else:
        # Используем доллары
        df['cost_display'] = df['cost_total']
        currency_symbol = "$"
        currency_name = "долларах"
    
    # Боковая панель с фильтрами
    st.sidebar.header("📊 Фильтры")
    
    # Фильтр по датам
    min_date = df['date'].min()
    max_date = df['date'].max()
    date_range = st.sidebar.date_input(
        "Период",
        [min_date, max_date],
        min_value=min_date,
        max_value=max_date
    )
    
    # Получаем уникальные значения
    unique_projects = sorted(df['app_name'].unique().tolist())
    unique_models = sorted(df['model_permaslug'].unique().tolist())
    unique_api_keys = sorted(df['api_key_name'].unique().tolist())
    
    # Фильтры
    projects = ['Все'] + unique_projects
    selected_project = st.sidebar.selectbox("📁 Проект (app_name)", projects)
    
    api_keys = ['Все'] + unique_api_keys
    selected_api_key = st.sidebar.selectbox("🔑 API Key (api_key_name)", api_keys)
    
    models = ['Все'] + unique_models
    selected_model = st.sidebar.selectbox("🤖 Модель", models)
    
    # Применяем фильтры
    mask = (df['date'] >= date_range[0]) & (df['date'] <= date_range[1])
    if len(date_range) == 2:
        mask = (df['date'] >= date_range[0]) & (df['date'] <= date_range[1])
    else:
        mask = (df['date'] >= date_range[0])
    
    filtered_df = df[mask]
    
    if selected_project != 'Все':
        filtered_df = filtered_df[filtered_df['app_name'] == selected_project]
    
    if selected_api_key != 'Все':
        filtered_df = filtered_df[filtered_df['api_key_name'] == selected_api_key]
    
    if selected_model != 'Все':
        filtered_df = filtered_df[filtered_df['model_permaslug'] == selected_model]
    
    if len(filtered_df) == 0:
        st.warning("⚠️ Нет данных для выбранных фильтров.")
        st.stop()
    
    # ===== КЛЮЧЕВЫЕ МЕТРИКИ =====
    st.header(f"📈 Ключевые метрики ({currency_symbol})")
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    total_tokens = filtered_df['tokens_prompt'].sum() + filtered_df['tokens_completion'].sum()
    total_cost = filtered_df['cost_display'].sum()
    total_requests = len(filtered_df)
    avg_time = filtered_df['generation_time_ms'].mean()
    
    prompt_sum = filtered_df['tokens_prompt'].sum()
    completion_sum = filtered_df['tokens_completion'].sum()
    ratio = prompt_sum / completion_sum if completion_sum > 0 else 0
    
    with col1:
        st.metric("💰 Общая стоимость", f"{currency_symbol}{total_cost:,.2f}")
    with col2:
        st.metric("🎯 Всего токенов", f"{total_tokens:,}")
    with col3:
        st.metric("📞 Запросов", total_requests)
    with col4:
        st.metric("⚡ Среднее время", f"{avg_time:.0f} мс")
    with col5:
        st.metric("📊 Входящие/Исходящие", f"{ratio:.1f}")
    
    # ===== ГРАФИКИ =====
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader(f"💰 Расходы по дням ({currency_symbol})")
        daily_cost = filtered_df.groupby('date')['cost_display'].sum().reset_index()
        if len(daily_cost) > 0:
            fig = px.line(daily_cost, x='date', y='cost_display', title=f"Динамика затрат ({currency_symbol})")
            fig.update_layout(xaxis_title="Дата", yaxis_title=f"Стоимость ({currency_symbol})")
            st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.subheader("🎯 Токены по проектам")
        project_tokens = filtered_df.groupby('app_name').agg({
            'tokens_prompt': 'sum',
            'tokens_completion': 'sum'
        }).reset_index()
        project_tokens['total'] = project_tokens['tokens_prompt'] + project_tokens['tokens_completion']
        if len(project_tokens) > 0:
            fig = px.bar(project_tokens, x='app_name', y='total', title="Токены по проектам")
            fig.update_layout(xaxis_title="Проект", yaxis_title="Токены")
            st.plotly_chart(fig, use_container_width=True)
    
    col3, col4 = st.columns(2)
    
    with col3:
        st.subheader(f"🤖 Расходы по моделям ({currency_symbol})")
        model_cost = filtered_df.groupby('model_permaslug')['cost_display'].sum().reset_index()
        model_cost = model_cost.nlargest(10, 'cost_display')
        if len(model_cost) > 0:
            fig = px.pie(model_cost, values='cost_display', names='model_permaslug', title=f"Доля затрат по моделям ({currency_symbol})")
            st.plotly_chart(fig, use_container_width=True)
    
    with col4:
        st.subheader(f"🏢 Расходы по провайдерам ({currency_symbol})")
        provider_cost = filtered_df.groupby('provider_name')['cost_display'].sum().reset_index()
        if len(provider_cost) > 0:
            fig = px.bar(provider_cost, x='provider_name', y='cost_display', title=f"Затраты по провайдерам ({currency_symbol})")
            fig.update_layout(xaxis_title="Провайдер", yaxis_title=f"Стоимость ({currency_symbol})")
            st.plotly_chart(fig, use_container_width=True)
    
    # ===== ДЕТАЛЬНАЯ СТАТИСТИКА ПО МОДЕЛЯМ =====
    st.header(f"🎲 Детальная статистика по моделям ({currency_symbol})")
    
    model_details = filtered_df.groupby('model_permaslug').agg({
        'tokens_prompt': 'sum',
        'tokens_completion': 'sum',
        'cost_display': 'sum',
        'generation_id': 'count'
    }).round(2)
    
    model_details.columns = [
        'Входящие токены', 
        'Исходящие токены', 
        f'Стоимость ({currency_symbol})', 
        'Кол-во запросов'
    ]
    
    model_details['Всего токенов'] = model_details['Входящие токены'] + model_details['Исходящие токены']
    model_details['Доля токенов (%)'] = (model_details['Всего токенов'] / model_details['Всего токенов'].sum() * 100).round(1)
    model_details['Доля затрат (%)'] = (model_details[f'Стоимость ({currency_symbol})'] / model_details[f'Стоимость ({currency_symbol})'].sum() * 100).round(1)
    
    # Цены за 1 млн токенов с новыми названиями
    model_details[f'Ср. цена за 1M (общая) ({currency_symbol})'] = (
        model_details[f'Стоимость ({currency_symbol})'] / (model_details['Всего токенов'] + 1) * 1000000
    ).round(2)
    model_details[f'Ср. цена за 1M (входящие) ({currency_symbol})'] = (
        model_details[f'Стоимость ({currency_symbol})'] / (model_details['Входящие токены'] + 1) * 1000000
    ).round(2)
    model_details[f'Ср. цена за 1M (исходящие) ({currency_symbol})'] = (
        model_details[f'Стоимость ({currency_symbol})'] / (model_details['Исходящие токены'] + 1) * 1000000
    ).round(2)
    
    model_details[f'Ср. стоимость запроса ({currency_symbol})'] = (
        model_details[f'Стоимость ({currency_symbol})'] / model_details['Кол-во запросов']
    ).round(6)
    
    model_details = model_details.sort_values(f'Стоимость ({currency_symbol})', ascending=False)
    
    # Форматирование для отображения
    formatted_models = model_details.copy()
    for col in formatted_models.columns:
        if 'Ср. цена за 1M' in col:
            formatted_models[col] = formatted_models[col].apply(lambda x: f"{currency_symbol}{x:,.2f}")
        elif f'Стоимость ({currency_symbol})' in col and 'запроса' not in col:
            formatted_models[col] = formatted_models[col].apply(lambda x: f"{currency_symbol}{x:.2f}")
        elif f'Ср. стоимость запроса ({currency_symbol})' in col:
            formatted_models[col] = formatted_models[col].apply(lambda x: f"{currency_symbol}{x:.6f}")
        elif 'Доля' in col:
            formatted_models[col] = formatted_models[col].apply(lambda x: f"{x}%")
    
    st.dataframe(formatted_models, use_container_width=True)
    
    # ===== ДЕТАЛЬНАЯ ТАБЛИЦА ПО ПРОЕКТАМ =====
    st.subheader(f"📋 Детальная статистика по проектам ({currency_symbol})")
    
    project_details = filtered_df.groupby('app_name').agg({
        'tokens_prompt': 'sum',
        'tokens_completion': 'sum',
        'cost_display': 'sum',
        'generation_id': 'count',
        'generation_time_ms': 'mean'
    }).round(2)
    
    project_details.columns = [
        'Входящие токены', 
        'Исходящие токены', 
        f'Стоимость ({currency_symbol})', 
        'Запросы', 
        'Ср. время (мс)'
    ]
    project_details['Всего токенов'] = project_details['Входящие токены'] + project_details['Исходящие токены']
    project_details = project_details.sort_values(f'Стоимость ({currency_symbol})', ascending=False)
    
    # Форматирование
    formatted_projects = project_details.copy()
    formatted_projects[f'Стоимость ({currency_symbol})'] = formatted_projects[f'Стоимость ({currency_symbol})'].apply(lambda x: f"{currency_symbol}{x:.2f}")
    
    st.dataframe(formatted_projects, use_container_width=True)
    
    # ===== ДЕТАЛЬНАЯ ТАБЛИЦА ПО API-КЛЮЧАМ =====
    st.subheader(f"🔑 Детальная статистика по API-ключам ({currency_symbol})")
    
    api_key_details = filtered_df.groupby('api_key_name').agg({
        'tokens_prompt': 'sum',
        'tokens_completion': 'sum',
        'cost_display': 'sum',
        'generation_id': 'count',
        'app_name': lambda x: x.nunique(),
        'model_permaslug': lambda x: x.nunique(),
        'generation_time_ms': 'mean'
    }).round(2)
    
    api_key_details.columns = [
        'Входящие токены', 'Исходящие токены', f'Стоимость ({currency_symbol})', 
        'Запросы', 'Проектов', 'Моделей', 'Ср. время (мс)'
    ]
    api_key_details['Всего токенов'] = api_key_details['Входящие токены'] + api_key_details['Исходящие токены']
    api_key_details = api_key_details.sort_values(f'Стоимость ({currency_symbol})', ascending=False)
    
    formatted_keys = api_key_details.copy()
    formatted_keys[f'Стоимость ({currency_symbol})'] = formatted_keys[f'Стоимость ({currency_symbol})'].apply(lambda x: f"{currency_symbol}{x:.2f}")
    
    st.dataframe(formatted_keys, use_container_width=True)
    
    # ===== ТОП-10 САМЫХ ДОРОГИХ ЗАПРОСОВ =====
    st.subheader(f"💰 Топ-10 самых дорогих запросов ({currency_symbol})")
    
    available_cols = ['created_at', 'app_name', 'api_key_name', 'model_permaslug', 
                      'tokens_prompt', 'tokens_completion', 'cost_display', 'generation_time_ms']
    
    expensive = filtered_df.nlargest(10, 'cost_display')[available_cols]
    expensive.columns = ['Время', 'Проект', 'API Key', 'Модель', 'Входящие', 'Исходящие', f'Стоимость ({currency_symbol})', 'Время (мс)']
    
    # Форматирование
    expensive[f'Стоимость ({currency_symbol})'] = expensive[f'Стоимость ({currency_symbol})'].apply(lambda x: f"{currency_symbol}{x:.4f}")
    
    st.dataframe(expensive, use_container_width=True)
    
    # ===== ГРАФИК РАСХОДОВ ПО API-КЛЮЧАМ =====
    st.subheader(f"🔑 Расходы по API-ключам ({currency_symbol})")
    
    api_key_cost = filtered_df.groupby('api_key_name')['cost_display'].sum().reset_index()
    api_key_cost = api_key_cost.sort_values('cost_display', ascending=False)
    if len(api_key_cost) > 0:
        fig = px.bar(api_key_cost.head(10), x='api_key_name', y='cost_display', 
                    title=f"Топ-10 API-ключей по затратам ({currency_symbol})")
        fig.update_layout(xaxis_title="API Key", yaxis_title=f"Стоимость ({currency_symbol})")
        st.plotly_chart(fig, use_container_width=True)
    
    # ===== ЭКСПОРТ =====
    st.subheader("📥 Экспорт отчёта")
    
    output = io.BytesIO()
    try:
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            filtered_df.to_excel(writer, sheet_name='Все данные', index=False)
            model_details.to_excel(writer, sheet_name='Статистика по моделям')
            project_details.to_excel(writer, sheet_name='Статистика по проектам')
            api_key_details.to_excel(writer, sheet_name='Статистика по API-ключам')
            expensive.to_excel(writer, sheet_name='Топ запросов', index=False)
            if len(daily_cost) > 0:
                daily_cost.to_excel(writer, sheet_name='Расходы по дням', index=False)
        
        st.download_button(
            label="📊 Скачать Excel отчёт",
            data=output.getvalue(),
            file_name=f"token_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except Exception as e:
        st.error(f"Ошибка при создании Excel: {e}")
    
    # ===== СТАТИСТИКА В САЙДБАРЕ =====
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📊 Статистика")
    st.sidebar.markdown(f"**Записей:** {len(filtered_df):,}")
    st.sidebar.markdown(f"**Уникальных проектов:** {filtered_df['app_name'].nunique()}")
    st.sidebar.markdown(f"**Уникальных API-ключей:** {filtered_df['api_key_name'].nunique()}")
    st.sidebar.markdown(f"**Уникальных моделей:** {filtered_df['model_permaslug'].nunique()}")
    
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**Период:** {filtered_df['date'].min()} → {filtered_df['date'].max()}")
    st.sidebar.markdown(f"**Всего токенов:** {total_tokens:,}")

else:
    st.info("👈 Загрузите CSV файл с логами для начала анализа")
    
    st.markdown("""
    ### Как использовать:
    1. Подготовьте CSV файл с вашими логами
    2. Нажмите "Browse files" выше
    3. Выберите файл
    4. Используйте фильтры слева
    
    ### 💱 Выбор валюты:
    - **Включите чекбокс** "Показывать цены в рублях" для отображения всех цен в рублях
    - **Выключите чекбокс** для отображения цен в долларах США
    - При выборе рублей, курсы автоматически загружаются с API ЦБ РФ
    - Конвертация происходит по курсу на **дату каждой операции**
    
    ### 📊 Что означают колонки в статистике по моделям:
    - **Входящие токены** - токены, отправленные в API (prompt)
    - **Исходящие токены** - токены, полученные от API (completion)
    - **Ср. цена за 1M (общая)** - средняя фактическая цена за 1 млн всех токенов
    - **Ср. цена за 1M (входящие)** - средняя фактическая цена за 1 млн входящих токенов
    - **Ср. цена за 1M (исходящие)** - средняя фактическая цена за 1 млн исходящих токенов
    
    ### Ожидаемая структура CSV:
    - `created_at` - дата и время запроса
    - `tokens_prompt` - входящие токены
    - `tokens_completion` - исходящие токены
    - `cost_total` - общая стоимость в USD
    - `app_name` - название проекта
    - `api_key_name` - название API-ключа
    - `model_permaslug` - модель ИИ
    - `provider_name` - провайдер
    - `generation_time_ms` - время ответа
    """)