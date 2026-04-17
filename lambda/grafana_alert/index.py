import json
import boto3
import urllib.request
import urllib.error

def send_response(event, context, status, data):
    body = json.dumps({
        'Status': status,
        'Reason': 'See CloudWatch logs',
        'PhysicalResourceId': context.log_stream_name,
        'StackId': event['StackId'],
        'RequestId': event['RequestId'],
        'LogicalResourceId': event['LogicalResourceId'],
        'Data': data
    })
    req = urllib.request.Request(
        event['ResponseURL'],
        data=body.encode(),
        headers={'content-type': '', 'content-length': str(len(body))},
        method='PUT'
    )
    urllib.request.urlopen(req)
    print(f"Response sent: {status}")

def create_key(client, workspace_id, name):
    return client.create_workspace_api_key(
        workspaceId=workspace_id, keyName=name,
        keyRole='ADMIN', secondsToLive=300)['key']

def delete_key(client, workspace_id, name):
    try:
        client.delete_workspace_api_key(
            workspaceId=workspace_id, keyName=name)
    except Exception as e:
        print(f"Warning: {e}")

def call_grafana(endpoint, token, method, path, payload=None):
    url  = f"https://{endpoint}{path}"
    body = json.dumps(payload).encode() if payload else None
    req  = urllib.request.Request(
        url, data=body, method=method,
        headers={'Authorization': f'Bearer {token}',
                 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise Exception(f"HTTP {e.code}: {e.read().decode()}")

def handler(event, context):
    print(json.dumps(event))
    props        = event['ResourceProperties']
    workspace_id = props['WorkspaceId']
    region       = props.get('Region', 'us-east-1')
    runbook_url  = props.get('RunbookUrl', 'https://github.com/adinarayanap/aws-observability-grafana/blob/main/docs/runbooks/server-down.md')
    endpoint     = f"{workspace_id}.grafana-workspace.{region}.amazonaws.com"
    key_name     = f"cfn-alert-{workspace_id[:8]}"
    client       = boto3.client('grafana', region_name=region)
    token        = None
    try:
        if event['RequestType'] == 'Delete':
            send_response(event, context, 'SUCCESS', {})
            return
        token = create_key(client, workspace_id, key_name)
        try:
            folder = call_grafana(endpoint, token, 'POST', '/api/folders',
                {"title": "Platform Alerts", "uid": "platform-alerts"})
            folder_uid = folder.get('uid', 'platform-alerts')
        except Exception:
            folder_uid = 'platform-alerts'

        alert_group = {
            "name": "Server Down Alerts",
            "interval": "1m",
            "rules": [{
                "uid": "server-down-rule",
                "title": "Server Down — EC2 Status Check Failed",
                "condition": "C",
                "for": "2m",
                "labels": {"severity": "critical", "team": "platform", "service": "ec2"},
                "annotations": {
                    "summary": "SERVER IS DOWN — EC2 status check failed",
                    "description": "EC2 instance status check failed for 2 consecutive minutes.",
                    "runbook_url": runbook_url
                },
                "data": [
                    {"refId": "A", "datasourceUid": "default",
                     "relativeTimeRange": {"from": 300, "to": 0},
                     "model": {"datasource": {"type": "cloudwatch", "uid": "default"},
                               "dimensions": {}, "metricName": "StatusCheckFailed",
                               "namespace": "AWS/EC2", "period": "60",
                               "queryMode": "Metrics", "refId": "A",
                               "region": region, "statistic": "Maximum"}},
                    {"refId": "B", "datasourceUid": "__expr__",
                     "relativeTimeRange": {"from": 300, "to": 0},
                     "model": {"type": "reduce", "datasource": {"type": "__expr__", "uid": "__expr__"},
                               "expression": "A", "reducer": "last", "refId": "B"}},
                    {"refId": "C", "datasourceUid": "__expr__",
                     "relativeTimeRange": {"from": 300, "to": 0},
                     "model": {"type": "threshold", "datasource": {"type": "__expr__", "uid": "__expr__"},
                               "expression": "B", "refId": "C",
                               "conditions": [{"evaluator": {"type": "gt", "params": [0]},
                                               "operator": {"type": "and"},
                                               "query": {"params": ["B"]},
                                               "reducer": {"type": "last"}}]}}
                ],
                "noDataState": "Alerting", "execErrState": "Alerting", "isPaused": False
            }]
        }
        result = call_grafana(endpoint, token, 'POST',
            f'/api/ruler/grafana/api/v1/rules/{folder_uid}', alert_group)
        print(f"Alert created: {result}")
        send_response(event, context, 'SUCCESS',
            {'Message': 'Server down alert created', 'FolderUid': folder_uid})
    except Exception as e:
        print(f"Error: {e}")
        send_response(event, context, 'FAILED', {'Error': str(e)})
    finally:
        if token:
            delete_key(client, workspace_id, key_name)
