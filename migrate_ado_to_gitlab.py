import json
import random
from azure.devops.connection import Connection
from msrest.authentication import BasicAuthentication
import gitlab
from config import AZURE_ORG_URL, AZURE_PROJECT, AZURE_PAT, GITLAB_URL, GITLAB_PAT, GITLAB_PROJECT_ID

# Initialize Azure DevOps connection
credentials = BasicAuthentication('', AZURE_PAT)
connection = Connection(base_url=AZURE_ORG_URL, creds=credentials)
wit_client = connection.clients.get_work_item_tracking_client()

# Initialize GitLab connection
gl = gitlab.Gitlab(GITLAB_URL, private_token=GITLAB_PAT)
project = gl.projects.get(GITLAB_PROJECT_ID)
group = gl.groups.get(project.namespace['id'])

# Query ADO work items
wiql = {
    'query': f"SELECT [System.Id], [System.Title], [System.Description], [System.WorkItemType], [System.State] FROM WorkItems WHERE [System.TeamProject] = '{AZURE_PROJECT}'"
}
ado_id_to_gitlab = {}

wiql_result = wit_client.query_by_wiql(wiql).work_items

# Phase 1: Create Epics and Issues
for wi_ref in wiql_result:
    work_item = wit_client.get_work_item(wi_ref.id, expand="Relations")
    title = work_item.fields.get("System.Title", "No Title")
    description = work_item.fields.get("System.Description", "")
    ado_type = work_item.fields.get("System.WorkItemType", "WorkItem")
    ado_state = work_item.fields.get("System.State", "Undefined")

    body = f"{description}\n\n---\nMigrated from ADO #{work_item.id} (State: {ado_state})"

    # Create labels if they don't exist
    for label in [ado_type, ado_state]:
        try:
            project.labels.create({'name': label, 'color': "#{:06x}".format(random.randint(0, 0xFFFFFF))})
        except gitlab.exceptions.GitlabCreateError:
            pass  # Label exists

    # Epic or Issue
    if ado_type in ["Epic", "Feature"]:
        epic = group.epics.create({
            'title': title,
            'description': body
        })
        ado_id_to_gitlab[work_item.id] = {'type': 'epic', 'id': epic.iid}
        print(f"Created EPIC for ADO #{work_item.id} → GitLab Epic #{epic.iid}")
    else:
        issue = project.issues.create({
            'title': title,
            'description': body,
            'labels': [ado_type, ado_state]
        })
        ado_id_to_gitlab[work_item.id] = {'type': 'issue', 'id': issue.iid}
        print(f"Created ISSUE for ADO #{work_item.id} → GitLab Issue #{issue.iid}")

# Save mapping
# with open('ado_gitlab_map.json', 'w') as f:
#     json.dump(ado_id_to_gitlab, f, indent=2)

# Phase 2: Link Parent/Child Relations
print("\n--- Linking Parent/Child ---")

for wi_ref in wiql_result:
    work_item = wit_client.get_work_item(wi_ref.id, expand="Relations")
    relations = getattr(work_item, "relations", None)
    if relations is not None:
        for rel in relations:
            if rel.rel == "System.LinkTypes.Hierarchy-Forward":
                parent_id = int(rel.url.split("/")[-1])
                if parent_id in ado_id_to_gitlab and work_item.id in ado_id_to_gitlab:
                    parent = ado_id_to_gitlab[parent_id]
                    child = ado_id_to_gitlab[work_item.id]

                    if parent['type'] == 'epic' and child['type'] == 'issue':
                        epic = group.epics.get(parent['id'])
                        epic.add_issue({'issue_id': project.issues.get(child['id']).id})
                        print(f"Linked Issue #{child['id']} to Epic #{parent['id']}")
                    elif parent['type'] == 'issue' and child['type'] == 'issue':
                        parent_issue = project.issues.get(parent['id'])
                        parent_issue.links.create({
                            'target_project_id': GITLAB_PROJECT_ID,
                            'target_issue_iid': child['id'],
                            'link_type': 'relates_to'
                        })
                        print(f"Linked Issue #{parent['id']} → Issue #{child['id']}")
