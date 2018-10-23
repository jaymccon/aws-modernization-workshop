from __future__ import print_function
import boto3
import json
import time
import traceback
from botocore.vendored import requests
from botocore.exceptions import ClientError

def getInstanceState(client,instanceName):
    try:
        response = client.describe_instances(
            Filters=[
                {
                    'Name': 'tag:Name',
                    'Values': [instanceName]
                }
            ]
        )   
        print(instanceName)
        if len(response['Reservations']) < 1:
            print("No instances found, sleeping 5 seconds and retrying.")
            time.sleep(5)
            getInstanceState(client,instanceName)
        if response['Reservations'][0]['Instances'][0]['State']['Name'] != "running":
            print("Instance is not in running state, sleeping 5 seconds and retrying.")
            time.sleep(5)
            getInstanceState(client,instanceName)
        return response['Reservations'][0]['Instances'][0]['InstanceId']    
    except ClientError as e:
        print(e.response['Error']['Message'])

def attachRole(client,iam_instance_profile,InstanceId):
    client.associate_iam_instance_profile(IamInstanceProfile=iam_instance_profile, InstanceId=InstanceId)

def handler(event,context):
    try:
        print(event['RequestType'])
        if event['RequestType'] == 'Create':
            # Open AWS clients
            client = boto3.client('ec2')
            
            instanceName = getInstanceState(client,'{}{}{}{}'.format('aws-cloud9-',event['ResourceProperties']['StackName'],'-',event['ResourceProperties']['EnvironmentId']))

            # Get the InstanceId of the Cloud9 IDE
            try:
                print("Getting instance information for instance name {}.".format(instanceName))
                response = client.describe_instances()    
                instance = response['Reservations'][0]['Instances'][0]
                instance['BlockVolumeId'] = instance['BlockDeviceMappings'][0]['Ebs']['VolumeId']
            except ClientError as e:
                print("Failed getting instance information!")
                print(e)
                return False
        
            # Wait for Instance to become ready before adding Role
            try:
                print("Getting instance state for {}".format(instanceName))
                while instance['State']['Name'] != 'running':
                    print("Instance state is not ready, sleeping 5 seconds and retrying.")
                    time.sleep(5)
                    instance = client.describe_instances(InstanceIds=[instance['InstanceId']])['Reservations'][0]['Instances'][0]
            except ClientError as e:
                print("Failed getting instance state!")
                print(e)
                return False
                
            # Modify this instance Role
            try: 
                # Create the IamInstanceProfile request object
                iam_instance_profile = {
                    'Arn': event['ResourceProperties']['C9InstanceProfileArn'],
                    'Name': event['ResourceProperties']['C9InstanceProfileName']
                }
                print("Attaching IAM role to instance {}.".format(instanceName))
                attachRole(client,iam_instance_profile,instance['InstanceId'])
            except ClientError as e: 
                print("Failed attaching IAM role!")
                print(e)
                #return False

            # Modify the size of the Cloud9 IDE EBS volume
            try:
                waiter = client.get_waiter('instance_status_ok').wait(InstanceIds=[instance['InstanceId']])
                print("Resizing volume {} for instance {} to {}. This will take several minutes to complete.".format(instance['BlockVolumeId'],instance['InstanceId'],event['ResourceProperties']['EBSVolumeSize']))
                client.modify_volume(VolumeId=instance['BlockVolumeId'],Size=int(event['ResourceProperties']['EBSVolumeSize']))
            except ClientError as e: 
                print("Failed to resize volume!")
                print(e)
                #return False

            # Reboot the Cloud9 IDE
            try:
                volume_state = client.describe_volumes_modifications(VolumeIds=[instance['BlockVolumeId']])['VolumesModifications'][0]
                while volume_state['ModificationState'] != 'completed':
                    time.sleep(5)
                    volume_state = client.describe_volumes_modifications(VolumeIds=[instance['BlockVolumeId']])['VolumesModifications'][0]
                print("Restarting instance {}.".format(instanceName))
                client.reboot_instances(InstanceIds=[instance['InstanceId']])
            except ClientError as e: 
                print("Failed to restart instance!")
                print(e)
                #return False

        elif event['RequestType'] == 'Update':
            print(event['RequestType'])
            return True
        elif event['RequestType'] == 'Delete':
            print(event['RequestType'])
            return True
    except:
        print (traceback.print_exc())