import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from backend.storage_manager import StorageManager
from backend.engine import TimeEngine

# Create project
storage = StorageManager('backend/data')
project = storage.create_project(name='TestAct', boq_filename='test.csv', rate_breakdown_filename='rb.csv', schedule_filename='sched.csv')
project_id = project['id']
print('Created project:', project_id)

# Parse schedule
engine = TimeEngine()
activities = engine.parse_schedule('test_data/asphalt_schedule.csv', project_id=project_id)
print('Parsed', len(activities), 'activities')

# Add to storage
count = storage.add_activities(project_id, activities)
print('Added', count, 'activities to storage')

# Verify
project_after = storage.get_project(project_id)
print('Project now has', len(project_after.get('activities', [])), 'activities')
if project_after.get('activities'):
    print('First activity:', project_after['activities'][0])
