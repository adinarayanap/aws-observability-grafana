import json
import urllib.request

SUCCESS = "SUCCESS"
FAILED = "FAILED"

def send(event, context, responseStatus, responseData, physicalResourceId=None, noEcho=False):
    responseUrl = event['ResponseURL']
    responseBody = {
        'Status': responseStatus,
        'Reason': 'See the details in CloudWatch Log Stream: ' + context.log_stream_name,
        'PhysicalResourceId': physicalResourceId or context.log_stream_name,
        'StackId': event['StackId'],
        'RequestId': event['RequestId'],
        'LogicalResourceId': event['LogicalResourceId'],
        'NoEcho': noEcho,
        'Data': responseData
    }
    json_responseBody = json.dumps(responseBody)
    headers = {
        'content-type': '',
        'content-length': str(len(json_responseBody))
    }
    try:
        req = urllib.request.Request(
            responseUrl,
            data=json_responseBody.encode('utf-8'),
            headers=headers,
            method='PUT'
        )
        urllib.request.urlopen(req)
        print("cfnresponse sent successfully")
    except Exception as e:
        print(f"cfnresponse failed: {e}")
