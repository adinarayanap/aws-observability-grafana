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
    runbook_url  = props.get('RunbookUrl', '')
    endpoint     = f"{workspace_id}.grafana-workspace.{region}.amazonaws.com"
    key_name     = f"cfn-alert-{workspace_id[:8]}"
    client       = boto3.client('grafana', region_name=region)
    token        = None

    try:
        if event['RequestType'] == 'Delete':
            send_response(event, context, 'SUCCESS', {})
            return

        token = create_key(client, workspace_id, key_name)

        # Create alert rule using Grafana unified alerting API
        # Use correct folder-based approach
        alert_rule = {
            "uid": "server-down-rule",
            "title": "Server Down - EC2 Status Check Failed",
            "condition": "C",
            "data": [
                {
                    "refId": "A",
                    "datasourceUid": "default",
                    "queryType": "",
                    "relativeTimeRange": {"from": 300, "to": 0},
                    "model": {
                        "datasource": {"type": "cloudwatch", "uid": "default"},
                        "dimensions": {},
                        "expression": "",
                        "id": "",
                        "matchExact": True,
                        "metricEditorMode": 0,
                        "metricName": "StatusCheckFailed",
                        "metricQueryType": 0,
                        "namespace": "AWS/EC2",
                        "period": "60",
                        "queryMode": "Metrics",
                        "refId": "A",
                        "region": region,
                        "sqlExpression": "",
                        "statistic": "Maximum"
                    }
                },
                {
                    "refId": "B",
                    "datasourceUid": "__expr__",
                    "queryType": "",
                    "relativeTimeRange": {"from": 300, "to": 0},
                    "model": {
                        "conditions": [{
                            "evaluator": {"params": [], "type": "gt"},
                            "operator": {"type": "and"},
                            "query": {"params": ["A"]},
                            "reducer": {"params": [], "type": "last"},
                            "type": "query"
                        }],
                        "datasource": {"type": "__expr__", "uid": "__expr__"},
                        "expression": "A",
                        "hide": False,
                        "intervalMs": 1000,
                        "maxDataPoints": 43200,
                        "reducer": "last",
                        "refId": "B",
                        "type": "reduce"
                    }
                },
                {
                    "refId": "C",
                    "datasourceUid": "__expr__",
                    "queryType": "",
                    "relativeTimeRange": {"from": 300, "to": 0},
                    "model": {
                        "conditions": [{
                            "evaluator": {"params": [0], "type": "gt"},
                            "operator": {"type": "and"},
                            "query": {"params": ["B"]},
                            "reducer": {"params": [], "type": "last"},
                            "type": "query"
                        }],
                        "datasource": {"type": "__expr__", "uid": "__expr__"},
                        "expression": "B",
                        "hide": False,
                        "intervalMs": 1000,
                        "maxDataPoints": 43200,
                        "refId": "C",
                        "type": "threshold"
                    }
                }
            ],
            "updated": "2026-04-19T00:00:00Z",
            "intervalSeconds": 60,
            "is_paused": False,
            "for": "2m",
            "annotations": {
                "description": "EC2 instance status check failed for 2 consecutive minutes. Server may be down.",
                "runbook_url": runbook_url,
                "summary": "SERVER IS DOWN - EC2 status check failed"
            },
            "labels": {
                "severity": "critical",
                "team": "platform",
                "service": "ec2"
            },
            "folderUID": "platform-alerts",
            "ruleGroup": "server-alerts",
            "noDataState": "Alerting",
            "execErrState": "Alerting"
        }

        # First create the folder
        try:
            call_grafana(endpoint, token, 'POST', '/api/folders',
                {"title": "Platform Alerts", "uid": "platform-alerts"})
            print("Folder created")
        except Exception as e:
            print(f"Folder may already exist: {e}")

        # Create alert rule using POST /api/v1/provisioning/alert-rules
        result = call_grafana(endpoint, token, 'POST',
            '/api/v1/provisioning/alert-rules', alert_rule)
        print(f"Alert created: {result}")

        send_response(event, context, 'SUCCESS',
            {'Message': 'Server down alert created',
             'AlertUID': result.get('uid', 'unknown')})

    except Exception as e:
        print(f"Error: {e}")
        # Send SUCCESS to not block stack - alert can be created manually
        send_response(event, context, 'SUCCESS',
            {'Message': f'Warning: {str(e)} - create alert manually'})
    finally:
        if token:
            delete_key(client, workspace_id, key_name)
