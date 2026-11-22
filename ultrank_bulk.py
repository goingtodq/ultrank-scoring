from event_regex_match import regex_match
from ultrank_tiering import Tournament, TournamentTieringResult
from sheets_io import write_events, fetch_event_regex
from datetime import datetime
from Levenshtein import jaro_winkler
from startgg_toolkit import send_request
from datetime import datetime, timedelta

class _Tournament:
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
        resp = send_request(query, variables)
        if resp['data']['tournament'] is None:
            print(resp)
            return None


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
        tournaments.extend([_Tournament(tournament['name'], tournament['slug'], tournament['startAt']) for tournament in resp['data']['tournament']['owner']['tournaments']['nodes'] if (
            tournament['owner']['id'] == tournament_owner_id and tournament['slug'] != tournament_slug and tournament['startAt'] >= range_start and tournament['startAt'] <= tournament_start
            and tournament['hasOfflineEvents'])])

        # Check if all tournaments are before the requested tournament.
        # Since the API returns tournaments in reverse chronological order 
        # (maybe not good to rely on, but the alternative also sucks), 
        # this means that we don't need to check the rest.
        if resp['data']['tournament']['owner']['tournaments']['nodes'][-1]['startAt'] < tournament_start:
            break

        if page >= resp['data']['tournament']['owner']['tournaments']['pageInfo']['totalPages']:
            break
        page += 1

    tournaments.insert(0, _Tournament(tournament_name, tournament_slug, tournament_start))

    return tournaments


def check_potential_weekly(tournamentSlug):
    other_admined_tournaments = get_admined_tournaments(tournamentSlug)

    # TODO: Should never logically happen apart from deletion scenarios. Why is this triggered?
    if other_admined_tournaments is None:
        return None

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

def classify_event(event: TournamentTieringResult,
                   ranked_series: list,
                   unranked_series: list,
                   online_series: list):
    """Classifies an event with some string matching + an extra check for weeklies."""
    category = "unknown"
    reason = None

    if event.event_type != 1:
        return ["not_singles", "Not a singles event"]

    if check_blacklist(event.ownerDiscriminator):
        return ["blacklisted", 'Tournament Creator Blacklisted']

    if event.is_online:
        return ["online", "Online Event"]

    match = regex_match(event.event, event.tournament, ranked_series, unranked_series, online_series)
    if match is not None:
        return match

    potential_weekly = check_potential_weekly(event.tournamentSlug)
    if potential_weekly is not None:
        days_since = str(
            round(potential_weekly.time_since / (24 * 60 * 60)))
        reason = 'Probable Weekly [{:.5f}] (found tournament {} [{}] which precedes by {} days)'.format(potential_weekly.similarity, potential_weekly.name, potential_weekly.slug, days_since)
        category = "probable_weekly"

    return [category, reason]

def bulk_score(events):
    """Scores multiple ids (previously slug), and returns the resultant result."""

    # Get values
    results = []

    for event in events:
        id = event['id']
        invit = event['invit']

        print('calculating for id {}'.format(id))

        try:
            t = Tournament(id, invit)
            result = t.calculate_tier()
            results.append(result)
        except Exception as e:
            print(e)
            print('catastrophic failure')

    return results


def write_results(results):
    formatted_results = []

    event_regex = fetch_event_regex()
    for result in results:
        formatted_result = []
        if isinstance(result, TournamentTieringResult):
            formatted_result = [result.date.isoformat().replace("+00:00", ""), 
                                result.event_date.isoformat().replace("+00:00", ""), 
                                result.tournament, 
                                result.activity_state, 
                                "", 
                                result.is_online, 
                                result.set_progress, 
                                "", 
                                "", 
                                "", 
                                result.event, 
                                result.event_type, 
                                result.region.note, 
                                result.event_id, 
                                result.slug, 
                                result.score, 
                                result.max_potential_score(), 
                                "", 
                                result.entrants,
                                str(result.should_count_strict()),
                                str(result.should_count())]
            formatted_result += classify_event(result, *event_regex)
            formatted_result += [""]

            formatted_results.append(formatted_result)
        else:
            print("Error: Not a valid TournamentTieringResult -- ", result)
            continue

    write_events(formatted_results)