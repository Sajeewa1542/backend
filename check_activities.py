import json
with open('backend/data/project_1.json') as f:
    p = json.load(f)
    
acts = p.get('activities', [])
print(f'Project 1 has {len(acts)} activities')
for act in acts:
    if str(act.get('activity_id')) in ['58', '60']:
        print(f"Activity {act.get('activity_id')}: {act.get('name')}")
