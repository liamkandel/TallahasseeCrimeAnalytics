import streamlit as st
import pandas as pd
import requests
import sqlite3
from datetime import datetime
import re
import pydeck as pdk
import os

url = st.secrets.get('url')

# API status indicator
try:
    response = requests.get(url)
    response.raise_for_status()
    data = response.json()['data']
    st.success('✅ API response received successfully!')
except Exception as e:
    st.error(f'❌ Error fetching data from API: {e}')
    data = []

# Convert to DataFrame
df = pd.DataFrame(data)
df['x'] = df['x'].astype(float)
df['y'] = df['y'].astype(float)

st.title("Tallahassee Police Active Incidents")

# Connect to SQLite database (creates file if it doesn't exist)
conn = sqlite3.connect('incidents.db')
c = conn.cursor()

# Create table if it doesn't exist
c.execute('''
    CREATE TABLE IF NOT EXISTS incidents (
        eventinc TEXT PRIMARY KEY,
        eventnum TEXT,
        eventdate TEXT,
        eventid TEXT,
        x REAL,
        y REAL,
        eventdesc TEXT,
        eventheadline TEXT,
        eventaddress TEXT,
        ipk TEXT,
        fetched_at TEXT
    )
''')

# Insert new incidents, skip duplicates
for incident in data:
    if 'eventinc' not in incident:
        continue  # skip incomplete records
    try:
        c.execute('''
            INSERT OR IGNORE INTO incidents (
                eventinc, eventnum, eventdate, eventid, x, y, eventdesc, eventheadline, eventaddress, ipk, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            incident.get('eventinc'),
            incident.get('eventnum'),
            incident.get('eventdate'),
            incident.get('eventid'),
            float(incident.get('x', 0)),
            float(incident.get('y', 0)),
            incident.get('eventdesc'),
            incident.get('eventheadline'),
            incident.get('eventaddress'),
            incident.get('ipk'),
            datetime.now(datetime.timezone.utc).isoformat()
        ))
    except Exception as e:
        pass  # Optionally log errors
conn.commit()

# Interactive map with clickable markers for active incidents (replaces old map)
st.subheader("Active Incidents Map (Interactive)")
if not df[['y', 'x']].dropna().empty:
    icon_data = {
        "url": "https://cdn-icons-png.flaticon.com/512/684/684908.png",  # simple marker icon
        "width": 128,
        "height": 128,
        "anchorY": 128
    }
    df['icon_data'] = [icon_data] * len(df)
    icon_layer = pdk.Layer(
        type="IconLayer",
        data=df,
        get_icon="icon_data",
        get_position='[x, y]',
        get_size=4,
        size_scale=10,
        pickable=True
    )
    view_state = pdk.ViewState(
        latitude=df['y'].mean(),
        longitude=df['x'].mean(),
        zoom=11,
        pitch=0
    )
    r = pdk.Deck(
        layers=[icon_layer],
        initial_view_state=view_state,
        tooltip={
            "html": "<b>Type:</b> {eventdesc}<br><b>Time:</b> {eventdate}<br><b>Address:</b> {eventaddress}",
            "style": {"color": "white"}
        }
    )
    st.pydeck_chart(r)
else:
    st.info("No active incidents to display on the map.")

# Table of incidents
st.subheader("Incident Table")
st.dataframe(df[['eventdate', 'eventdesc', 'eventaddress']])

# Optionally, you can load all historical data for analytics:
hist_df = pd.read_sql_query('SELECT * FROM incidents', conn)

# Convert eventdate to datetime for sorting and analytics
def clean_eventdate(date_str):
    if pd.isna(date_str):
        return None
    # Replace multiple spaces with a single space
    date_str = re.sub(r'\s+', ' ', date_str.strip())
    # Try parsing with known format
    try:
        return pd.to_datetime(date_str, format='%b %d %Y %I:%M%p')
    except Exception:
        return pd.NaT

# Clean and parse eventdate for sorting and analytics
hist_df['eventdate_clean'] = hist_df['eventdate'].apply(clean_eventdate)
hist_df = hist_df.sort_values('eventdate_clean', ascending=False)

# Simple analytics: Most common event types
st.subheader("Most Common Event Types (All Time)")
event_counts = hist_df['eventdesc'].value_counts().reset_index()
event_counts.columns = ['Event Type', 'Count']
st.bar_chart(event_counts.set_index('Event Type'))
st.dataframe(event_counts)

# Heatmap for areas with highest crime rate
st.subheader("Crime Concentration Heatmap (All Time)")
if not hist_df[['y', 'x']].dropna().empty:
    heatmap_layer = pdk.Layer(
        "HeatmapLayer",
        data=hist_df,
        get_position='[x, y]',
        aggregation=pdk.types.String("MEAN"),
        get_weight=1,
        radiusPixels=60,
    )
    view_state = pdk.ViewState(
        latitude=hist_df['y'].mean(),
        longitude=hist_df['x'].mean(),
        zoom=11,
        pitch=50
    )
    st.pydeck_chart(pdk.Deck(layers=[heatmap_layer], initial_view_state=view_state))
else:
    st.info("Not enough data for heatmap.")

# Analytics: Most dangerous times of day
st.subheader("Most Dangerous Times of Day (All Time)")
if 'eventdate_clean' in hist_df:
    # hist_df['hour'] = hist_df['eventdate_clean'].dt.hour
    hour_counts = hist_df['hour'].value_counts().sort_index()
    st.bar_chart(hour_counts)
    hour_counts_df = hour_counts.reset_index()
    hour_counts_df.columns = ['Hour of day', 'Incident count']
    st.dataframe(hour_counts_df)
else:
    st.info("No valid event date data for time-of-day analysis.")


# Pie chart of incidents by ipk (severity/priority)
st.subheader("Incident Distribution by Severity (ipk)")
# Blurb explaining ipk
st.markdown("""
**What is 'ipk'?**  
The `ipk` field represents the priority or severity of each incident, as assigned by the Tallahassee Police Department. Lower values (e.g., 1 or 2) typically indicate higher priority or more urgent incidents, while higher values (e.g., 3 or 4) indicate lower priority. This helps identify which incidents require the most immediate attention.
""")

ipk_counts = hist_df['ipk'].value_counts().sort_index()
st.plotly_chart({
    "data": [{
        "values": ipk_counts.values,
        "labels": ipk_counts.index,
        "type": "pie",
        "hole": .3
    }],
    "layout": {"title": "Incidents by Severity (ipk)"}
})
st.dataframe(ipk_counts.reset_index().rename(columns={'index': 'ipk', 'ipk': 'Incident Count'}))

# You can add more analytics below, e.g., by time, by area, etc.
