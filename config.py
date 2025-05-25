import os
AZURE_ORG_URL = "https://israelmoi-vsts.visualstudio.com/"
AZURE_PROJECT = "PORTAL-INFO"
GITLAB_URL = "https://gitlab.moin.gov.il"
GITLAB_PROJECT_ID = 12  # GitLab numeric ID or path
AZURE_PAT = os.getenv('AZURE_PAT')
GITLAB_PAT = os.getenv('GITLAB_PAT')
