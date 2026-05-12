import requests
import json
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE_URL = 'http://localhost:8000'

# Upload
print('Uploading files...')
files = {
    'boq': open('test_data/asphalt_boq.csv', 'rb'),
    'rate_breakdown': open('test_data/asphalt_rate_breakdown.csv', 'rb'),
    'schedule': open('test_data/asphalt_schedule.csv', 'rb'),
}
resp = requests.post(f'{BASE_URL}/upload/files', files=files)
upload_data = resp.json()
project_id = upload_data.get('data', {}).get('project_id')
print(f'Upload response: {upload_data}')
print(f'Project ID: {project_id}')

# Get project to verify
print('\nGetting project...')
resp = requests.get(f'{BASE_URL}/debug/project/{project_id}')
project = resp.json()
print(f'Project activities count: {len(project.get("activities", []))}')
if project.get('activities'):
    for act in project['activities'][:3]:
        print(f'  Activity {act.get("activity_id")}: {act.get("name")}')
