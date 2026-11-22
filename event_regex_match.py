import re

def list_regex_match(haystack: str, series: list):
    for needle in series:
        if re.search(needle.lower(), haystack.lower()): # is lower here fine?
            return "Regex matched: " + needle
    return False

def regex_match(event_str: str,
                tournament_str: str,
                ranked_series: list,
                unranked_series: list,
                online_series: list):
    if rv := list_regex_match(event_str, online_series):
        return ["online", rv]
    if rv := list_regex_match(tournament_str, online_series):
        return ["online", rv]

    if rv := list_regex_match(event_str, unranked_series):
        return ["unranked", rv]
    if rv := list_regex_match(tournament_str, unranked_series):
        return ["unranked", rv]

    if rv := list_regex_match(event_str, ranked_series):
        return ["ranked", rv]
    if rv := list_regex_match(tournament_str, ranked_series):
        return ["ranked", rv]

    return None