from __future__ import print_function
import time
import boto3
from .crhelper import *

init_fail = False
try:
    # Place initialization code here
    client = boto3.client('ec2')
    log.info("Container initialization completed")
except Exception as err:
    log.error(err, exc_info=True)
    init_fail = err


def get_instance(instance_name):
    while True:
        response = client.describe_instances(Filters=[{'Name': 'tag:Name', 'Values': [instance_name]}])
        if len(response['Reservations']) == 1:
            break
        if response['Reservations'][0]['Instances'][0]['State']['Name'] == "running":
            break
        print("instance not stabilised, sleeping 5 seconds and retrying.")
        time.sleep(5)
    return response['Reservations'][0]['Instances'][0]


def attach_role(iam_instance_profile, instance_id):
    client.associate_iam_instance_profile(IamInstanceProfile=iam_instance_profile, InstanceId=instance_id)


def create(event, context):
    instance = get_instance('{}{}{}{}'.format(
                            'aws-cloud9-', event['ResourceProperties']['StackName'],
                            '-', event['ResourceProperties']['EnvironmentId']))

    instance_name = instance['InstanceId']

    # Get the volume id of the Cloud9 IDE
    block_volume_id = instance['BlockDeviceMappings'][0]['Ebs']['VolumeId']

    # Create the IamInstanceProfile request object
    iam_instance_profile = {
        'Arn': event['ResourceProperties']['C9InstanceProfileArn'],
        'Name': event['ResourceProperties']['C9InstanceProfileName']
    }
    print("Attaching IAM role to instance {}.".format(instance_name))
    attach_role(iam_instance_profile, instance['InstanceId'])

    # Modify the size of the Cloud9 IDE EBS volume
    client.get_waiter('instance_status_ok').wait(InstanceIds=[instance['InstanceId']])
    print("Resizing volume {} for instance {} to {}. This will take several minutes to complete.".format(
        instance['BlockVolumeId'], instance['InstanceId'], event['ResourceProperties']['EBSVolumeSize']))
    client.modify_volume(VolumeId=block_volume_id,
                         Size=int(event['ResourceProperties']['EBSVolumeSize']))
    event["Poll"] = True
    event["PhysicalResourceId"] = block_volume_id
    setup_poll(event, context)
    return block_volume_id, {}


def poll(event, context):
    block_volume_id = event["PhysicalResourceId"]
    response_data = {}
    volume_state = client.describe_volumes_modifications(VolumeIds=[block_volume_id])['VolumesModifications'][0]
    if volume_state['ModificationState'] != 'completed':
        print("Restarting instance {}.".format(instance_name))    
        client.reboot_instances(InstanceIds=[instance['InstanceId']])
        response_data['Complete'] = True
    return block_volume_id, response_data


def update(event, context):
    physical_resource_id = event['PhysicalResourceId']
    response_data = {}
    return physical_resource_id, response_data


def delete(event, context):
    return


def handler(event, context):
    global log
    logger = log_config(event)
    return cfn_handler(event, context, create, update, delete, poll, logger, init_fail)

