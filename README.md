# 📊 kpi-dashboard

Interactive KPI dashboard built with Streamlit, pandas and Plotly.

## Features
- Upload a CSV/Excel file (or use the built-in `sample_data.csv`), with a column-mapping step for differently named columns
- Sidebar filters (date range, region, category, product) and a reset button
- KPI cards: revenue, profit, margin, units, average order value, month-over-month growth
- Interactive charts: trend (monthly/weekly), revenue by region, category share, top products, region × category heatmap
- Searchable data table with CSV download, data-quality panel, and rule-based insights

Required fields: `Date, Region, Product, Category, Units Sold, Revenue, Cost`
(optional: `Salesperson, Customer Segment`). Each row is treated as one order; profit = revenue − cost.

## Setup and Run

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```
