import os
import sys

# Add current directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.supabase_client import supabase

def seed_test_data():
    try:
        # Create a Project
        new_project = {
            "name": "Sviluppo HipA v2",
            "acronym": "HIPA2",
            "identifier": "HIP",
            "funding_agency": "Ateneo",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31"
        }
        res_p = supabase.table("projects").insert(new_project).execute()
        proj_id = res_p.data[0]['id']
        
        # Create a Deliverable
        new_deliv = {
            "project_id": proj_id,
            "name": "Rilascio Piattaforma Core",
            "type": "prototype",
            "status": "In progress",
            "deadline": "2026-06-30"
        }
        res_d = supabase.table("deliverables").insert(new_deliv).execute()
        deliv_id = res_d.data[0]['id']
        
        # Create Tasks
        # Task 1: Assigned to admin
        task_1 = {
            "sequence_id": "HIP-01",
            "project_id": proj_id,
            "deliverable_id": deliv_id,
            "name": "Setup Database Supabase",
            "owner_email": "luigi.boccia@unical.it",
            "supervisor_email": "luigi.boccia@unical.it",
            "status": "Working on",
            "priority": "high",
            "sort_order": 1
        }
        
        # Task 2: Assigned to user
        task_2 = {
            "sequence_id": "HIP-02",
            "project_id": proj_id,
            "deliverable_id": deliv_id,
            "name": "Design Interfaccia",
            "owner_email": "user@maic.it",
            "supervisor_email": "luigi.boccia@unical.it",
            "status": "Not started",
            "priority": "medium",
            "sort_order": 2
        }
        
        supabase.table("tasks").insert([task_1, task_2]).execute()
        print("Data seeded successfully!")
        
    except Exception as e:
        print(f"Error seeding data: {e}")

if __name__ == "__main__":
    # Check if a project already exists
    res = supabase.table("projects").select("id").limit(1).execute()
    if len(res.data) == 0:
        seed_test_data()
    else:
        print("Data already seeded.")
