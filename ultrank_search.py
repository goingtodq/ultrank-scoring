# Requires dateparser, which you can install via `pip install dateparser`.

from startgg_toolkit import send_request
import dateparser
import csv
import os
import traceback
from datetime import datetime, timedelta
from ultrank_bulk import bulk_score, write_results
from sheets_io import fetch_slug_classifications, fetch_slugs_updated_at, write_slugs_updated_at

class Tournament:
    def __init__(self, name, slug, start_at):
        self.name = name
        self.slug = slug
        self.start_at = start_at
        self.time_since = start_at
        self.similarity = 0

def events_updated_at_query(start_time, end_time, page=1, per_page=40):
    query = '''query tournamentsQuery($pageNum: Int!, $perPage: Int!, $startTime: Timestamp!, $endTime: Timestamp!) {
  tournaments (
    query: {
      page: $pageNum,
      perPage: $perPage,
      filter: {
        hasOnlineEvents: false,
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
        slug
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

def retrieve_events_updated_at(start_time, end_time):
    page = 1
    updated = dict()

    while True:
        query, variables = events_updated_at_query(start_time, end_time, page=page)
        resp = send_request(query, variables, quiet=True)
        print('retrieved {} tournaments updated_at data'.format(len(resp['data']['tournaments']['nodes'])))

        for tournament in resp['data']['tournaments']['nodes']:
            try:
                events = [event for event in tournament['events'] if (
                    event['type'] == 1 and event['videogame']['id'] == 1386 and event['numEntrants'] != None)]

                for event in events:
                    updated[event['slug']] = [event['updatedAt'], event['numEntrants']]
            except Exception as e:
                print(e)
                print(tournament)
                traceback.print_exc()
        if page >= resp['data']['tournaments']['pageInfo']['totalPages']:
            break
        page += 1
    return updated


def filter_ranked_slugs(ranked_slugs, unranked_slugs, updated_at_tts, updated_at_startgg):
    slugs = []
    for slug in updated_at_startgg:
        if slug in unranked_slugs:
            continue
        elif slug not in updated_at_tts:
            slugs.append(slug)
        elif updated_at_tts[slug][2] == "u":
            slugs.append(slug)
        elif slug in ranked_slugs and updated_at_tts[slug][2] != "v":
            slugs.append(slug)
        elif slug not in ranked_slugs and updated_at_tts[slug][2] == "v":
            slugs.append(slug)
        elif datetime.fromisoformat(updated_at_tts[slug][0]).timestamp() < updated_at_startgg[slug][0]:
            print("Need to update based on time!", slug)
            slugs.append(slug)
        elif updated_at_tts[slug][1] != str(updated_at_startgg[slug][1]):
            print("Need to update, number of entrants changed from", updated_at_tts[slug][1], "to",  updated_at_startgg[slug][1], slug)
            slugs.append(slug)

    return slugs

if __name__ == '__main__':
    start_time_str = input('input starting time for search: ')
    start_time = dateparser.parse(start_time_str)
    start_timestamp = int(start_time.timestamp())

    end_time_str = input('input ending time for search: ')
    end_time = dateparser.parse(end_time_str)
    end_timestamp = int(end_time.timestamp())

    print('using start timestamp {} and end timestamp {}'.format(
        str(start_timestamp), str(end_timestamp)))

    ranked_slugs, unranked_slugs = fetch_slug_classifications()

    slugs_updated_at = fetch_slugs_updated_at()
    startgg_updated_at = retrieve_events_updated_at(start_timestamp, end_timestamp)

    events_needing_updates = filter_ranked_slugs(ranked_slugs, unranked_slugs, slugs_updated_at, startgg_updated_at)

    results = bulk_score([{'slug': slug, 'invit': False} for slug in events_needing_updates])

    write_results(results, ranked_slugs, unranked_slugs)
    write_slugs_updated_at(ranked_slugs, unranked_slugs, events_needing_updates, startgg_updated_at)