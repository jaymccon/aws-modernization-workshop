from __future__ import print_function
import time
import traceback
import boto3
from botocore.exceptions import ClientError


def get_instance_state(client, instance_name):
    try:
        response = client.describe_instances(
            Filters=[
                {
                    'Name': 'tag:Name',
                    'Values': [instance_name]
                }
            ]
        )
        print("Found instance {}.".format(instance_name))
        if len(response['Reservations']) < 1:
            print("No instances found, sleeping 5 seconds and retrying.")
            time.sleep(5)
            get_instance_state(client, instance_name)
        if response['Reservations'][0]['Instances'][0]['State']['Name'] != "running":
            print("Instance is not in running state, sleeping 5 seconds and retrying.")
            time.sleep(5)
            get_instance_state(client, instance_name)
        return response['Reservations'][0]['Instances'][0]['InstanceId']
    except ClientError as e:
        print(e.response['Error']['Message'])


def attach_role(client, iam_instance_profile, instance_id):
    client.associate_iam_instance_profile(IamInstanceProfile=iam_instance_profile, InstanceId=instance_id)


def handler(event):
    try:
        print("Received request to {}.".format(event['RequestType']))
        if event['RequestType'] == 'Create':
            # Open AWS clients
            client = boto3.client('ec2')

            instance_name = get_instance_state(client,
                                               '{}{}{}{}'.format('aws-cloud9-',
                                                                 event['ResourceProperties']['StackName'],
                                                                 '-', event['ResourceProperties']['EnvironmentId']))

            response = client.describe_instances()

            # Get the InstanceId of the Cloud9 IDE
            try:
                print("Getting instance information for instance {}.".format(instance_name))
                instance = response['Reservations'][0]['Instances'][0]
                print(instance)
                instance['BlockVolumeId'] = instance['BlockDeviceMappings'][0]['Ebs']['VolumeId']
            except ClientError as e:
                print("Failed getting instance information!")
                print(e)
                return False

            # Wait for Instance to become ready before adding Role
            try:
                print("Getting instance state for {}".format(instance_name))
                while instance['State']['Name'] != 'running':
                    print("Instance state is not ready, sleeping 5 seconds and retrying.")
                    time.sleep(5)
                    instance = \
                        client.describe_instances(InstanceIds=[instance['InstanceId']])['Reservations'][0]['Instances'][
                            0]
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
                print("Attaching IAM role to instance {}.".format(instance_name))
                attach_role(client, iam_instance_profile, instance['InstanceId'])
            except ClientError as e:
                print("Failed attaching IAM role!")
                print(e)

            # Modify the size of the Cloud9 IDE EBS volume
            try:
                client.get_waiter('instance_status_ok').wait(InstanceIds=[instance['InstanceId']])
                print("Resizing volume {} for instance {} to {}. This will take several minutes to complete.".format(
                    instance['BlockVolumeId'], instance['InstanceId'], event['ResourceProperties']['EBSVolumeSize']))
                client.modify_volume(VolumeId=instance['BlockVolumeId'],
                                     Size=int(event['ResourceProperties']['EBSVolumeSize']))
            except ClientError as e:
                print("Failed to resize volume!")
                print(e)

            # Reboot the Cloud9 IDE
            try:
                volume_state = \
                    client.describe_volumes_modifications(VolumeIds=[instance['BlockVolumeId']])[
                        'VolumesModifications'][0]
                while volume_state['ModificationState'] != 'completed':
                    time.sleep(5)
                    volume_state = client.describe_volumes_modifications(VolumeIds=[instance['BlockVolumeId']])[
                        'VolumesModifications'][0]
                print("Restarting instance {}.".format(instance_name))
                client.reboot_instances(InstanceIds=[instance['InstanceId']])
            except ClientError as e:
                print("Failed to restart instance!")
                print(e)

        elif event['RequestType'] == 'Update':
            print("Received request to {}.".format(event['RequestType']))
            return True
        elif event['RequestType'] == 'Delete':
            print("Received request to {}.".format(event['RequestType']))
            return True
    except ClientError:
        print(traceback.print_exc())
