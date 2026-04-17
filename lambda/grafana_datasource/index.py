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
    endpoint     = f"{workspace_id}.grafana-workspace.{region}.amazonaws.com"
    key_name     = f"cfn-ds-{workspace_id[:8]}"
    client       = boto3.client('grafana', region_name=region)
    token        = None
    try:
        if event['RequestType'] == 'Delete':
            send_response(event, context, 'SUCCESS', {})
            return
        token  = create_key(client, workspace_id, key_name)
        result = call_grafana(endpoint, token, 'POST', '/api/datasources', {
            "name": "CloudWatch", "type": "cloudwatch",
            "access": "proxy", "isDefault": True,
            "jsonData": {"authType": "default", "defaultRegion": region}
        })
        print(f"Datasource: {result}")
        send_response(event, context, 'SUCCESS', {'Message': 'CloudWatch datasource configured'})
    except Exception as e:
        print(f"Error: {e}")
        send_response(event, context, 'FAILED', {'Error': str(e)})
    finally:
        if token:
            delete_key(client, workspace_id, key_name)
