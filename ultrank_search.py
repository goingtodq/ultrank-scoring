# Requires dateparser, which you can install via `pip install dateparser`.

from startgg_toolkit import send_request
import dateparser
import csv
import os
import traceback
from datetime import datetime, timedelta, timezone
from ultrank_bulk import bulk_score, write_results
from ultrank_tiering import Addresses
from sheets_io import fetch_updated_at, write_updated_at, write_cached_addresses, fetch_updated_players, write_players, write_script_endtime

class Tournament:
    def __init__(self, name, slug, start_at):
        self.name = name
        self.slug = slug
        self.start_at = start_at
        self.time_since = start_at
        self.similarity = 0

# current per_page may be unstable
def events_updated_at_query(start_time, end_time, page=1, per_page=40):
    query = '''query tournamentsQuery($pageNum: Int!, $perPage: Int!, $startTime: Timestamp!, $endTime: Timestamp!) {
  tournaments (
    query: {
      page: $pageNum,
      perPage: $perPage,
      filter: {
        videogameIds: [1386],
        afterDate: $startTime,
        beforeDate: $endTime
      }
    }
  ) {
    pageInfo {
      totalPages
    }
    nodes {
      events {
        id
        slug
        state
        updatedAt
        type
        numEntrants
        videogame {
          id
        }
      }
    }
  }
}'''
    variables = '''{{
        "pageNum": {},
        "perPage": {},
        "startTime": {},
        "endTime": {}
    }}'''.format(page, per_page, start_time, end_time)

    return query, variables

def player_events_query(player_id, page=1, per_page=490):
    query = '''query playerEventsQuery($pageNum: Int!, $perPage: Int!, $playerId: ID!) {
  player(id: $playerId) {
    user {
      events (
        query: {
          page: $pageNum,
          perPage: $perPage,
          filter: {
            videogameId: [1386],
          }
        } 
      ) {
        pageInfo {
          totalPages
        }
        nodes {
          slug
          updatedAt
          type
          numEntrants
          tournament {
            startAt
          }
        }
      }
    }
  }
}'''
    variables = '''{{
        "pageNum": {},
        "perPage": {},
        "playerId": {}
    }}'''.format(page, per_page, player_id)

    return query, variables

def retrieve_events_updated_at(start_time, end_time):
    TIME_STEP = 4000000
    TIME_STEP_BUFFER = 400000
    updated = dict()

    time_slices = []
    time = start_time
    while time < end_time:
        time_slices.append((time, min(time + TIME_STEP, end_time) + TIME_STEP_BUFFER))
        time += TIME_STEP

    for slice in time_slices:
      page = 0
      while True:
          query, variables = events_updated_at_query(slice[0], slice[1], page=page)
          resp = send_request(query, variables)

          # To avoid crashes... should ideally never be triggered.
          if resp['data']['tournaments'] is None:
              print('Early exit from retrieve_events_updated_at', resp)
              break

          for tournament in resp['data']['tournaments']['nodes']:
              if tournament['events'] is None:
                  continue

              try:
                  events = [event for event in tournament['events'] if (
                      event['type'] == 1 and event['videogame']['id'] == 1386 and event['numEntrants'] != None and event['numEntrants'] >= 8)]

                  for event in events:
                      updated[str(event['id'])] = [event['updatedAt'], event['numEntrants'], event['state']]
              except Exception as e:
                  print(e)
                  print(tournament)
                  traceback.print_exc()
          if page >= resp['data']['tournaments']['pageInfo']['totalPages']:
              break
          if page >= resp['data']['tournaments']['pageInfo']['totalPages']:
              print(f"Page count overflow: {resp['data']['tournaments']['pageInfo']['totalPages']}")
          page += 1
    return updated

def retrieve_events_by_player(start_time, end_time, player):
    page = 1
    event_slugs = []

    while True:
        query, variables = player_events_query(player, page)
        resp = send_request(query, variables)      
        player_events = resp['data']['player']['user']['events']['nodes']

        try:
            events = [event for event in player_events if (
                event['type'] == 1
                and start_time <= event['tournament']['startAt'] and event['tournament']['startAt'] <= end_time 
                and event['numEntrants'] != None and event['numEntrants'] >= 8)]
            for event in events:
                event_slugs.append(event['slug'])
        except Exception as e:
            print(e)
            print(player_events)
            traceback.print_exc()

        if page >= resp['data']['player']['user']['events']['pageInfo']['totalPages']:
            break
        page += 1
    return event_slugs

def determine_events_to_update(updated_at_tts, updated_at_startgg):
    UPDATED_AT_INDEX = 0
    ENTRANTS_INDEX = 1
    ACTIVITY_STATE_INDEX = 2

    ids = []
    for id in updated_at_startgg:
        if id not in updated_at_tts:
            print(f"New event! -- {id}")
            ids.append(id)
        elif datetime.fromisoformat(updated_at_tts[id][UPDATED_AT_INDEX]).replace(tzinfo=timezone.utc).timestamp() < updated_at_startgg[id][UPDATED_AT_INDEX]:
            print(f"Need to update based on time! -- {id}")
            ids.append(id)
        elif updated_at_tts[id][ENTRANTS_INDEX] != str(updated_at_startgg[id][ENTRANTS_INDEX]):
            print(f"Need to update, number of entrants changed from {updated_at_tts[id][ENTRANTS_INDEX]} to {updated_at_startgg[id][ENTRANTS_INDEX]} -- {id}")
            ids.append(id)
        elif updated_at_tts[id][ACTIVITY_STATE_INDEX] != str(updated_at_startgg[id][ACTIVITY_STATE_INDEX]):
            print(f"Need to update, activity state changed from {updated_at_tts[id][ACTIVITY_STATE_INDEX]} to {updated_at_startgg[id][ACTIVITY_STATE_INDEX]} -- {id}")
            ids.append(id)
        elif updated_at_startgg[id][ACTIVITY_STATE_INDEX] == "ACTIVE":
            print(f"Need to update, active event {updated_at_startgg[id][ACTIVITY_STATE_INDEX]} -- {id}")
            ids.append(id)

    return ids

def determine_slugs_to_force_update(players, scan_time, end_time):
    slugs = []
    for player in players:
        slugs = slugs + retrieve_events_by_player(scan_timestamp, end_time, player)

    return slugs

if __name__ == '__main__':
    start_time_str = input('input starting time for search: ')
    start_time = dateparser.parse(start_time_str)
    start_timestamp = int(start_time.timestamp())

    end_time_str = input('input ending time for search: ')
    end_time = dateparser.parse(end_time_str)
    end_timestamp = int(end_time.timestamp())

    # how far back must we go when updating player's values
    # scan_time_str = input('player update scan starting time: ')
    # scan_time = dateparser.parse(scan_time_str)
    # scan_timestamp = int(scan_time.timestamp())

    print('using start timestamp {} and end timestamp {}'.format(
        str(start_timestamp), str(end_timestamp)))

    sheet_updated_at = fetch_updated_at()
    startgg_updated_at = retrieve_events_updated_at(start_timestamp, end_timestamp)

    # return is a list of ids (previously slugs)
    events_needing_updates = determine_events_to_update(sheet_updated_at, startgg_updated_at)

    # read from the players list
    # find all events with these players and force add to the events needing updates
    # players = fetch_updated_players()
    # player_events_needing_updates = determine_slugs_to_force_update(players, scan_timestamp, end_timestamp)
    # events_needing_updates = events_needing_updates + player_events_needing_updates

    events = list(dict.fromkeys(events_needing_updates))

    results = bulk_score([{'id': id, 'invit': False} for id in events])

    write_cached_addresses(Addresses().addresses)
    write_results(results)
    write_updated_at(results, startgg_updated_at)
    # write_players(players)
    write_script_endtime()