import requests
import json

BASE_URL = 'http://localhost:8000'

# Test the debug endpoint
project_id = 36  # From previous test
resp = requests.get(f'{BASE_URL}/debug/project/{project_id}')
data = resp.json()

print(f"Project {project_id}:")
print(f"  Activities: {data['counts']['activities']}")
if data.get('project'):
    acts = data['project'].get('activities', [])
    for act in acts[:5]:
        print(f"    - {act.get('activity_id')}: {act.get('name')}")
