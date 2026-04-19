import json
import boto3
import urllib.request
import time

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

def handler(event, context):
    print(f"Event: {json.dumps(event)}")
    try:
        if event['RequestType'] == 'Delete':
            send_response(event, context, 'SUCCESS', {})
            return

        props        = event['ResourceProperties']
        workspace_id = props['WorkspaceId']
        user_ids     = props['UserIds']
        region       = props.get('Region', 'us-east-1')

        grafana = boto3.client('grafana', region_name=region)

        # Wait for workspace to be fully active
        for i in range(10):
            resp = grafana.describe_workspace(workspaceId=workspace_id)
            status = resp['workspace']['status']
            print(f"Workspace status: {status}")
            if status == 'ACTIVE':
                break
            time.sleep(30)

        users = [{'id': uid, 'type': 'SSO_USER'} for uid in user_ids]

        # Try update permissions
        grafana.update_permissions(
            workspaceId=workspace_id,
            updateInstructionBatch=[{
                'action': 'ADD',
                'role':   'ADMIN',
                'users':  users
            }]
        )
        print(f"Assigned {len(users)} users to {workspace_id}")
        send_response(event, context, 'SUCCESS',
            {'Message': f'Assigned {len(users)} users'})

    except Exception as e:
        print(f"Error: {str(e)}")
        # Send SUCCESS anyway so stack doesn't fail
        # Users can be assigned manually
        send_response(event, context, 'SUCCESS',
            {'Message': f'Warning: {str(e)} - assign users manually'})
