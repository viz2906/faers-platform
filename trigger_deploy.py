import subprocess, json, sys

def codedeploy(app, dg, appspec_file, description):
    with open(appspec_file) as f:
        content = f.read()
    revision = json.dumps({
        "revisionType": "AppSpecContent",
        "appSpecContent": {"content": content}
    })
    result = subprocess.run([
        r"C:\Program Files\Amazon\AWSCLIV2\aws.exe",
        "deploy", "create-deployment",
        "--application-name", app,
        "--deployment-group-name", dg,
        "--revision", f"revisionType=AppSpecContent,appSpecContent={{content={json.dumps(content)}}}",
        "--description", description,
        "--output", "json"
    ], capture_output=True, text=True)
    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)
    return result

print("=== Deploying API (task def :4) ===")
r1 = codedeploy("faers-prod-api", "faers-prod-api-dg", "appspec_api.json", "API rev4: analytics fix + redis status + gemini")
print()
print("=== Deploying Frontend (task def :2) ===")
r2 = codedeploy("faers-prod-frontend", "faers-prod-frontend-dg", "appspec_fe.json", "Frontend rev2: relative API URL fix")
