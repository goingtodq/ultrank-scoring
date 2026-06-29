from ultrank_tiering import Tournament, TournamentTieringResult
from startgg_toolkit import startgg_slug_regex
from sheets_io import write_events
from datetime import datetime
from Levenshtein import jaro_winkler
from startgg_toolkit import send_request
from datetime import datetime, timedelta
import csv
import os 
import re
import sys

true_values = ['true', 't', '1']


class Tournament2:
    def __init__(self, name, slug, start_at):
        self.name = name
        self.slug = slug
        self.start_at = start_at
        self.time_since = start_at
        self.similarity = 0

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


def get_admined_tournaments(tournament_slug, day_range=15):
    """Gather all tournament names with the same owner as the requested tournament,
    within the specified day range prior.

    Puts the requested tournament as the first item in the returned array.
    """

    page = 1
    tournaments = []
    tournament_name = None
    tournament_owner_id = None
    tournament_start = None
    range_start = None

    while True:
        query, variables = admin_query(tournament_slug, page)
        resp = send_request(query, variables, quiet=True)
        # print(resp)

        # Set tournament-specific variables if not set
        if tournament_name == None:
            tournament_name = resp['data']['tournament']['name']
        if tournament_owner_id == None:
            tournament_owner_id = resp['data']['tournament']['owner']['id']
        if tournament_start == None:
            tournament_start = resp['data']['tournament']['startAt']
        if range_start == None:
            tournament_start_datetime = datetime.fromtimestamp(
                tournament_start)
            range_start_timedelta = timedelta(days=day_range)
            range_start = (tournament_start_datetime -
                           range_start_timedelta).timestamp()

        if resp['data']['tournament']['owner']['tournaments'] is None:
            break

        # Gather tournaments
        tournaments.extend([Tournament2(tournament['name'], tournament['slug'], tournament['startAt']) for tournament in resp['data']['tournament']['owner']['tournaments']['nodes'] if (
            tournament['owner']['id'] == tournament_owner_id and tournament['slug'] != tournament_slug and tournament['startAt'] >= range_start and tournament['startAt'] <= tournament_start
            and tournament['hasOfflineEvents'])])

        # Check if all tournaments are before the requested tournament.
        # Since the API returns tournaments in reverse chronological order, this means that we don't need to check the rest.
        if resp['data']['tournament']['owner']['tournaments']['nodes'][-1]['startAt'] < tournament_start:
            break

        if page >= resp['data']['tournament']['owner']['tournaments']['pageInfo']['totalPages']:
            break
        page += 1

    tournaments.insert(0, Tournament2(
        tournament_name, tournament_slug, tournament_start))

    return tournaments


def check_potential_weekly(tournamentSlug):
    other_admined_tournaments = get_admined_tournaments(tournamentSlug)

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

def validate_event(event):
    used = False
    skip_reason = None

    for skip in skip_weekly_check:
        if skip.lower() in event.event.lower():
            return [True, 'skip_weekly_check, matched: ' + skip.lower()]

    if check_blacklist(event.ownerDiscriminator):
        skip_reason = 'Tournament Creator Blacklisted'
    elif event.event.lower().find('weekly') != -1 or event.event.lower().find('weekly') != -1:
        skip_reason = 'Probable Weekly (contains string "weekly")'
    elif event.tournament.lower().find('weeklies') != -1 or event.event.lower().find('weeklies') != -1:
        skip_reason = 'Probable Weekly (contains string "weeklies")'
    elif event.tournament.lower().find('arcadian') != -1 or event.event.lower().find('arcadian') != -1:
        skip_reason = 'Probable Arcadian (contains string "arcadian")'
    elif event.event.lower().find('ladder') != -1:
        skip_reason = 'Probable Side Event (contains string "ladder")'
    elif event.event.lower().find('redemption') != -1:
        skip_reason = 'Probable Side Event (contains string "redemption")'
    elif event.event.lower().find('resurrection') != -1:
        skip_reason = 'Probable Side Event (contains string "resurrection")'
    elif event.event.lower().find('buster') != -1:
        skip_reason = 'Probable Side Event (contains string "buster")'
    elif event.event.lower().find('amateur') != -1:
        skip_reason = 'Probable Side Event (contains string "amateur")'
    elif event.event.lower().find('squad') != -1:
        skip_reason = 'Probable Side Event (contains string "squad")'
    elif event.event.lower().find('random') != -1:
        skip_reason = 'Probable Side Event (contains string "random")'
    elif event.event.lower().find('cpu') != -1:
        skip_reason = 'Probable Side Event (contains string "cpu")'
    elif event.event.lower().find('amiibo') != -1:
        skip_reason = 'Probable Side Event (contains string "amiibo")'
    elif event.event.lower().find('hdr') != -1:
        skip_reason = 'Probable Side Event (contains string "hdr")'
    elif event.event.lower().find('wait') != -1:
        skip_reason = 'Probable Waitlist (contains string "wait")'
    elif event.tournament.lower().find('monthly') != -1 or event.event.lower().find('monthly') != -1:
        used = True
    else:
        print(event.tournamentSlug)
        potential_weekly = check_potential_weekly(event.tournamentSlug)

        if potential_weekly is not None:
            days_since = str(
                round(potential_weekly.time_since / (24 * 60 * 60)))
            skip_reason = 'Probable Weekly [{:.5f}] (found tournament {} [{}] which precedes by {} days)'.format(potential_weekly.similarity, potential_weekly.name, potential_weekly.slug, days_since)

    if skip_reason == None:
        used = True

    return [used, skip_reason]

def bulk_score(slugs):
    """Scores multiple slugs, and returns the resultant result."""

    # Get values
    results = []

    for slug_obj in slugs:
        slug = slug_obj['slug']
        invit = slug_obj['invit']

        if startgg_slug_regex.fullmatch(slug):
            print('calculating for slug {}'.format(slug))

            try:
                t = Tournament(slug, invit)
                result = t.calculate_tier()

                results.append(result)

            except Exception as e:
                print(e)
                print('catastrophic failure')
                results.append(slug)
        else:
            print('skipping slug {}'.format(slug))
            results.append(slug)

    return results


def write_results(results):
    formatted_results = []

    for result in results:
        formatted_result = []
        if isinstance(result, TournamentTieringResult):
            formatted_result = [result.date.isoformat(), result.tournament, "", "", "", result.event, result.region.note, result.slug, 
                                str(result.is_invitational), result.score, result.max_potential_score(), "", result.entrants,
                                str(result.should_count())]
            formatted_result += validate_event(result)
            formatted_result += [""]

            formatted_results.append(formatted_result)
        else:
            print("Error: Not a valid TournamentTieringResult -- ", result)
            continue

    write_events(formatted_results)

if __name__ == '__main__':
    # Get file
    file = input('input file to read keys from: ')

    if not os.path.exists(file):
        print('file doesn\'t exist!')
        sys.exit()

    # Read in values
    slugs = []

    _, ext = os.path.splitext(file)

    if ext == '.csv':
        with open(file, newline='') as file_obj:
            reader = csv.DictReader(file_obj)

            for row in reader:
                slug = row['startgg slug']

                if len(row) > 1:
                    is_invit = row['Is Invitational?'].lower() in true_values
                else:
                    is_invit = False

                slugs.append({'slug': slug, 'invit': is_invit})
    else:
        with open(file) as file_obj:
            for row in file_obj:
                slugs.append({'slug': row.strip(), 'invit': False})

    print('read values')

    results = bulk_score(slugs)
    write_results(results)