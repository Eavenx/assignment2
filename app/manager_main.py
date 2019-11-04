from flask import render_template, redirect, url_for, request, flash
from app import webapp

import boto3
from app import config
from datetime import datetime, timedelta
from operator import itemgetter

from app import elb_op

import mysql.connector


@webapp.route('/ec2_examples', methods=['GET'])
# Display an HTML list of all ec2 instances
def ec2_list():
    # create connection to ec2
    ec2 = boto3.resource('ec2')

    instances = ec2.instances.all()

    s3 = boto3.resource('s3')

    buckets = s3.buckets.all()

    # Test CloudWatch avgs
    workers_list = []
    for instance in instances:
        # filter db and mananger
        if instance.id != config.DATABASE_ID and instance.id != config.MANAGER_ID:  # Is database instance in ec2?
            if (instance.state['Name'] != 'terminated') and (len(instance.tags) != 0):
                if instance.tags[0]['Value'] == 'work':
                    workers_list.append(instance.id)

    # Open DB Connection
    cnx = mysql.connector.connect(user=config.db_config['user'], password=config.db_config['password'],
                                  host=config.db_config['host'],
                                  database=config.db_config['database'])
    cursor = cnx.cursor()

    # Query DB for Autoscale settings
    cursor.execute("SELECT scale,upper_bound,lower_bound,scale_up,scale_down FROM autoscale WHERE id = 1")
    auto_scale_data = cursor.fetchall()

    if (len(auto_scale_data) == 0):
        flash("Database is missing autoscale data")

    for scale, upper_bound, lower_bound, scale_up, scale_down in auto_scale_data:
        AUTO_scale = scale
        AUTO_upper_bound = upper_bound
        AUTO_lower_bound = lower_bound
        AUTO_scale_up = scale_up
        AUTO_scale_down = scale_down

    # Close DB Connection
    cursor.close()
    cnx.close()
    return render_template("ec2_examples/list.html", title="EC2 Instances", instances=instances, buckets=buckets,
                           manager=config.MANAGER_ID,
                           database=config.DATABASE_ID,
                           upperBound=AUTO_upper_bound,
                           lowerBound=AUTO_lower_bound,
                           scaleUp=AUTO_scale_up,
                           scaleDown=AUTO_scale_down,
                           scaleStatus=AUTO_scale)


@webapp.route('/ec2_examples/<id>', methods=['GET'])
# Display details about a specific instance.
def ec2_view(id):
    ec2 = boto3.resource('ec2')

    instance = ec2.Instance(id)

    client = boto3.client('cloudwatch')

    metric_name = 'CPUUtilization'

    ##    CPUUtilization, NetworkIn, NetworkOut, NetworkPacketsIn,
    #    NetworkPacketsOut, DiskWriteBytes, DiskReadBytes, DiskWriteOps,
    #    DiskReadOps, CPUCreditBalance, CPUCreditUsage, StatusCheckFailed,
    #    StatusCheckFailed_Instance, StatusCheckFailed_System

    namespace = 'AWS/EC2'
    statistic = 'Average'  # could be Sum,Maximum,Minimum,SampleCount,Average

    cpu = client.get_metric_statistics(
        Period=1 * 60,
        StartTime=datetime.utcnow() - timedelta(seconds=60 * 60),
        EndTime=datetime.utcnow() - timedelta(seconds=0 * 60),
        MetricName=metric_name,
        Namespace=namespace,  # Unit='Percent',
        Statistics=[statistic],
        Dimensions=[{'Name': 'InstanceId', 'Value': id}]
    )

    cpu_stats = []

    for point in cpu['Datapoints']:
        hour = point['Timestamp'].hour
        minute = point['Timestamp'].minute
        time = hour + minute / 60
        cpu_stats.append([time, point['Average']])

    cpu_stats = sorted(cpu_stats, key=itemgetter(0))

    statistic = 'Sum'  # could be Sum,Maximum,Minimum,SampleCount,Average

    network_in = client.get_metric_statistics(
        Period=1 * 60,
        StartTime=datetime.utcnow() - timedelta(seconds=60 * 60),
        EndTime=datetime.utcnow() - timedelta(seconds=0 * 60),
        MetricName='NetworkIn',
        Namespace=namespace,  # Unit='Percent',
        Statistics=[statistic],
        Dimensions=[{'Name': 'InstanceId', 'Value': id}]
    )

    net_in_stats = []

    for point in network_in['Datapoints']:
        hour = point['Timestamp'].hour
        minute = point['Timestamp'].minute
        time = hour + minute / 60
        net_in_stats.append([time, point['Sum']])

    net_in_stats = sorted(net_in_stats, key=itemgetter(0))

    network_out = client.get_metric_statistics(
        Period=5 * 60,
        StartTime=datetime.utcnow() - timedelta(seconds=60 * 60),
        EndTime=datetime.utcnow() - timedelta(seconds=0 * 60),
        MetricName='NetworkOut',
        Namespace=namespace,  # Unit='Percent',
        Statistics=[statistic],
        Dimensions=[{'Name': 'InstanceId', 'Value': id}]
    )

    net_out_stats = []

    for point in network_out['Datapoints']:
        hour = point['Timestamp'].hour
        minute = point['Timestamp'].minute
        time = hour + minute / 60
        net_out_stats.append([time, point['Sum']])

        net_out_stats = sorted(net_out_stats, key=itemgetter(0))

    return render_template("ec2_examples/view.html", title="Instance Info",
                           instance=instance,
                           cpu_stats=cpu_stats,
                           net_in_stats=net_in_stats,
                           net_out_stats=net_out_stats)


@webapp.route('/ec2_examples/create', methods=['POST'])
# Start a new EC2 instance
def ec2_create():
    ec2 = boto3.resource('ec2')

    new_instance = ec2.create_instances(ImageId=config.ami_id,
                                        MinCount=config.EC2_count,
                                        MaxCount=config.EC2_count,
                                        UserData=config.EC2_userdata,
                                        InstanceType=config.EC2_instance,
                                        KeyName=config.EC2_keyName,
                                        SecurityGroupIds=config.EC2_security_group_id,
                                        Monitoring={'Enabled': config.EC2_monitor},
                                        TagSpecifications=[{'ResourceType': 'instance', 'Tags': [
                                            {'Key': config.EC2_target_key, 'Value': config.EC2_target_value}, ]}, ])

    for instance in new_instance:
        # Add New Instance to ELB
        elb_op.elb_add_instance(instance.id)

    return redirect(url_for('ec2_list'))


@webapp.route('/ec2_examples/delete/<id>', methods=['POST'])
# Terminate a EC2 instance
def ec2_destroy(id):
    # create connection to ec2
    ec2 = boto3.resource('ec2')

    delete = ec2.instances.filter(InstanceIds=[id])

    # delete instance in ELB
    for instance in delete:
        elb_op.elb_remove_instance(instance.id)
        instance.terminate()

    return redirect(url_for('ec2_list'))


@webapp.route('/ec2_examples/deleteAll/', methods=['POST'])
# Terminate all instances and clear S3 data
def delete_all_userdata():
    cnx = mysql.connector.connect(user=config.db_config['user'], password=config.db_config['password'],
                                  host=config.db_config['host'],
                                  database=config.db_config['database'])
    cursor = cnx.cursor()
    try:
        # delete data from tables but keep the structure
        cursor.execute("DELETE FROM user_information;")
        cursor.execute("DELETE FROM image;")
        cnx.commit()
    except:
        cnx.rollback

    cursor.close()
    cnx.close()

    s3 = boto3.resource('s3')
    bucket = s3.Bucket(config.S3_BUCKET_NAME)

    bucket.objects.all().delete()

    return redirect(url_for('ec2_list'))


@webapp.route('/ec2_examples/scaling/', methods=['POST'])
# modify configure of scaling
def scaling_modified():
    # Get User Data
    newUpperBound = request.form['upperBound']
    newlowerBound = request.form['lowerBound']
    newScaleUp = request.form['scaleUp']
    newScaleDown = request.form['scaleDown']

    update_prefix = "UPDATE autoscale SET "
    update_suffix = " WHERE id = 1"
    update_entry = []

    # Update Parameters Check
    if newUpperBound:
        if not (newUpperBound.isdigit()):
            flash("Upper Bound %s is not a valid number. Entry was not updated." % (newUpperBound))
        elif (int(newUpperBound) > 100 or int(newUpperBound) < 0):
            flash("Upper Bound %s must be between 0-100. Entry was not updated." % (newUpperBound))
        else:
            update_entry.append("upper_bound = " + newUpperBound)
    if newlowerBound:
        if not (newlowerBound.isdigit()):
            flash("Lower Bound %s is not a valid  number. Entry was not updated." % (newlowerBound))
        elif (int(newlowerBound) > 100 or int(newlowerBound) < 0):
            flash("Lower Bound %s must be between 0-100. Entry was not updated." % (newlowerBound))
        else:
            update_entry.append("lower_bound = " + newlowerBound)
    if newScaleUp:
        if not (newScaleUp.isdigit()):
            flash("Scale Up %s is not a valid number. Entry was not updated." % (newScaleUp))
        elif (int(newScaleUp) < 1 or int(newScaleUp) > 10):
            flash("Scale Up %s must be between 1-10. Entry was not updated." % (newScaleUp))
        else:
            update_entry.append("scale_up = " + newScaleUp)
    if newScaleDown:
        if not (newScaleDown.isdigit()):
            flash("Scale Down %s is not a valid number. Entry was not updated." % (newScaleDown))
        elif (int(newScaleDown) < 1 or int(newScaleDown) > 10):
            flash("Scale Down %s must be between 1-10. Entry was not updated." % (newScaleDown))
        else:
            update_entry.append("scale_down = " + newScaleDown)

    cnx = mysql.connector.connect(user=config.db_config['user'], password=config.db_config['password'],
                                  host=config.db_config['host'],
                                  database=config.db_config['database'])
    cursor = cnx.cursor()

    # Update Fields that were valid
    for update_middle in update_entry:
        update_command = update_prefix + update_middle + update_suffix
        try:
            cursor.execute(update_command)
            cnx.commit()
        except:
            cnx.rollback()

            # Close DB Connection
    cursor.close()
    cnx.close()

    return redirect(url_for('ec2_list'))


@webapp.route('/ec2_examples/configscaling', methods=['POST'])
def config_scaling():
    # Get User DATA
    newautoScaling = request.form['autoScaling']

    update_prefix = "UPDATE autoscale SET "
    update_suffix = " WHERE id = 1"
    update_entry = []

    # Check Value
    if newautoScaling == "ON":
        update_entry.append("scale = 'ON'")
    if newautoScaling == "OFF":
        update_entry.append("scale = 'OFF'")

    cnx = mysql.connector.connect(user=config.db_config['user'], password=config.db_config['password'],
                                  host=config.db_config['host'],
                                  database=config.db_config['database'])
    cursor = cnx.cursor()

    # Update Fields that were valid
    for update_middle in update_entry:
        update_command = update_prefix + update_middle + update_suffix
        try:
            cursor.execute(update_command)
            cnx.commit()
        except:
            cnx.rollback()

            # Close DB Connection
    cursor.close()
    cnx.close()

    return redirect(url_for('ec2_list'))
