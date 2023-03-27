import argparse
from operator import length_hint
import sys
from threading import Thread
from urllib.error import HTTPError
from bs4 import BeautifulSoup
import os
from jira.client import JIRA
import time
from pathlib import Path
from getpass import getpass, getuser
from urllib.parse import parse_qs, urlparse
from jira.client import JIRA
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timedelta

AD_USER = getuser()
now = time.time()


token_path = os.path.join("/Users", AD_USER, ".jira","token")
print(token_path)
try:
    file_size = os.stat(token_path).st_size
except:
    file_size = 0
if file_size != 0:
    global AD_TOKEN
    f=open(token_path, "r")
    AD_TOKEN = f.read()
    f.close()
    print("AD Token found!\n##########")
else:
    print("AD Token")
    AD_TOKEN = getpass(prompt='Enter your AD_TOKEN: ', stream=None) 
    f = open(token_path,"w+")
    f.write(AD_TOKEN)
    f.close()
    
options = {'server': "https://splunk.atlassian.net"}

try:
    jira = JIRA(options=options, basic_auth=(AD_USER + '@splunk.com', AD_TOKEN))
except Exception as e:
        raise RuntimeError(f'Unable to logged in into "JIRA" ({e})')


def suffix(d):
    return 'th' if 11 <= d <= 13 else {1:'st',2:'nd',3:'rd'}.get(d % 10, 'th')



def custom_strftime(format, t):
    if t.time() < datetime.strptime('06:30:00', '%H:%M:%S').time():
        # If the time is before 6:30 AM, use yesterday's date
        t -= timedelta(days=1)
    return t.strftime(format).replace('{S}', str(t.day) + suffix(t.day))


def find_TO(JOB):
    query = 'project = "TechOps" AND text ~ "' + JOB +'"'
    issues = jira.search_issues(query)
    for issue in issues:
        jiras=(str(issue))
    return jiras

def getJiraStatus(JOB):
    to = find_TO(JOB)
    jira_status = jira.issue(to).raw["fields"]["status"]["name"]
    print(JOB, jira_status, to)

    for row in sheet_state['values'][::-1]:
        if row[0] == JOB:
            if row[-1].lower() == "job-completed":
                print(f"## Skipping as status for {JOB} is JOB-COMPLETED ##\n")
                jira_status = row[-1]
            else:
                print("\n")
            break

    return jira_status


def conditional_formatting(spreadsheet_id):
    """
    Creates the batch_update the user has access to.
    Load pre-authorized user credentials from the environment.
    TODO(developer) - See https://developers.google.com/identity
    for guides on implementing OAuth2 for the application.
        """
    creds, _ = google.auth.default()
    # pylint: disable=maybe-no-member
    try:
        service = build('sheets', 'v4', credentials=creds)

        my_range = {
            'sheetId': 0,
            'startRowIndex': 1,
            'endRowIndex': 11,
            'startColumnIndex': 0,
            'endColumnIndex': 4,
        }
        requests = [{
            'addConditionalFormatRule': {
                'rule': {
                    'ranges': [my_range],
                    'booleanRule': {
                        'condition': {
                            'type': 'CUSTOM_FORMULA',
                            'values': [{
                                'userEnteredValue':
                                    '=GT($D2,median($D$2:$D$11))'
                            }]
                        },
                        'format': {
                            'textFormat': {
                                'foregroundColor': {'red': 0.8}
                            }
                        }
                    }
                },
                'index': 0
            }
        }, {
            'addConditionalFormatRule': {
                'rule': {
                    'ranges': [my_range],
                    'booleanRule': {
                        'condition': {
                            'type': 'CUSTOM_FORMULA',
                            'values': [{
                                'userEnteredValue':
                                    '=LT($D2,median($D$2:$D$11))'
                            }]
                        },
                        'format': {
                            'backgroundColor': {
                                'red': 1,
                                'green': 0.4,
                                'blue': 0.4
                            }
                        }
                    }
                },
                'index': 0
            }
        }]
        body = {
            'requests': requests
        }
        response = service.spreadsheets() \
            .batchUpdate(spreadsheetId=spreadsheet_id, body=body).execute()
        print(f"{(len(response.get('replies')))} cells updated.")
        return response

    except HTTPError as error:
        print(f"An error occurred: {error}")
        return error



output = []

def process_job_id(job, current_status):
    status = getJiraStatus(job)
    current_status.update( {job : status} )


def main():
    global sheet_state
    sheet_name = custom_strftime('{S} %b', datetime.now())
    print(sheet_name)
    

    # If modifying these scopes, delete the file token.json.
    SERVICE_ACCOUNT_FILE = 'keys.json'
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

    creds = None
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)

    # The ID and range of a sample spreadsheet.
    SAMPLE_SPREADSHEET_ID = '1kq5i69XwvTJBRkLAb47LTkGV-CE3-oxTDPU4Qh5xBBc'

    service = build('sheets', 'v4', credentials=creds)

    # Call the Sheets API
    sheet = service.spreadsheets()
    
    
    sheet_state = sheet.values().get(spreadsheetId=SAMPLE_SPREADSHEET_ID, range=f"{sheet_name}!B2:H").execute()
    
    job_ids = [row[0] for row in sheet_state['values']]
    status_sheet = [row[-1] for row in sheet_state['values']]
    
    print("\nStatus on sheet: ",status_sheet)
    print("\nJOBs on sheet: ", job_ids)
    
    #print(job_sheet.get('values', []))
    
    total_rows = len(job_ids)
    closed_count = sum(1 for row in sheet_state['values'] if row[-1].lower() in ("job-completed", "closed"))
    
    if closed_count == total_rows:
        print("\n\nAll jobs have been completed/closed. Exiting the script.")
        sys.exit()
    
    print("\n\n")
    # Process JOBs in parallel
    threads = []
    current_status = {}
    for job_id in job_ids:
        thread = Thread(target=process_job_id, args=(job_id, current_status))
        thread.start()
        threads.append(thread)

    for thread in threads:
        thread.join()
    
    # Update spreadsheet with job_sheets
    for job in job_ids:
        output.append([current_status[job]])
    
#    for job in job_sheet['values']:
#        output.append([current_status[job[0]]])
    
    #values = [[status] for status in output]
    print("\nCurrent Status: ", output)
    sheet = service.spreadsheets()
    job_sheet = sheet.values().update(spreadsheetId=SAMPLE_SPREADSHEET_ID, range=f"{sheet_name}!H2", valueInputOption="USER_ENTERED", body={"values":output}).execute()
    print("Sheet Updated")

main()