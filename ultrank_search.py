# Requires dateparser, which you can install via `pip install dateparser`.

from startgg_toolkit import send_request
import dateparser
import csv
import os
import traceback
from Levenshtein import jaro_winkler
from datetime import datetime, timedelta
from ultrank_bulk import bulk_score, write_results
from sheets_io import fetch_slug_classifications, fetch_slugs_updated_at, write_slugs_updated_at

# defines the minimum Jaro-Winkler similarity to
# categorize a tournament as a related iteration.
MINIMUM_JARO_SIMILARITY = 0.8

# certain event names to skip string similarity check for
skip_weekly_check = ['Smash Mouth', 'The Big Bang Hadoken edition', 'Gengar League', 'To The Top',
    'IR Training: Special Edition', 'DAT BlastZone', 'Boss Stage', 'Bonus Stage', 'Smash on Titan',
    'Xentric Gaming: Let\'s Brawl', 'CLUTCH23. Ultimate Mayhem', 'マエスマ\'', 'マエスマTOP', 'Champion Series',
    'qualifier', 'lcq', 'Ultimate Gaiden', 'Xenosaga', 'Macrospacing Vancouver', 'Ultimate Challenger Series',
    '月', 'monthly', 'seasonal', 'mensual', 'CLUTCH United Mayhem', '4o4 by Sh33rz: Smash Bowl',
    'Undiscovered Turbo', 'BeeSmash BIG', 'Smash Pro League']
organizer_blacklist = ['f014e14d', '6d94b652', 'fef75a6a', 'ebbf7fac', '4472fa92', '886decc2']

class Tournament:
    def __init__(self, name, slug, start_at):
        self.name = name
        self.slug = slug
        self.start_at = start_at
        self.time_since = start_at
        self.similarity = 0


def tournaments_query(start_time, end_time, page=1, per_page=20):
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
      slug
      name
      startAt
      events {
        name
        type
        videogame {
          id
        }
        slug
        numEntrants
      }
      owner {
        discriminator
        id
        tournaments(
            query: {
                page: 1,
                perPage: 10,
                filter: {
                    videogameId: [1386]
                }
            }
        ) {
            pageInfo {
              totalPages
            }
            nodes {
              name
              slug
              startAt
              owner {
                id
              }
              hasOfflineEvents
            }
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


def admin_query(tournament_slug, page=1, per_page=75):
    query = '''query tournamentAdminQuery($tournamentSlug: String!, $pageNum: Int!, $perPage: Int!) {
  tournament(slug: $tournamentSlug) {
    name
    startAt
    owner {
      id
      player {
        gamerTag
      }
      tournaments(
        query: {
          page: $pageNum,
          perPage: $perPage,
          filter: {
            videogameId: [1386]
          }
        }
      ) {
        pageInfo {
          totalPages
        }
        nodes {
          name
          slug
          startAt
          owner {
            id
          }
          hasOfflineEvents
        }
      }
    }
  }
}'''
    variables = '''{{
        "tournamentSlug": "{}",
        "pageNum": {},
        "perPage": {}
    }}'''.format(tournament_slug, page, per_page)

    return query, variables

def tournament_owner_query(tournament_slug):
    query = '''query tournamentOwnerQuery($tournamentSlug: String!) {
  tournament(slug: $tournamentSlug) {
    owner {
      discriminator
    }
  }
}'''
    variables = '''{{
        "tournamentSlug": "{}"
    }}'''.format(tournament_slug)

    return query, variables


def get_admined_tournaments(base_tournament, day_range=18):
    """Gather all tournament names with the same owner as the requested tournament,
    within the specified day range prior.

    Puts the requested tournament as the first item in the returned array.
    """

    page = 0
    tournaments = []
    tournament_name = base_tournament['name']
    tournament_slug = base_tournament['slug']
    tournament_owner_id = base_tournament['owner']['id']
    tournament_start = base_tournament['startAt']
    tournament_start_datetime = datetime.fromtimestamp(tournament_start)
    range_start_timedelta = timedelta(days=day_range)
    range_start = (tournament_start_datetime - range_start_timedelta).timestamp()

    while True:
        data = []
        if page == 0:
            data = base_tournament['owner']['tournaments']
        else:
            query, variables = admin_query(tournament_slug, page)
            resp = send_request(query, variables, quiet=True)

            if resp['data']['tournament']['owner']['tournaments'] is None:
                break

            data = resp['data']['tournament']['owner']['tournaments']

        # Gather tournaments
        tournaments.extend([Tournament(tournament['name'], tournament['slug'], tournament['startAt']) for tournament in data['nodes'] if (
            tournament['owner']['id'] == tournament_owner_id and tournament['slug'] != tournament_slug and tournament['startAt'] >= range_start and tournament['startAt'] <= tournament_start
            and tournament['hasOfflineEvents'])])

        # Check if all tournaments are before the requested tournament.
        # Since the API returns tournaments in reverse chronological order, this means that we don't need to check the rest.
        if data['nodes'][-1]['startAt'] < tournament_start:
            break

        if page >= data['pageInfo']['totalPages']:
            break
        page += 1

    tournaments.insert(0, Tournament(
        tournament_name, tournament_slug, tournament_start))

    return tournaments


def check_potential_weekly(tournament):
    other_admined_tournaments = get_admined_tournaments(tournament)

    base_tournament = other_admined_tournaments[0]

    for tournament in other_admined_tournaments[1:]:
        sim = jaro_winkler(base_tournament.name, tournament.name, score_cutoff=MINIMUM_JARO_SIMILARITY)
        if sim != 0:
            tournament.time_since = base_tournament.start_at - tournament.start_at
            tournament.similarity = sim
            return tournament

    return None

def check_blacklist(discriminator):
    return discriminator in organizer_blacklist

def retrieve_events(start_time, end_time):
    page = 1
    events_data = []

    while True:
        query, variables = tournaments_query(start_time, end_time, page=page)
        resp = send_request(query, variables, quiet=True)

        print('checking {} tournaments'.format(len(resp['data']['tournaments']['nodes'])))

        for tournament in resp['data']['tournaments']['nodes']:
            try:
                events = [event for event in tournament['events'] if (
                    event['type'] == 1 and event['videogame']['id'] == 1386 and event['numEntrants'] != None)]

                events.sort(reverse=True, key=lambda event: event['numEntrants'])

                added_event = False

                potential_weekly = "not checked"
                
                for skip in skip_weekly_check:
                    if skip.lower() in tournament['name'].lower():
                        potential_weekly = "skip"

                ladder_potential = None


                for event in events:
                    event_data = [datetime.fromtimestamp(tournament['startAt']).isoformat(), 
                                  '=HYPERLINK(\"https://start.gg/' + event['slug'] + "\",\"" + tournament['name'] + '\")', 
                                  event['name'], 
                                  event['slug']]

                    used = False
                    skip_reason = None

                    if check_blacklist(tournament['owner']['discriminator']):
                        skip_reason = 'Tournament Creator Blacklisted'
                    elif tournament['name'].lower().find('weekly') != -1 or event['name'].lower().find('weekly') != -1:
                        skip_reason = 'Probable Weekly (contains string "weekly")'
                    elif tournament['name'].lower().find('weeklies') != -1 or event['name'].lower().find('weeklies') != -1:
                        skip_reason = 'Probable Weekly (contains string "weeklies")'
                    elif tournament['name'].lower().find('arcadian') != -1 or event['name'].lower().find('arcadian') != -1:
                        skip_reason = 'Probable Arcadian (contains string "arcadian")'
                    elif event['name'].lower().find('ladder') != -1:
                        ladder_potential = event_data
                        continue
                    elif event['name'].lower().find('redemption') != -1:
                        skip_reason = 'Probable Side Event (contains string "redemption")'
                    elif event['name'].lower().find('resurrection') != -1:
                        skip_reason = 'Probable Side Event (contains string "resurrection")'
                    elif event['name'].lower().find('buster') != -1:
                        skip_reason = 'Probable Side Event (contains string "buster")'
                    elif event['name'].lower().find('amateur') != -1:
                        skip_reason = 'Probable Side Event (contains string "amateur")'
                    elif event['name'].lower().find('squad') != -1:
                        skip_reason = 'Probable Side Event (contains string "squad")'
                    elif event['name'].lower().find('random') != -1:
                        skip_reason = 'Probable Side Event (contains string "random")'
                    elif event['name'].lower().find('cpu') != -1:
                        skip_reason = 'Probable Side Event (contains string "cpu")'
                    elif event['name'].lower().find('amiibo') != -1:
                        skip_reason = 'Probable Side Event (contains string "amiibo")'
                    elif event['name'].lower().find('hdr') != -1:
                        skip_reason = 'Probable Side Event (contains string "hdr")'
                    elif event['name'].lower().find('wait') != -1:
                        skip_reason = 'Probable Waitlist (contains string "wait")'
                    elif added_event:
                        skip_reason = 'Other Larger Event in Tournament'
                    elif tournament['name'].lower().find('monthly') != -1 or event['name'].lower().find('monthly') != -1:
                        used = True
                    elif potential_weekly == "not checked":
                        potential_weekly = check_potential_weekly(tournament)

                        if isinstance(potential_weekly, Tournament):
                            days_since = str(
                                round(potential_weekly.time_since / (24 * 60 * 60)))

                            skip_reason = 'Probable Weekly [{:.5f}] (found tournament {} [{}] which precedes by {} days)'.format(potential_weekly.similarity, potential_weekly.name, potential_weekly.slug, days_since)
                            added_event = True # TODO: Should this be here?

                    if skip_reason == None:
                        used = True

                    event_data.append(used)
                    if not used:
                        event_data.append(skip_reason)
                    else:
                        added_event = True

                    events_data.append(event_data)

                if ladder_potential:
                    event_data = ladder_potential

                    if added_event:
                        used = False
                        skip_reason = 'Probable Side Event (contains string "ladder")'
                    else:
                        used = True

                    event_data.append(used)
                    if not used:
                        event_data.append(skip_reason)
                    else:
                        added_event = True

                    events_data.append(event_data)
            except Exception as e:
                print(e)
                print(tournament['slug'])
                traceback.print_exc()

        if page >= resp['data']['tournaments']['pageInfo']['totalPages']:
            break
        page += 1

    events_data.append(['Start Date', 'Tournament', 'Event', 'Slug', 'Valid', 'Skip Reason'])
    events_data.reverse()
    return events_data

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


def filter_valid_slugs(valid_slugs, invalid_slugs, updated_at_tts, updated_at_startgg):
    slugs = []
    for slug in updated_at_startgg:
        if slug in invalid_slugs:
            continue
        elif slug not in updated_at_tts:
            slugs.append(slug)
        elif updated_at_tts[slug][2] == "u":
            slugs.append(slug)
        elif slug in valid_slugs and updated_at_tts[slug][2] != "v":
            slugs.append(slug)
        elif slug not in valid_slugs and updated_at_tts[slug][2] == "v":
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

    valid_slugs, invalid_slugs = fetch_slug_classifications()

    slugs_updated_at = fetch_slugs_updated_at()
    startgg_updated_at = retrieve_events_updated_at(start_timestamp, end_timestamp)

    events_needing_updates = filter_valid_slugs(valid_slugs, invalid_slugs, slugs_updated_at, startgg_updated_at)

    results = bulk_score([{'slug': slug, 'invit': False} for slug in events_needing_updates])

    write_results(results, valid_slugs, invalid_slugs)
    write_slugs_updated_at(valid_slugs, invalid_slugs, events_needing_updates, startgg_updated_at)