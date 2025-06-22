import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import re
import pydeck as pdk
import os
from supabase import create_client, Client

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

# Load Supabase credentials from Streamlit secrets
data_url = st.secrets["supabase_url"]
data_key = st.secrets["supabase_key"]
supabase: Client = create_client(data_url, data_key)

# Insert new incidents, skip duplicates
for incident in data:
    if 'eventinc' not in incident:
        continue  # skip incomplete records
    # Check if incident already exists
    existing = supabase.table('incidents').select('eventinc').eq('eventinc', incident.get('eventinc')).execute()
    if existing.data:
        continue  # skip duplicates
    try:
        supabase.table('incidents').insert({
            'eventinc': incident.get('eventinc'),
            'eventnum': incident.get('eventnum'),
            'eventdate': incident.get('eventdate'),
            'eventid': incident.get('eventid'),
            'x': float(incident.get('x', 0)),
            'y': float(incident.get('y', 0)),
            'eventdesc': incident.get('eventdesc'),
            'eventheadline': incident.get('eventheadline'),
            'eventaddress': incident.get('eventaddress'),
            'ipk': incident.get('ipk'),
            'fetched_at': datetime.now().isoformat()
        }).execute()
    except Exception as e:
        st.error(f"Supabase insert error: {e}")

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

# Load all historical data for analytics
hist_df = pd.DataFrame(supabase.table('incidents').select('*').execute().data)

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

# Heatmap for areas with highest crime rate (last 24 hours)
st.subheader("Crime Concentration Heatmap (Last 24 Hours)")

if 'eventdate_clean' in hist_df:
    last_24h = datetime.now() - timedelta(hours=24)
    recent_df = hist_df[hist_df['eventdate_clean'] >= last_24h]
    if not recent_df[['y', 'x']].dropna().empty:
        heatmap_layer = pdk.Layer(
            "HeatmapLayer",
            data=recent_df,
            get_position='[x, y]',
            aggregation=pdk.types.String("MEAN"),
            get_weight=1,
            radiusPixels=60,
        )
        view_state = pdk.ViewState(
            latitude=recent_df['y'].mean(),
            longitude=recent_df['x'].mean(),
            zoom=11,
            pitch=50
        )
        st.pydeck_chart(pdk.Deck(layers=[heatmap_layer], initial_view_state=view_state))
        
        # Show table of events used in the heatmap
        #st.subheader("Events in Last 24 Hours (Heatmap Data)")
        #st.dataframe(recent_df[['eventdate', 'eventdesc', 'eventaddress', 'x', 'y']].sort_values('eventdate', ascending=False))
        
    else:
        st.info("Not enough data for heatmap in the last 24 hours.")
else:
    st.info("No valid event date data for heatmap.")

# Analytics: Most dangerous times of day
st.subheader("Times of day with highest incident count (All Time)")
if 'eventdate_clean' in hist_df:
    hist_df['hour'] = hist_df['eventdate_clean'].dt.hour
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

ipk_label_map = {
    '1': '1 (Least severe)',
    '2': '2 (Less severe)',
    '3': '3 (More severe)',
    '4': '4 (Most severe)'
}
ipk_counts = hist_df['ipk'].value_counts().sort_index()
labels = [ipk_label_map.get(str(ipk), str(ipk)) for ipk in ipk_counts.index]
st.plotly_chart({
    "data": [{
        "values": ipk_counts.values,
        "labels": labels,
        "type": "pie",
        "hole": .3
    }],
    "layout": {"title": "Incidents by Severity (ipk)"}
})
# st.dataframe(ipk_counts.reset_index().rename(columns={'index': 'ipk', 'ipk': 'Incident Count'}))

# You can add more analytics below, e.g., by time, by area, etc.

# Data source attribution
st.markdown("""
---
**Data Source:** [Tallahassee Police Active Incidents](https://www.talgov.com/gis/tops/)
""")
