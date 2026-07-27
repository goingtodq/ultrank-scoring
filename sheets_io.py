import os
import json
import gspread
from datetime import datetime, timedelta
from google.oauth2.service_account import Credentials
from zoneinfo import ZoneInfo


client = None
TTS_SHEET = "https://docs.google.com/spreadsheets/d/1aQEUAPqzF49OPMNNyPlelH5mRKtTWfrLHXI18R6Qfc0"

NOMINATIM_SHEET = "nominatim-cache"
EVENTS_SHEET = "all-events"

DATE_INDEX = 0
EVENT_DATE_INDEX = 1
TOURNAMENT_INDEX = 2
ACTIVITY_STATE_INDEX = 3
OVERRIDE_STATE_INDEX = 4
PROGRESS_INDEX = 5
CLASSIFICATION_INDEX = 6
OVERRIDE_DATE_INDEX = 7
NICKNAME_INDEX = 8
ID_INDEX = 11
SLUG_INDEX = 12
SCORE_INDEX = 14
OVERRIDE_SCORE_INDEX = 15
ENTRANTS_INDEX = 18
JUSTIFICATION_INDEX = 20
NOTE_INDEX = 21
EVENTS_COLUMNS = 22

def authorize():
    global client
    if client == None:
        SHEETS_API_KEY = json.loads(os.environ["SHEETS_API_KEY"])
        CREDS = Credentials.from_service_account_info(SHEETS_API_KEY, 
                                                      scopes=["https://www.googleapis.com/auth/spreadsheets"])
        client = gspread.authorize(CREDS)


def fetch_cached_addresses():
    authorize()
    main_sheet = client.open_by_url(TTS_SHEET)
    addresses_sheet = main_sheet.worksheet(NOMINATIM_SHEET)

    cached_addresses = addresses_sheet.get("A2:B")
    addresses = dict()
    for row in cached_addresses:
        if (len(row) > 1):
            addresses[row[0]] = json.loads(row[1])
    return addresses

def write_cached_addresses(addresses):
    authorize()
    main_sheet = client.open_by_url(TTS_SHEET)
    addresses_sheet = main_sheet.worksheet(NOMINATIM_SHEET)

    addresses_list = []

    for ll, address in addresses.items():
        addresses_list.append([ll, json.dumps(address)])

    addresses_sheet.update("A2", addresses_list)

def create_events_dict(tts_events, updated_events):
    """
    Creates an events dict with both old and new event data.
    """
    events_dict = dict()

    for event in tts_events:
        if len(event) == 0:
            continue

        events_dict[event[ID_INDEX]] = event[0:ID_INDEX] + event[ID_INDEX + 1:]

        # We need to be using full rows. Otherwise things get messed up.
        while len(events_dict[event[ID_INDEX]]) < EVENTS_COLUMNS - 1:
            events_dict[event[ID_INDEX]].append('')
    

    for event in updated_events:
        if event[ID_INDEX] in events_dict:
            current_event = events_dict[event[ID_INDEX]]

            # Override purple fields (ex: nickname)
            for index, field in enumerate(current_event):
                if index in [CLASSIFICATION_INDEX, OVERRIDE_STATE_INDEX, OVERRIDE_DATE_INDEX, NICKNAME_INDEX, OVERRIDE_SCORE_INDEX - 1, NOTE_INDEX - 1]:
                    event[index + 1 if index >= ID_INDEX else index] = field

        if event[JUSTIFICATION_INDEX] == None:
            event[JUSTIFICATION_INDEX] = ''

        events_dict[event[ID_INDEX]] = event[0:ID_INDEX] + event[ID_INDEX + 1:]

    return events_dict

def sanitize(string: str):
    return string.replace('""', '"').replace('"', '""')

def format_event_link(name, slug):
    """
    Creates a hyperlink out of an event slug and name.
    """
    return '=HYPERLINK(\"https://start.gg/' + sanitize(slug) + "\",\"" + sanitize(name) + '\")'

def format_classification(classification):
    classification = classification.upper()
    if classification == "R" or classification == "RANKED":
        classification = "RANKED"
    elif classification == "U" or classification == "UNRANKED":
        classification = "UNRANKED"
    return classification.strip()

def write_events(data):
    """
    Writes all events to the main sheet.
    """
    authorize()

    main_sheet = client.open_by_url(TTS_SHEET)
    events_sheet = main_sheet.worksheet(EVENTS_SHEET)

    events = events_sheet.get("A3:V")
    events_dict = create_events_dict(events, data)

    formatted_events = []
    for id, event in events_dict.items():
        formatted_events.append(event[0:ID_INDEX] + [int(id)] + event[ID_INDEX:])

        # recast (due to raw... annoying)
        formatted_events[-1][PROGRESS_INDEX] = float(formatted_events[-1][PROGRESS_INDEX])
        formatted_events[-1][SCORE_INDEX] = int(formatted_events[-1][SCORE_INDEX])
        try:
            formatted_events[-1][OVERRIDE_SCORE_INDEX] = int(formatted_events[-1][OVERRIDE_SCORE_INDEX])
        except ValueError:
            pass

        formatted_events[-1][TOURNAMENT_INDEX] = format_event_link(formatted_events[-1][TOURNAMENT_INDEX], formatted_events[-1][SLUG_INDEX])
        formatted_events[-1][CLASSIFICATION_INDEX] = format_classification(formatted_events[-1][CLASSIFICATION_INDEX])

    formatted_events.sort(key=lambda x: int(x[SCORE_INDEX]), reverse=True)
    formatted_events.sort(key=lambda x: x[DATE_INDEX], reverse=True)

    # USER_ENTERED lets hyperlinks show up.
    events_sheet.spreadsheet.values_batch_update({
        'value_input_option': 'USER_ENTERED',
        'data': [
            {'range': f'{events_sheet.title}!C3', 'values': [row[2:3] for row in formatted_events]},
        ],
    })

    events_sheet.spreadsheet.values_batch_update({
        'value_input_option': 'RAW',
        'data': [
            {'range': f'{events_sheet.title}!A3', 'values': [row[0:2] for row in formatted_events]},
            {'range': f'{events_sheet.title}!D3', 'values': [row[3:] for row in formatted_events]},
        ],
    })

    #events_sheet.update("A3", formatted_events, value_input_option='USER_ENTERED')

def fetch_updated_at():
    """
    Fetches from the updated_at sheet
    """
    authorize()
    main_sheet = client.open_by_url(TTS_SHEET)
    updated_at_sheet = main_sheet.worksheet("events-updated-at")
    slugs = updated_at_sheet.get("A2:E")

    formatted_slugs = dict()
    for slug in slugs:
        if len(slug) < 5:
            continue
        formatted_slugs[slug[0]] = [slug[1], slug[3], slug[4]]

    return formatted_slugs

def write_updated_at(results: list, startgg_updated_at):
    """
    Writes to the update_at sheet.
    """
    authorize()

    main_sheet = client.open_by_url(TTS_SHEET)
    slugs_updated_at = main_sheet.worksheet("events-updated-at")

    events = slugs_updated_at.get("A2:E")
    
    events_dict = dict()
    for event in events:
        if len(event) < 5:
            continue
        events_dict[event[0]] = event[1:]

    for result in results:
        events_dict[result.event_id] = [datetime.fromtimestamp(result.updated_at).isoformat(),
                                   datetime.now(ZoneInfo("UTC")).isoformat(),
                                   result.entrants,
                                   result.activity_state]
        
    for key, data in startgg_updated_at.items():
        if key in events_dict:
            events_dict[key][2] = data[1]

    formatted_slugs = []
    for id, info in events_dict.items():
        formatted_slugs.append([id, info[0], info[1], info[2], info[3]])

    slugs_updated_at.update("A2", formatted_slugs)

def remove_old_events():
    """
    Remove all events that are more than old (> 3 weeks passed). This is because:
    1. The sheet is slow with that many events
    2. Google sheets has a per-sheet cell cap
    It may end up being bad to cull these events? IDK.
    """
    authorize()

    main_sheet = client.open_by_url(TTS_SHEET)
    events_sheet = main_sheet.worksheet(EVENTS_SHEET)
    events = events_sheet.get("A3:V")

    cutoff_period = timedelta(days=21) # 3 weeks for now
    cutoff_date = datetime.now(ZoneInfo("UTC")).date() - cutoff_period

    kept_events = []
    removed_event_ids = []

    for row in events:
        if len(row) == 0:
            continue

        override_date = row[OVERRIDE_DATE_INDEX].strip()
        if override_date == "":
            unparsed_date = row[DATE_INDEX]
        else:
            unparsed_date = override_date

        # extra failsafe in case somebody fucks up an override date
        # maybe a bad idea? idk
        try:
            parsed_date = datetime.fromisoformat(unparsed_date).date()
        except:
            kept_events.append(row)
            continue

        # keep classified events. not perfect metric, likely should be changed later
        # or we have multiple scripts? idk
        classification = row[CLASSIFICATION_INDEX]
        if parsed_date < cutoff_date and classification == "":
            removed_event_ids.append(row[ID_INDEX])
        else:
            kept_events.append(row)

    # this is needed
    for event in kept_events:
        event[TOURNAMENT_INDEX] = format_event_link(event[TOURNAMENT_INDEX], event[SLUG_INDEX])

    kept_events.sort(key=lambda x: int(x[SCORE_INDEX]), reverse=True)
    kept_events.sort(key=lambda x: x[DATE_INDEX], reverse=True)

    for i in range(0, len(removed_event_ids)):
        kept_events.append([''] * EVENTS_COLUMNS)

    events_sheet.spreadsheet.values_batch_update({
        'value_input_option': 'USER_ENTERED',
        'data': [
            {'range': f'{events_sheet.title}!C3', 'values': [row[2:3] for row in kept_events]},
        ],
    })

    events_sheet.spreadsheet.values_batch_update({
        'value_input_option': 'RAW',
        'data': [
            {'range': f'{events_sheet.title}!A3', 'values': [row[0:2] for row in kept_events]},
            {'range': f'{events_sheet.title}!D3', 'values': [row[3:] for row in kept_events]},
        ],
    })

    slugs_updated_at = main_sheet.worksheet("events-updated-at")

    slugs = slugs_updated_at.get("A2:E")
    
    slugs_dict = dict()
    for slug in slugs:
        if len(slug) < 5:
            continue
        slugs_dict[slug[0]] = slug[1:]

    deleted = 0
    for id in removed_event_ids:
        if id in slugs_dict:
            del slugs_dict[id]
            deleted += 1

    formatted_slugs = []
    for slug, info in slugs_dict.items():
        formatted_slugs.append([slug, info[0], info[1], info[2], info[3]])
    for i in range(0, deleted):
        formatted_slugs.append([''] * 5)

    slugs_updated_at.update("A2", formatted_slugs)


def fetch_updated_players() -> list:
    """
    Fetches from the players sheet
    """
    authorize()
    main_sheet = client.open_by_url(TTS_SHEET)
    players_sheet = main_sheet.worksheet("players-needing-updates")
    players_data = players_sheet.get("A2:B")

    players = list()
    for player in players_data:
        if len(player) < 2:
            continue
        players.append(player[1])

    return players


def write_players(players):
    """
    Writes to the players sheet
    """
    authorize()
    main_sheet = client.open_by_url(TTS_SHEET)
    players_sheet = main_sheet.worksheet("players-needing-updates")
    players_data = players_sheet.get("A2:B")
    
    print(players_data)

    new_players = list()
    for player in players_data:
        if len(player) < 2:
            continue
        if player[1] not in players:
            new_players.append(player)

    # atomic clear/write
    main_sheet.values_batch_update({
        "value_input_option": "RAW",
        "data": [
            {"range": "players-needing-updates!A2:B1000", "values": [["", ""]] * 999},
            {"range": "players-needing-updates!A2", "values": new_players},
        ],
    })

def write_script_endtime():
    """
    Writes the script end time to the all events sheet
    """
    authorize()
    main_sheet = client.open_by_url(TTS_SHEET)
    events_sheet = main_sheet.worksheet(EVENTS_SHEET)
    events_sheet.update_acell("A1", "Last update by script: " + datetime.now(ZoneInfo("UTC")).replace(tzinfo=None).isoformat(timespec="seconds") + " (UTC)")
