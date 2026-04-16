import json
import boto3
import cfnresponse

def handler(event, context):
    print(f"Event: {json.dumps(event)}")
    try:
        if event['RequestType'] == 'Delete':
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {})
            return

        props       = event['ResourceProperties']
        workspace_id = props['WorkspaceId']
        user_ids    = props['UserIds']
        region      = props.get('Region', 'us-east-1')

        grafana = boto3.client('grafana', region_name=region)
        users   = [{'id': uid, 'type': 'SSO_USER'} for uid in user_ids]

        grafana.update_permissions(
            workspaceId=workspace_id,
            updateInstructionBatch=[{
                'action': 'ADD',
                'role':   'ADMIN',
                'users':  users
            }]
        )
        print(f"Assigned {len(users)} users to {workspace_id}")
        cfnresponse.send(event, context, cfnresponse.SUCCESS,
            {'Message': f'Assigned {len(users)} users as Admin'})

    except Exception as e:
        print(f"Error: {str(e)}")
        cfnresponse.send(event, context, cfnresponse.FAILED,
            {'Error': str(e)})
