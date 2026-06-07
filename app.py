import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import io
import requests
import time
import xml.etree.ElementTree as ET
import plotly.io as pio

import sys
import warnings
warnings.filterwarnings('ignore')

# Настройка страницы
st.set_page_config(page_title="Анализ токенов ИИ", layout="wide")
st.title("🤖 Дашборд аналитики токенов ИИ")

# Функция для отображения инструкции
def show_instructions():
    st.markdown("""
    ### 📚 Как использовать дашборд:
    
    1. **Подготовьте CSV файл** с вашими логами
    2. **Нажмите "Upload CSV файл"** выше
    3. **Выберите файл** для загрузки
    4. **Используйте фильтры** в левой боковой панели
    
    ### 💱 Выбор валюты:
    - Включите чекбокс **"Показывать цены в рублях"**
    - Используются официальные курсы ЦБ РФ (код валюты: USD (R01235))
    - Каждая операция пересчитывается по курсу на **ДЕНЬ операции**
    
    ### 📈 Что вы получите:
    - Ключевые метрики (стоимость, токены, запросы)
    - Графики динамики затрат и распределения токенов
    - Детальную статистику по моделям, проектам и API-ключам
    - Тепловую карту затрат по API-ключам
    - Топ-10 самых дорогих запросов
    - Экспорт отчётов в HTML и CSV с цветными графиками
    """)

# Функция для получения курса USD на конкретную дату
def get_usd_rate_cbr(target_date):
    if isinstance(target_date, (datetime, pd.Timestamp)):
        date_obj = target_date
    else:
        date_obj = target_date
    
    date_str = date_obj.strftime('%d/%m/%Y')
    url = f"https://cbr.ru/scripts/XML_daily.asp?date_req={date_str}"
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xml;q=0.9,*/*;q=0.8',
        }
        
        response = requests.get(url, timeout=15, headers=headers)
        
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            
            for valute in root.findall('.//Valute'):
                char_code = valute.find('CharCode')
                if char_code is not None and char_code.text == 'USD':
                    value = valute.find('Value')
                    if value is not None:
                        rate_str = value.text.replace(',', '.')
                        rate = float(rate_str)
                        return rate
        return None
    except Exception as e:
        return None

# Функция для загрузки курсов с прогресс-баром
@st.cache_data(ttl=3600)
def load_rates_for_dates(dates_list):
    rates = {}
    sorted_dates = sorted(dates_list)
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for i, date_obj in enumerate(sorted_dates):
        progress = (i + 1) / len(sorted_dates)
        progress_bar.progress(progress, text=f"Загрузка курсов: {i+1}/{len(sorted_dates)}")
        status_text.info(f"📅 {date_obj.strftime('%d.%m.%Y')}")
        
        rate = get_usd_rate_cbr(date_obj)
        if rate is not None:
            rates[date_obj] = rate
        else:
            rates[date_obj] = None
        
        time.sleep(0.05)
    
    progress_bar.empty()
    status_text.empty()
    st.success(f"✅ Загружено {len(sorted_dates)} курсов")
    time.sleep(0.5)
    st.empty()
    
    # Интерполяция пропущенных значений
    rates_df = pd.DataFrame([{"date": k, "rate": v} for k, v in rates.items()])
    rates_df['date'] = pd.to_datetime(rates_df['date'])
    rates_df = rates_df.sort_values('date')
    rates_df['rate'] = rates_df['rate'].ffill().bfill()
    
    if rates_df['rate'].isna().any():
        rates_df['rate'] = rates_df['rate'].fillna(90.0)
    
    return dict(zip(rates_df['date'].dt.date, rates_df['rate']))

# Функция для переименования API-ключей
def rename_api_keys(api_key_name):
    rename_map = {
        'key_1': 'Бета стенд (Юрченко)',
        'key_2': 'Дообучение (Соколов)',
        'key_3': 'Разработка (Юрченко)',
        'key_4': 'Разработка (Мошков)',
        'key_5': 'Мейн стенд (Юрченко, Ильинов)',
        'key_6': 'Агент подписки (Мамедов)',
        'key_7': 'Аргумент (Кошелев)'
    }
    return rename_map.get(api_key_name, api_key_name)

# Функция для создания цветных графиков для HTML отчёта
def create_colored_charts(df, currency_symbol):
    """Создание цветных графиков для HTML отчёта"""
    
    # График 1: Динамика затрат
    daily_cost = df.groupby('date')['cost_display'].sum().reset_index()
    fig_cost = go.Figure()
    fig_cost.add_trace(go.Scatter(
        x=daily_cost['date'],
        y=daily_cost['cost_display'],
        mode='lines+markers',
        name='Затраты',
        line=dict(color='#667eea', width=3),
        marker=dict(size=8, color='#764ba2', symbol='circle')
    ))
    fig_cost.update_layout(
        title=f'<b>Динамика затрат ({currency_symbol})</b>',
        xaxis_title='Дата',
        yaxis_title=f'Стоимость ({currency_symbol})',
        hovermode='x unified',
        plot_bgcolor='white',
        paper_bgcolor='white',
        title_font_size=16,
        title_font_color='#2c3e50',
        height=400
    )
    fig_cost.update_xaxes(showgrid=True, gridwidth=1, gridcolor='#e0e0e0')
    fig_cost.update_yaxes(showgrid=True, gridwidth=1, gridcolor='#e0e0e0')
    
    # График 2: Распределение токенов
    token_data = []
    token_colors = []
    if df['tokens_prompt'].sum() > 0:
        token_data.append(('Входящие', df['tokens_prompt'].sum()))
        token_colors.append('#667eea')
    if df['tokens_completion'].sum() > 0:
        token_data.append(('Исходящие', df['tokens_completion'].sum()))
        token_colors.append('#764ba2')
    if df['tokens_reasoning'].sum() > 0:
        token_data.append(('Рассуждений', df['tokens_reasoning'].sum()))
        token_colors.append('#f093fb')
    if df['tokens_cached'].sum() > 0:
        token_data.append(('Кэшированные', df['tokens_cached'].sum()))
        token_colors.append('#4facfe')
    
    fig_pie = go.Figure(data=[go.Pie(
        labels=[item[0] for item in token_data],
        values=[item[1] for item in token_data],
        marker=dict(colors=token_colors),
        hole=0.3,
        textinfo='percent+label',
        textposition='auto'
    )])
    fig_pie.update_layout(
        title='<b>Распределение токенов по типам</b>',
        plot_bgcolor='white',
        paper_bgcolor='white',
        title_font_size=16,
        title_font_color='#2c3e50',
        height=450
    )
    
    # График 3: Расходы по моделям
    model_cost = df.groupby('model_permaslug')['cost_display'].sum().reset_index()
    model_cost = model_cost.nlargest(10, 'cost_display')
    colors_model = ['#667eea', '#764ba2', '#f093fb', '#4facfe', '#43e97b', '#fa709a', '#fee140', '#30cfd0', '#a8edea', '#fed6e3']
    
    fig_models = go.Figure(data=[go.Pie(
        labels=model_cost['model_permaslug'],
        values=model_cost['cost_display'],
        marker=dict(colors=colors_model[:len(model_cost)]),
        textinfo='percent+label',
        textposition='auto'
    )])
    fig_models.update_layout(
        title=f'<b>Доля затрат по моделям ({currency_symbol})</b>',
        plot_bgcolor='white',
        paper_bgcolor='white',
        title_font_size=16,
        title_font_color='#2c3e50',
        height=450
    )
    
    # График 4: Тепловая карта по API-ключам
    api_daily = df.groupby(['api_key_name', 'date'])['cost_display'].sum().reset_index()
    pivot_api = api_daily.pivot(index='api_key_name', columns='date', values='cost_display').fillna(0)
    
    if len(pivot_api) > 0:
        fig_heatmap = go.Figure(data=go.Heatmap(
            z=pivot_api.values,
            x=[d.strftime('%d.%m') for d in pivot_api.columns],
            y=pivot_api.index,
            colorscale='Viridis',
            text=pivot_api.values.round(2),
            texttemplate='%{text}',
            textfont={"size": 10},
            hoverongaps=False
        ))
        fig_heatmap.update_layout(
            title=f'<b>Тепловая карта затрат по API-ключам ({currency_symbol})</b>',
            xaxis_title='Дата',
            yaxis_title='API-ключ',
            plot_bgcolor='white',
            paper_bgcolor='white',
            title_font_size=16,
            title_font_color='#2c3e50',
            height=400
        )
        heatmap_html = pio.to_html(fig_heatmap, full_html=False, include_plotlyjs=False)
    else:
        heatmap_html = "<p>Нет данных для тепловой карты</p>"
    
    # График 5: Расходы по провайдерам
    provider_cost = df.groupby('provider_name')['cost_display'].sum().reset_index()
    fig_providers = go.Figure()
    fig_providers.add_trace(go.Bar(
        x=provider_cost['provider_name'],
        y=provider_cost['cost_display'],
        marker_color='#667eea',
        text=provider_cost['cost_display'].apply(lambda x: f'{currency_symbol}{x:,.2f}'),
        textposition='outside'
    ))
    fig_providers.update_layout(
        title=f'<b>Затраты по провайдерам ({currency_symbol})</b>',
        xaxis_title='Провайдер',
        yaxis_title=f'Стоимость ({currency_symbol})',
        plot_bgcolor='white',
        paper_bgcolor='white',
        title_font_size=16,
        title_font_color='#2c3e50',
        height=400
    )
    fig_providers.update_xaxes(tickangle=-45, showgrid=True, gridwidth=1, gridcolor='#e0e0e0')
    fig_providers.update_yaxes(showgrid=True, gridwidth=1, gridcolor='#e0e0e0')
    
    # Конвертируем в HTML
    cost_graph_html = pio.to_html(fig_cost, full_html=False, include_plotlyjs='cdn')
    pie_graph_html = pio.to_html(fig_pie, full_html=False, include_plotlyjs=False)
    models_graph_html = pio.to_html(fig_models, full_html=False, include_plotlyjs=False)
    providers_graph_html = pio.to_html(fig_providers, full_html=False, include_plotlyjs=False)
    
    return cost_graph_html, pie_graph_html, models_graph_html, heatmap_html, providers_graph_html

# Функция для создания HTML-отчёта с цветными графиками
def create_html_report(df, model_details, project_details, api_key_details, expensive, currency_symbol):
    report_date = datetime.now().strftime('%d.%m.%Y %H:%M:%S')
    
    # Создаем цветные графики
    cost_graph_html, pie_graph_html, models_graph_html, heatmap_html, providers_graph_html = create_colored_charts(df, currency_symbol)
    
    # Подготовка таблиц
    model_display = model_details.copy()
    project_display = project_details.copy()
    api_display = api_key_details.copy()
    expensive_display = expensive.copy()
    
    for col in model_display.columns:
        if 'Стоимость' in col:
            model_display[col] = model_display[col].apply(lambda x: f"{currency_symbol}{x:,.2f}")
        if 'токены' in col or 'Всего' in col:
            model_display[col] = model_display[col].apply(lambda x: f"{x:,}")
    
    for col in project_display.columns:
        if 'Стоимость' in col:
            project_display[col] = project_display[col].apply(lambda x: f"{currency_symbol}{x:,.2f}")
        if 'токены' in col or 'Всего' in col:
            project_display[col] = project_display[col].apply(lambda x: f"{x:,}")
    
    for col in api_display.columns:
        if 'Стоимость' in col:
            api_display[col] = api_display[col].apply(lambda x: f"{currency_symbol}{x:,.2f}")
        if 'токены' in col or 'Всего' in col:
            api_display[col] = api_display[col].apply(lambda x: f"{x:,}")
    
    for col in expensive_display.columns:
        if 'Стоимость' in col:
            expensive_display[col] = expensive_display[col].apply(lambda x: f"{currency_symbol}{x:.4f}")
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Отчёт по использованию AI-моделей</title>
        <script src="https://cdn.plot.ly/plotly-3.0.1.min.js" charset="utf-8"></script>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                padding: 20px;
            }}
            .report {{
                max-width: 1400px;
                margin: 0 auto;
                background: white;
                border-radius: 20px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                overflow: hidden;
            }}
            .header {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 40px;
                text-align: center;
            }}
            .header h1 {{ font-size: 32px; margin-bottom: 10px; }}
            .header p {{ opacity: 0.9; font-size: 14px; }}
            .content {{ padding: 30px; }}
            h2 {{
                color: #2c3e50;
                font-size: 24px;
                margin: 30px 0 15px 0;
                padding-bottom: 10px;
                border-bottom: 3px solid #667eea;
            }}
            h3 {{
                color: #2c3e50;
                font-size: 20px;
                margin: 20px 0 15px 0;
            }}
            .metrics {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 20px;
                margin: 20px 0;
            }}
            .metric {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 20px;
                border-radius: 15px;
                text-align: center;
                transition: transform 0.3s;
            }}
            .metric:hover {{
                transform: translateY(-5px);
            }}
            .metric-value {{ font-size: 28px; font-weight: bold; margin-bottom: 8px; }}
            .metric-label {{ font-size: 13px; opacity: 0.9; }}
            .graph-container {{
                margin: 30px 0;
                padding: 20px;
                background: #f8f9fa;
                border-radius: 15px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin: 15px 0;
                font-size: 13px;
            }}
            th {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 12px;
                text-align: left;
            }}
            td {{
                padding: 10px 12px;
                border-bottom: 1px solid #e0e0e0;
            }}
            tr:hover td {{ background-color: #f5f5f5; }}
            .footer {{
                background: #f8f9fa;
                padding: 20px;
                text-align: center;
                font-size: 12px;
                color: #666;
            }}
            @media print {{
                body {{
                    background: white;
                    padding: 0;
                }}
                .graph-container {{
                    break-inside: avoid;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="report">
            <div class="header">
                <h1>🤖 Отчёт по использованию AI-моделей</h1>
                <p>📅 Дата формирования: {report_date}</p>
                <p>📊 Период: {df['date'].min()} → {df['date'].max()}</p>
                <p>💱 Валюта: {currency_symbol}</p>
            </div>
            
            <div class="content">
                <div class="metrics">
                    <div class="metric">
                        <div class="metric-value">{currency_symbol}{df['cost_display'].sum():,.2f}</div>
                        <div class="metric-label">Общая стоимость</div>
                    </div>
                    <div class="metric">
                        <div class="metric-value">{df['total_tokens'].sum():,}</div>
                        <div class="metric-label">Всего токенов</div>
                    </div>
                    <div class="metric">
                        <div class="metric-value">{len(df):,}</div>
                        <div class="metric-label">Запросов</div>
                    </div>
                    <div class="metric">
                        <div class="metric-value">{df['generation_time_ms'].mean():.0f} мс</div>
                        <div class="metric-label">Среднее время</div>
                    </div>
                </div>
                
                <h2>📈 Визуализация данных</h2>
                
                <div class="graph-container">
                    <h3>💰 Динамика затрат</h3>
                    {cost_graph_html}
                </div>
                
                <div class="graph-container">
                    <h3>🎯 Распределение токенов по типам</h3>
                    {pie_graph_html}
                </div>
                
                <div class="graph-container">
                    <h3>🤖 Доля затрат по моделям</h3>
                    {models_graph_html}
                </div>
                
                <div class="graph-container">
                    <h3>🏢 Затраты по провайдерам</h3>
                    {providers_graph_html}
                </div>
                
                <div class="graph-container">
                    <h3>🔥 Тепловая карта затрат по API-ключам</h3>
                    {heatmap_html}
                </div>
                
                <h2>🎲 Детальная статистика по моделям</h2>
                {model_display.to_html(index=False)}
                
                <h2>📋 Детальная статистика по проектам</h2>
                {project_display.to_html(index=False)}
                
                <h2>🔑 Детальная статистика по API-ключам</h2>
                {api_display.to_html(index=False)}
                
                <h2>💰 Топ-10 самых дорогих запросов</h2>
                {expensive_display.to_html(index=False)}
            </div>
            
            <div class="footer">
                <p>🤖 Отчёт сгенерирован автоматически дашбордом аналитики токенов ИИ</p>
                <p style="margin-top: 10px">📊 Все графики интерактивны - наводите курсор для деталей</p>
            </div>
        </div>
    </body>
    </html>
    """
    return html

# Загрузка файла
uploaded_file = st.file_uploader("Upload CSV файл", type=['csv'])

if uploaded_file is None:
    with st.expander("📋 Пример ожидаемого формата CSV", expanded=False):
        st.markdown("""
        **CSV файл должен содержать следующие колонки:**
        - `created_at` - дата и время запроса
        - `app_name` - название проекта
        - `api_key_name` - идентификатор API-ключа
        - `model_permaslug` - название модели
        - `provider_name` - провайдер модели
        - `tokens_prompt` - входящие токены
        - `tokens_completion` - исходящие токены
        - `tokens_reasoning` - токены рассуждений
        - `tokens_cached` - кэшированные токены
        - `cost_total` - стоимость в USD
        - `generation_time_ms` - время генерации
        - `generation_id` - ID запроса
        """)
    
    show_instructions()

if uploaded_file is not None:
    try:
        with st.spinner("📊 Загрузка и обработка данных..."):
            df = pd.read_csv(uploaded_file)
            
            if 'api_key_name' in df.columns:
                df['api_key_name'] = df['api_key_name'].apply(rename_api_keys)
            
            # Пробуем разные форматы дат
            try:
                df['created_at'] = pd.to_datetime(df['created_at'], format='%Y-%m-%d %H:%M:%S.%f')
            except:
                try:
                    df['created_at'] = pd.to_datetime(df['created_at'])
                except:
                    st.error("❌ Не удалось распознать формат даты в колонке 'created_at'")
                    st.stop()
            
            df['date'] = df['created_at'].dt.date
            
            df['app_name'] = df['app_name'].fillna('unknown').astype(str)
            df['app_name'] = df['app_name'].replace('nan', 'unknown').replace('None', 'unknown')
            df['api_key_name'] = df['api_key_name'].fillna('unknown').astype(str)
            df['api_key_name'] = df['api_key_name'].replace('nan', 'unknown').replace('None', 'unknown')
            df['model_permaslug'] = df['model_permaslug'].fillna('unknown').astype(str)
            df['provider_name'] = df['provider_name'].fillna('unknown').astype(str)
            
            df['tokens_prompt'] = pd.to_numeric(df['tokens_prompt'], errors='coerce').fillna(0)
            df['tokens_completion'] = pd.to_numeric(df['tokens_completion'], errors='coerce').fillna(0)
            df['tokens_cached'] = pd.to_numeric(df['tokens_cached'], errors='coerce').fillna(0)
            df['tokens_reasoning'] = pd.to_numeric(df['tokens_reasoning'], errors='coerce').fillna(0)
            df['cost_total'] = pd.to_numeric(df['cost_total'], errors='coerce').fillna(0)
            df['generation_time_ms'] = pd.to_numeric(df['generation_time_ms'], errors='coerce').fillna(0)
            
            df['total_tokens'] = (df['tokens_prompt'] + df['tokens_completion'] + 
                                  df['tokens_reasoning'] + df['tokens_cached'])
        
        # Фильтры
        st.sidebar.header("Фильтры")
        
        min_date = df['date'].min()
        max_date = df['date'].max()
        date_range = st.sidebar.date_input("Период", [min_date, max_date], min_value=min_date, max_value=max_date)
        
        selected_project = st.sidebar.selectbox("Проект", ['Все'] + sorted(df['app_name'].unique()))
        selected_api_key = st.sidebar.selectbox("API-ключ", ['Все'] + sorted(df['api_key_name'].unique()))
        selected_model = st.sidebar.selectbox("Модель", ['Все'] + sorted(df['model_permaslug'].unique()))
        
        mask = (df['date'] >= date_range[0]) & (df['date'] <= date_range[1])
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
        
        # Выбор валюты
        st.sidebar.markdown("---")
        st.sidebar.header("Настройки валюты")
        
        use_rub = st.sidebar.checkbox("Показывать цены в рублях", value=False)
        
        if use_rub:
            unique_dates_list = sorted(filtered_df['date'].unique())
            rates_dict = load_rates_for_dates(unique_dates_list)
            
            if rates_dict and any(v is not None for v in rates_dict.values()):
                filtered_df['usd_rate'] = filtered_df['date'].apply(lambda x: rates_dict.get(x, 90.0))
                filtered_df['cost_display'] = filtered_df['cost_total'] * filtered_df['usd_rate']
                currency_symbol = "₽"
                rates_history = filtered_df[['date', 'usd_rate']].drop_duplicates().sort_values('date').copy()
                st.sidebar.success(f"✅ Загружены курсы для {len(rates_history)} дат")
            else:
                st.sidebar.error("❌ Не удалось загрузить курсы. Используются доллары.")
                use_rub = False
                filtered_df['cost_display'] = filtered_df['cost_total']
                currency_symbol = "$"
        else:
            filtered_df['cost_display'] = filtered_df['cost_total']
            currency_symbol = "$"
        
        # Динамика курса валют
        if use_rub and 'rates_history' in locals() and len(rates_history) > 0:
            st.subheader("📈 Динамика курса USD по дням")
            
            fig_rates = px.line(rates_history, x='date', y='usd_rate', title="Курс USD к RUB", markers=True)
            fig_rates.update_layout(xaxis_title="Дата", yaxis_title="Курс (₽)", hovermode='x unified', height=400)
            avg_rate = rates_history['usd_rate'].mean()
            fig_rates.add_hline(y=avg_rate, line_dash="dash", line_color="green", annotation_text=f"Средний: {avg_rate:.2f} ₽")
            st.plotly_chart(fig_rates, use_container_width=True)
            
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Курс на последнюю дату", f"{rates_history['usd_rate'].iloc[-1]:.2f} ₽")
            with col2:
                st.metric("Минимальный курс", f"{rates_history['usd_rate'].min():.2f} ₽")
            with col3:
                st.metric("Максимальный курс", f"{rates_history['usd_rate'].max():.2f} ₽")
            with col4:
                st.metric("Средний курс", f"{avg_rate:.2f} ₽")
        
        # Ключевые метрики
        st.header(f"📈 Ключевые метрики ({currency_symbol})")
        
        total_tokens = filtered_df['total_tokens'].sum()
        total_cost = filtered_df['cost_display'].sum()
        total_requests = len(filtered_df)
        avg_time = filtered_df['generation_time_ms'].mean()
        
        total_prompt = filtered_df['tokens_prompt'].sum()
        total_completion = filtered_df['tokens_completion'].sum()
        total_reasoning = filtered_df['tokens_reasoning'].sum()
        total_cached = filtered_df['tokens_cached'].sum()
        ratio = total_prompt / total_completion if total_completion > 0 else 0
        
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("💰 Общая стоимость", f"{currency_symbol}{total_cost:,.2f}")
        with col2:
            st.metric("🎯 Всего токенов", f"{total_tokens:,}")
        with col3:
            st.metric("📞 Запросов", total_requests)
        with col4:
            st.metric("⚡ Среднее время", f"{avg_time:.0f} мс")
        with col5:
            st.metric("📊 Вх/Исх", f"{ratio:.1f}")
        
        st.caption(f"**Детализация токенов:** Входящие: {total_prompt:,} | Исходящие: {total_completion:,} | Токены рассуждений: {total_reasoning:,} | Кэшированные токены: {total_cached:,}")
        
        # Графики
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader(f"💰 Расходы по дням ({currency_symbol})")
            daily_cost = filtered_df.groupby('date')['cost_display'].sum().reset_index()
            if len(daily_cost) > 0:
                fig = px.line(daily_cost, x='date', y='cost_display', title=f"Динамика затрат ({currency_symbol})", markers=True)
                fig.update_layout(xaxis_title="Дата", yaxis_title=f"Стоимость ({currency_symbol})")
                st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            st.subheader("🎯 Распределение токенов по типам")
            token_distribution = pd.DataFrame({
                'Тип токенов': ['Входящие', 'Исходящие', 'Токены рассуждений', 'Кэшированные'],
                'Количество': [total_prompt, total_completion, total_reasoning, total_cached]
            })
            token_distribution = token_distribution[token_distribution['Количество'] > 0]
            if len(token_distribution) > 0:
                fig = px.pie(token_distribution, values='Количество', names='Тип токенов', 
                            title="Распределение токенов по типам")
                st.plotly_chart(fig, use_container_width=True)
        
        # Детализация расходов по дням
        if len(daily_cost) > 0:
            with st.expander("📊 Детализация расходов по дням", expanded=False):
                daily_detail = filtered_df.groupby('date').agg({
                    'cost_display': 'sum',
                    'generation_id': 'count',
                    'model_permaslug': 'nunique',
                    'api_key_name': 'nunique',
                    'app_name': 'nunique',
                    'tokens_prompt': 'sum',
                    'tokens_completion': 'sum',
                    'tokens_reasoning': 'sum',
                    'tokens_cached': 'sum',
                    'total_tokens': 'sum'
                }).reset_index()
                
                daily_detail = daily_detail.sort_values('date')
                daily_detail['date'] = pd.to_datetime(daily_detail['date']).dt.strftime('%d.%m.%Y')
                
                total_sum = daily_detail['cost_display'].sum()
                daily_detail['Доля затрат'] = (daily_detail['cost_display'] / total_sum * 100).round(2)
                
                daily_detail.columns = [
                    'Дата', 'Стоимость', 'Запросы', 'Модели', 'API-ключи', 'Проекты',
                    'Входящие', 'Исходящие', 'Рассуждений', 'Кэшированные', 'Всего токенов', 'Доля затрат (%)'
                ]
                
                daily_detail['Стоимость'] = daily_detail['Стоимость'].apply(lambda x: f"{currency_symbol}{x:,.2f}")
                daily_detail['Доля затрат (%)'] = daily_detail['Доля затрат (%)'].apply(lambda x: f"{x:.2f}%")
                
                for col in ['Запросы', 'Модели', 'API-ключи', 'Проекты', 'Входящие', 'Исходящие', 'Рассуждений', 'Кэшированные', 'Всего токенов']:
                    daily_detail[col] = daily_detail[col].apply(lambda x: f"{int(x):,}")
                
                st.dataframe(daily_detail, use_container_width=True, hide_index=True)
                
                st.markdown("---")
                col_a, col_b, col_c, col_d = st.columns(4)
                with col_a:
                    st.metric("📅 Всего дней", len(daily_detail))
                with col_b:
                    st.metric("💰 Общая стоимость", f"{currency_symbol}{total_sum:,.2f}")
                with col_c:
                    st.metric("📊 Всего запросов", f"{filtered_df['generation_id'].count():,}")
                with col_d:
                    st.metric("🤖 Уникальных моделей", filtered_df['model_permaslug'].nunique())
        
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
        
        # Детальная статистика по моделям
        st.header(f"🎲 Детальная статистика по моделям ({currency_symbol})")
        model_details = filtered_df.groupby('model_permaslug').agg({
            'tokens_prompt': 'sum', 'tokens_completion': 'sum', 'tokens_reasoning': 'sum', 'tokens_cached': 'sum',
            'cost_display': 'sum', 'generation_id': 'count'
        }).round(2).reset_index()
        model_details.columns = ['ИИ-модель', 'Входящие', 'Исходящие', 'Рассуждений', 'Кэшированные', f'Стоимость ({currency_symbol})', 'Запросы']
        model_details['Всего токенов'] = model_details['Входящие'] + model_details['Исходящие'] + model_details['Рассуждений'] + model_details['Кэшированные']
        model_details = model_details.sort_values(f'Стоимость ({currency_symbol})', ascending=False)
        st.dataframe(model_details, use_container_width=True, hide_index=True)
        
        # Детальная статистика по проектам
        st.subheader(f"📋 Детальная статистика по проектам ({currency_symbol})")
        project_main_key = filtered_df.groupby('app_name')['api_key_name'].agg(lambda x: x.mode()[0] if len(x.mode()) > 0 else 'unknown')
        project_details = filtered_df.groupby('app_name').agg({
            'tokens_prompt': 'sum', 'tokens_completion': 'sum', 'tokens_reasoning': 'sum', 'tokens_cached': 'sum',
            'cost_display': 'sum', 'generation_id': 'count', 'generation_time_ms': 'mean'
        }).round(2).reset_index()
        project_details = project_details.rename(columns={'app_name': 'Проект'})
        project_details.insert(1, 'API-ключ', project_details['Проект'].map(project_main_key))
        project_details.columns = ['Проект', 'API-ключ', 'Входящие', 'Исходящие', 'Рассуждений', 'Кэшированные', f'Стоимость ({currency_symbol})', 'Запросы', 'Ср.время(мс)']
        project_details['Всего токенов'] = project_details['Входящие'] + project_details['Исходящие'] + project_details['Рассуждений'] + project_details['Кэшированные']
        project_details = project_details.sort_values(f'Стоимость ({currency_symbol})', ascending=False)
        st.dataframe(project_details, use_container_width=True, hide_index=True)
        
        # Аналитика по API-ключам
        st.header(f"🔑 Аналитика по API-ключам ({currency_symbol})")
        
        api_details = filtered_df.groupby('api_key_name').agg({
            'tokens_prompt': 'sum', 'tokens_completion': 'sum', 'tokens_reasoning': 'sum', 'tokens_cached': 'sum',
            'cost_display': 'sum', 'generation_id': 'count', 'app_name': 'nunique', 'model_permaslug': 'nunique', 'generation_time_ms': 'mean'
        }).round(2).reset_index()
        api_details.columns = ['API-ключ', 'Входящие', 'Исходящие', 'Рассуждений', 'Кэшированные', f'Стоимость ({currency_symbol})', 'Запросы', 'Проектов', 'Моделей', 'Ср.время(мс)']
        api_details['Всего токенов'] = api_details['Входящие'] + api_details['Исходящие'] + api_details['Рассуждений'] + api_details['Кэшированные']
        api_details = api_details.sort_values(f'Стоимость ({currency_symbol})', ascending=False)
        
        tab1, tab2, tab3 = st.tabs(["📊 Таблица", "📈 Графики", "🔥 Тепловая карта"])
        
        with tab1:
            st.dataframe(api_details, use_container_width=True, hide_index=True)
            st.subheader("🏆 Топ-5 затратных ключей")
            st.dataframe(api_details.head(5)[['API-ключ', f'Стоимость ({currency_symbol})', 'Запросы', 'Проектов']], use_container_width=True, hide_index=True)
        
        with tab2:
            fig_cost = px.bar(api_details.head(10), x='API-ключ', y=f'Стоимость ({currency_symbol})', title="Топ-10 по затратам", text=f'Стоимость ({currency_symbol})')
            fig_cost.update_traces(texttemplate='%{text:.2f}', textposition='outside')
            fig_cost.update_layout(xaxis_tickangle=-45)
            st.plotly_chart(fig_cost, use_container_width=True)
            
            fig_req = px.bar(api_details.head(10), x='API-ключ', y='Запросы', title="Топ-10 по запросам", text='Запросы')
            fig_req.update_traces(texttemplate='%{text:,}', textposition='outside')
            fig_req.update_layout(xaxis_tickangle=-45)
            st.plotly_chart(fig_req, use_container_width=True)
        
        with tab3:
            api_daily = filtered_df.groupby(['api_key_name', 'date'])['cost_display'].sum().reset_index()
            pivot_api = api_daily.pivot(index='api_key_name', columns='date', values='cost_display').fillna(0)
            if len(pivot_api) > 0:
                fig_heat = px.imshow(pivot_api, labels=dict(x="Дата", y="API-ключ", color=f"Стоимость ({currency_symbol})"), aspect="auto", color_continuous_scale="Viridis")
                st.plotly_chart(fig_heat, use_container_width=True)
        
        # Топ-10 дорогих запросов
        st.header(f"💰 Топ-10 самых дорогих запросов ({currency_symbol})")
        top_cols = ['created_at', 'app_name', 'api_key_name', 'model_permaslug', 'tokens_prompt', 'tokens_completion', 'tokens_reasoning', 'tokens_cached', 'cost_display', 'generation_time_ms', 'generation_id']
        expensive = filtered_df.nlargest(10, 'cost_display')[top_cols].copy().reset_index(drop=True)
        expensive.columns = ['Дата и время', 'Проект', 'API-ключ', 'Модель', 'Входящие', 'Исходящие', 'Рассуждений', 'Кэшированные', f'Стоимость ({currency_symbol})', 'Время (мс)', 'ID запроса']
        st.dataframe(expensive, use_container_width=True, hide_index=True)
        
        # Экспорт отчёта
        st.header("📥 Экспорт отчёта")
        
        # Подготовка данных для экспорта
        model_details_export = model_details.copy()
        project_details_export = project_details.copy()
        api_details_export = api_details.copy()
        expensive_export = expensive.copy()
        
        html_report = create_html_report(filtered_df, model_details_export, project_details_export, 
                                         api_details_export, expensive_export, currency_symbol)
        
        col1, col2 = st.columns(2)
        with col1:
            st.download_button("📄 Скачать HTML отчёт", 
                              html_report.encode('utf-8'), 
                              f"ai_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html", 
                              "text/html", 
                              use_container_width=True)
        
        with col2:
            csv_data = filtered_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button("📊 Скачать CSV данные", 
                              csv_data, 
                              f"filtered_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", 
                              "text/csv", 
                              use_container_width=True)
    
    except Exception as e:
        st.error(f"❌ Ошибка при обработке файла: {str(e)}")
        st.info("Пожалуйста, проверьте формат CSV файла и попробуйте снова.")
