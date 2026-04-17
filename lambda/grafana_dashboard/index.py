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

def get_dashboards(bucket, prefix):
    s3   = boto3.client('s3')
    resp = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
    out  = []
    for obj in resp.get('Contents', []):
        if obj['Key'].endswith('.json'):
            body = s3.get_object(Bucket=bucket, Key=obj['Key'])['Body'].read()
            out.append(json.loads(body))
            print(f"Loaded: {obj['Key']}")
    return out

def handler(event, context):
    print(json.dumps(event))
    props        = event['ResourceProperties']
    workspace_id = props['WorkspaceId']
    region       = props.get('Region', 'us-east-1')
    bucket       = props['DashboardsBucket']
    prefix       = props.get('DashboardsPrefix', 'grafana/dashboards/')
    endpoint     = f"{workspace_id}.grafana-workspace.{region}.amazonaws.com"
    key_name     = f"cfn-dash-{workspace_id[:8]}"
    client       = boto3.client('grafana', region_name=region)
    token        = None
    try:
        if event['RequestType'] == 'Delete':
            send_response(event, context, 'SUCCESS', {})
            return
        token      = create_key(client, workspace_id, key_name)
        dashboards = get_dashboards(bucket, prefix)
        deployed   = []
        for dash in dashboards:
            result = call_grafana(
                endpoint, token, 'POST', '/api/dashboards/import',
                {"dashboard": dash, "overwrite": True, "folderId": 0})
            deployed.append(result.get('uid', 'unknown'))
            print(f"Deployed: {dash.get('title')} → {result.get('url')}")
        send_response(event, context, 'SUCCESS',
            {'Count': str(len(deployed)), 'Deployed': ','.join(deployed)})
    except Exception as e:
        print(f"Error: {e}")
        send_response(event, context, 'FAILED', {'Error': str(e)})
    finally:
        if token:
            delete_key(client, workspace_id, key_name)
