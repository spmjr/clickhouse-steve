#!/usr/bin/env python3

import logging
import json
import time
import fnmatch
from collections import namedtuple

import requests
import boto3

API_URL = 'https://api.github.com/repos/ClickHouse/ClickHouse/'

SUSPICIOUS_CHANGED_FILES_NUMBER = 200

SUSPICIOUS_PATTERNS = [
    "tests/ci/*",
    "docs/tools/*",
    ".github/*",
    "utils/release/*",
    "docker/*",
    "release",
]

MAX_RETRY = 5

WorkflowDescription = namedtuple('WorkflowDescription',
                                 ['action', 'run_id', 'event', 'sender_login', 'fork_owner_login', 'fork_branch', 'sender_orgs'])

TRUSTED_ORG_IDS = {
    7409213,   # yandex
    28471076,  # altinity
    54801242,  # clickhouse
}

# Individual trusted contirbutors who are not in any trusted organization.
# Can be changed in runtime: we will append users that we learned to be in
# a trusted org, to save GitHub API calls.
TRUSTED_CONTRIBUTORS = {
    "achimbab",
    "adevyatova ",  # DOCSUP
    "Algunenano",   # Raúl Marín, Tinybird
    "AnaUvarova",   # DOCSUP
    "anauvarova",   # technical writer, Yandex
    "annvsh",       # technical writer, Yandex
    "atereh",       # DOCSUP
    "azat",
    "bharatnc",     # Newbie, but already with many contributions.
    "bobrik",       # Seasoned contributor, CloundFlare
    "BohuTANG",
    "damozhaeva",   # DOCSUP
    "den-crane",
    "gyuton",       # DOCSUP
    "gyuton",       # technical writer, Yandex
    "hagen1778",    # Roman Khavronenko, seasoned contributor
    "hczhcz",
    "hexiaoting",   # Seasoned contributor
    "ildus",        # adjust, ex-pgpro
    "javisantana",  # a Spanish ClickHouse enthusiast, ex-Carto
    "ka1bi4",       # DOCSUP
    "kirillikoff",  # DOCSUP
    "kitaisreal",   # Seasoned contributor
    "kreuzerkrieg",
    "lehasm",       # DOCSUP
    "michon470",    # DOCSUP
    "MyroTk",       # Tester in Altinity
    "myrrc",        # Michael Kot, Altinity
    "nikvas0",
    "nvartolomei",
    "olgarev",      # DOCSUP
    "otrazhenia",   # Yandex docs contractor
    "pdv-ru",       # DOCSUP
    "podshumok",    # cmake expert from QRator Labs
    "s-mx",         # Maxim Sabyanin, former employee, present contributor
    "sevirov",      # technical writer, Yandex
    "spongedu",     # Seasoned contributor
    "ucasFL",       # Amos Bird's friend
    "vdimir",       # Employee
    "vzakaznikov",
    "YiuRULE",
    "zlobober"      # Developer of YT
}

def is_trusted_sender(pr_user_login, pr_user_orgs):
    if pr_user_login in TRUSTED_CONTRIBUTORS:
        logging.info("User '%s' is trusted", pr_user_login)
        return True

    logging.info("User '%s' is not trusted", pr_user_login)

    for org_id in pr_user_orgs:
        if org_id in TRUSTED_ORG_IDS:
            logging.info("Org '%s' is trusted; will mark user %s as trusted", org_id, pr_user_login)
            return True
        logging.info("Org '%s' is not trusted", org_id)

    return False

def _exec_get_with_retry(url):
    for i in range(MAX_RETRY):
        try:
            response = requests.get(url)
            response.raise_for_status()
            return response.json()
        except Exception as ex:
            logging.info("Got exception executing request %s", ex)
            time.sleep(i + 1)

    raise Exception("Cannot execute GET request with retries")

def _exec_post_with_retry(url, token, data=None):
    headers = {
        "Authorization": f"token {token}"
    }
    for i in range(MAX_RETRY):
        try:
            if data:
                response = requests.post(url, headers=headers, json=data)
            else:
                response = requests.post(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except Exception as ex:
            logging.info("Got exception executing request %s", ex)
            time.sleep(i + 1)

    raise Exception("Cannot execute POST request with retry")


def _get_pull_requests_from(owner, branch):
    url = f"{API_URL}/pulls?head={owner}:{branch}"
    return _exec_get_with_retry(url)


def get_workflow_description_from_event(event):
    action = event['action']
    sender_login = event['sender']['login']
    run_id = event['workflow_run']['id']
    event = event['workflow_run']['event']
    fork_owner = event['workflow_run']['head_repository']['owner']['login']
    fork_branch = event['workflow_run']['head_branch']
    orgs_data = _exec_get_with_retry(event['sender']['organizations_url'])
    sender_orgs = [org['id'] for org in orgs_data]
    return WorkflowDescription(
        action=action,
        sender_login=sender_login,
        run_id=run_id,
        event=event,
        fork_owner_login=fork_owner,
        fork_branch=fork_branch,
        sender_orgs=sender_orgs,
    )


def get_changed_files_for_pull_request(pull_request):
    number = pull_request['number']

    changed_files = set([])
    for i in range(1, 31):
        logging.info("Requesting changed files page %s", i)
        url = f"{API_URL}/pulls/{number}/files?page={i}&per_page=100"
        data = _exec_get_with_retry(url)
        logging.info("Got %s changed files", len(data))
        for change in data:
            logging.info("Adding changed file %s", change['filename'])
            changed_files.add(change['filename'])

        if len(changed_files) >= SUSPICIOUS_CHANGED_FILES_NUMBER:
            logging.info("More than %s changed files. Will stop fetching new files.", len(changed_files))
            break

    return changed_files

def check_suspicious_changed_files(changed_files):
    if len(changed_files) >= SUSPICIOUS_CHANGED_FILES_NUMBER:
        logging.info("Too many files changed %s, need manual approve", len(changed_files))
        return True

    for path in changed_files:
        for pattern in SUSPICIOUS_PATTERNS:
            if fnmatch.fnmatch(path, pattern):
                logging.info("File %s match suspicious pattern %s, will not approve automatically", path, pattern)
                return True
            logging.info("File %s doesn't match suspicious pattern %s", path, pattern)

    logging.info("No changed files match suspicious patterns, run will be approved")
    return False

def approve_run(run_id, token):
    url = f"{API_URL}/actions/runs/{run_id}/approve"
    _exec_post_with_retry(url, token)

def label_manual_approve(pull_request, token):
    number = pull_request['number']
    url = f"{API_URL}/issues/{number}/labels"
    data = {"labels" : "manual approve"}

    _exec_post_with_retry(url, token, data)

def get_token_from_aws():
    secret_name = "clickhouse_robot_token"
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
    )
    get_secret_value_response = client.get_secret_value(
        SecretId=secret_name
    )
    data = json.loads(get_secret_value_response['SecretString'])
    return data['clickhouse_robot_token']

def main(event):
    token = get_token_from_aws()
    workflow_description = get_workflow_description_from_event(event)
    logging.info("Got workflow description %s", workflow_description)

    if is_trusted_sender(workflow_description.sender_login, workflow_description.sender_orgs):
        approve_run(workflow_description.run_id, token)
        return

    pull_requests = _get_pull_requests_from(workflow_description.fork_owner_login, workflow_description.fork_branch)
    logging.info("Got pull requests for workflow %s", len(pull_requests))
    if len(pull_requests) > 1:
        raise Exception("Received more than one PR for workflow run")

    if len(pull_requests) < 1:
        raise Exception("Cannot find any pull requests for workflow run")

    pull_request = pull_requests[0]
    logging.info("Pull request for workflow number %s", pull_request['number'])

    changed_files = get_changed_files_for_pull_request(pull_request)
    logging.info("Totally have %s changed files in PR", len(changed_files))
    if check_suspicious_changed_files(changed_files):
        logging.info("Pull Request %s has suspicious changes, label it for manuall approve", pull_request['number'])
        label_manual_approve(pull_request, token)
    else:
        logging.info("Pull Request %s has no suspicious changes", pull_request['number'])
        approve_run(workflow_description.run_id, token)

def handler(event, _):
    logging.basicConfig(level=logging.INFO)
    main(event)
