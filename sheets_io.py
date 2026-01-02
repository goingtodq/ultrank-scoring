import os
import json
import gspread
from datetime import datetime
from google.oauth2.service_account import Credentials
import requests

client = None
TTS_SHEET = "https://docs.google.com/spreadsheets/d/1hz6wuj-BowOsyzRIowoAWRyVEJk7tHHFUNhJiJSgT48"

def authorize():
    global client
    if client == None:
        SHEETS_API_KEY = json.loads(os.environ["SHEETS_API_KEY"])
        CREDS = Credentials.from_service_account_info(SHEETS_API_KEY, 
                                                      scopes=["https://www.googleapis.com/auth/spreadsheets"])
        client = gspread.authorize(CREDS)

def fetch_slug_classifications():
    authorize()

    tts_main_sheet = client.open_by_url(TTS_SHEET)
    valid_slugs_sheet = tts_main_sheet.worksheet("valid-event-slugs")
    invalid_slugs_sheet = tts_main_sheet.worksheet("invalid-event-slugs")

    valid_slugs = valid_slugs_sheet.get("A2:A")
    invalid_slugs = invalid_slugs_sheet.get("A2:A")

    def flatten(xss):
        return [x for xs in xss for x in xs]

    valid_slugs = flatten(valid_slugs)
    invalid_slugs = flatten(invalid_slugs)

    return valid_slugs, invalid_slugs

def write_unsorted_events(data, valid_slugs, invalid_slugs):
    authorize()

    tts_main_sheet = client.open_by_url(TTS_SHEET)
    tts_tiered_events_sheet = tts_main_sheet.worksheet("tiered-unsorted-events")

    header = tts_tiered_events_sheet.get("A1:J1")
    events = tts_tiered_events_sheet.get("A2:J")

    tts_tiered_events_sheet.clear()

    events_dict = dict()

    for event in events:
        # weird edge case with empty sheet
        if len(event) == 0:
            continue

        events_dict[event[4]] = event[0:4] + event[5:]
    
    for event in data:
        events_dict[event[4]] = event[0:4] + event[5:]

    formatted_events = []
    for slug, event in events_dict.items():
        if slug in valid_slugs or slug in invalid_slugs:
            continue

        formatted_events.append(event[0:4] + [slug] + event[4:])
        formatted_events[-1][1] = '=HYPERLINK(\"https://start.gg/' + slug + "\",\"" + formatted_events[-1][1] + '\")'

    formatted_events.sort(key=lambda x: -int(x[6]))

    tts_tiered_events_sheet.update("A1", header)
    tts_tiered_events_sheet.update("A2", formatted_events, value_input_option='USER_ENTERED')

def write_valid_events(data, invalid_slugs):
    authorize()

    tts_main_sheet = client.open_by_url(TTS_SHEET)
    tts_tiered_events_sheet = tts_main_sheet.worksheet("tiered-valid-events")

    header = tts_tiered_events_sheet.get("A1:J1")
    events = tts_tiered_events_sheet.get("A2:J")

    tts_tiered_events_sheet.clear()

    events_dict = dict()

    for event in events:
        # weird edge case with empty sheet
        if len(event) == 0:
            continue

        events_dict[event[4]] = event[0:4] + event[5:]
    
    for event in data:
        events_dict[event[4]] = event[0:4] + event[5:]

    formatted_events = []
    for slug, event in events_dict.items():
        if slug in invalid_slugs:
            continue

        formatted_events.append(event[0:4] + [slug] + event[4:])
        formatted_events[-1][1] = '=HYPERLINK(\"https://start.gg/' + slug + "\",\"" + formatted_events[-1][1] + '\")'

    formatted_events.sort(key=lambda x: (x[0], -int(x[6])))

    tts_tiered_events_sheet.update("A1", header)
    tts_tiered_events_sheet.update("A2", formatted_events, value_input_option='USER_ENTERED')

def fetch_slugs_updated_at():
    authorize()

    tts_main_sheet = client.open_by_url(TTS_SHEET)
    slugs_updated_at = tts_main_sheet.worksheet("slugs-updated-at")

    slugs = slugs_updated_at.get("A2:E")

    formatted_slugs = dict()
    for slug in slugs:
        if len(slug) < 5:
            continue
        formatted_slugs[slug[0]] = [slug[1], slug[3], slug[4]]

    return formatted_slugs

def write_slugs_updated_at(valid_slugs, invalid_slugs, updated_slugs, timestamps):
    authorize()

    tts_main_sheet = client.open_by_url(TTS_SHEET)
    slugs_updated_at = tts_main_sheet.worksheet("slugs-updated-at")

    slugs = slugs_updated_at.get("A2:E")
    
    slugs_dict = dict()
    for slug in slugs:
        if len(slug) < 4:
            continue
        slugs_dict[slug[0]] = [slug[1], slug[2], slug[3]]

    for slug, timestamp in timestamps.items():
        if slug in updated_slugs:
            slugs_dict[slug] = [datetime.fromtimestamp(timestamp[0]).isoformat(), datetime.now().isoformat(), timestamp[1]]

    formatted_slugs = []
    for slug, dates in slugs_dict.items():
        status = "v" if slug in valid_slugs else ("u" if slug in invalid_slugs else "q")
        formatted_slugs.append([slug, dates[0], dates[1], dates[2], status])

    slugs_updated_at.update("A2", formatted_slugs)