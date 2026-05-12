import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from backend.main import _build_activity_candidates
from backend.keyword_normalization import load_keyword_normalization_map

# Setup
project = {
    'id': 'test',
    'name': 'test',
    'activities': [
        {'activity_id': 58, 'name': 'Asphaltic wearing course 20mm', 'duration': 30, 'is_critical': None, 'float': None, 'productivity': 180, 'unit': 'm2'},
        {'activity_id': 60, 'name': 'Asphalt wearing course', 'duration': 50, 'is_critical': None, 'float': None, 'productivity': 500, 'unit': 'm2'},
    ]
}

search_query = 'Engineer instructed additional asphalt wearing course work at junction tie-in areas and edge widening sections. This affects the asphalt concrete wearing course 40mm thick item in the BOQ. The revised total quantity is 58,549 m2.'
boq_item = {'description': 'Asphalt concrete in wearing course 40mm thick'}

activities = project['activities']
norm_map = load_keyword_normalization_map(project)

# Build candidates with BOQ item
cands = _build_activity_candidates(search_query, activities, norm_map, selected_boq_item=boq_item)

print('Activity Candidates:')
for c in cands:
    print('  ID:', c.get('activity_id'), 'Name:', c.get('name'), 'Score:', c.get('similarity_score'))
