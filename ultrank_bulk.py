from ultrank_tiering import Tournament, TournamentTieringResult
from startgg_toolkit import startgg_slug_regex
from sheets_io import write_unsorted_events, write_valid_events
from datetime import datetime
import csv
import os 
import re
import sys

true_values = ['true', 't', '1']

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


def write_results(results, valid_slugs, invalid_slugs):

    ranked_results = []
    unsorted_results = []

    for result in results:
        formatted_result = []
        if isinstance(result, TournamentTieringResult):
            formatted_result = [result.date.isoformat(), result.tournament, result.event, result.region.note, result.slug, 
                                str(result.is_invitational), result.score, result.max_potential_score(), result.entrants,
                                str(result.should_count())]

            if result.slug in valid_slugs:
                ranked_results.append(formatted_result)
            else:
                unsorted_results.append(formatted_result)
        else:
            print("Error: Not a valid TournamentTieringResult -- ", result)
            continue

    write_unsorted_events(unsorted_results, valid_slugs, invalid_slugs)
    write_valid_events(ranked_results, invalid_slugs)

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