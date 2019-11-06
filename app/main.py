import collections
from flask import render_template, redirect, url_for, request, flash, session
from app import webapp, db
import json
import boto3
from app import config
from datetime import datetime, timedelta
from operator import itemgetter
from app import elb_op
import mysql.connector
from pytz import timezone

from app.autoscale import increase_worker_nodes
from app.autoscale import decrease_worker_nodes

#global
flagmsg = 0 #appear message once

class RequestPerMinute(db.Model):
    __tablename__ = 'requestperminute'
    requestid = db.Column(db.Integer, primary_key=True)
    instance_id = db.Column(db.String(50))
    timestamp = db.Column(db.DateTime)  # A type for datetime.datetime() objects.

    def __repr__(self):
        return '<RequestPerMinute {}>'.format(self.instance_id)


def get_requests_per_minute(instance, start_time, end_time):
    datetimes = RequestPerMinute.query.filter(RequestPerMinute.instance_id == instance) \
        .filter(RequestPerMinute.timestamp <= end_time) \
        .filter(RequestPerMinute.timestamp >= start_time) \
        .with_entities(RequestPerMinute.timestamp).all()

    timestamps = list(map(lambda x: int(round(datetime.timestamp(x[0]))), datetimes))

    ret = []
    dict = collections.Counter(timestamps)

    start_timestamp = int(round(datetime.timestamp(start_time)))
    end_timestamp = int(round(datetime.timestamp(end_time)))

    for i in range(start_timestamp, end_timestamp, 60):
        count = 0
        for j in range(i, i + 60):
            count += dict[j]

        ret.append([i * 1000, count])
    # print(ret)
    return json.dumps(ret)


def get_time_span(latest):
    end_time = datetime.now()  # (timezone(webapp.config['ZONE']))
    start_time = end_time - timedelta(seconds=latest)
    return start_time, end_time


@webapp.route('/', methods=['GET'])
@webapp.route('/index', methods=['GET'])
def clear():
    session.clear()
    return redirect(url_for('main'))

@webapp.route('/main', methods=['GET'])
def main():
    global flagmsg

    # Display an HTML list of all ec2 instances
    # create connection to ec2
    ec2 = boto3.resource('ec2')

    instances = ec2.instances.all()

    # calculate workerpool
    workerpool = 0
    for instance in instances:
        # filter db and mananger
        if instance.id != config.MANAGER_ID:
            if (instance.state['Name'] != ('terminated' or 'shutting-down')) and (len(instance.tags) != 0):
                if instance.tags[0]['Value'] == 'work':
                    workerpool = workerpool + 1

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

    # get elb entry point
    elbList = boto3.client('elb')
    elb = elbList.describe_load_balancers(
        LoadBalancerNames=['A2loadbalance'])
    elbA2Des = elb['LoadBalancerDescriptions']
    elbDNS = elbA2Des[0]['DNSName']

    if flagmsg == 1:
        session.pop('msg')
        flagmsg = 0
    elif 'msg' in session:
        flagmsg = 1

    return render_template("ec2_examples/list.html", title="Manager UI", instances=instances,
                           manager=config.MANAGER_ID,

                           upperBound=AUTO_upper_bound,
                           lowerBound=AUTO_lower_bound,
                           scaleUp=AUTO_scale_up,
                           scaleDown=AUTO_scale_down,
                           scaleStatus=AUTO_scale,
                           elbDNS=elbDNS,
                           workerpool=workerpool)


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
        StartTime=datetime.utcnow() - timedelta(seconds=31 * 60),
        EndTime=datetime.utcnow() - timedelta(seconds=0 * 60),
        MetricName=metric_name,
        Namespace=namespace,  # Unit='Percent',
        Statistics=[statistic],
        Dimensions=[{'Name': 'InstanceId', 'Value': id}]
    )

    cpu_stats = []

    mint = 0
    for point in cpu['Datapoints']:
        hour = point['Timestamp'].hour
        minute = point['Timestamp'].minute
        time = mint
        cpu_stats.append([time, point['Average']])
        mint = mint + 1

    start_time, end_time = get_time_span(7200)
    instances = json.loads(request.data.decode('utf-8'))
    http_request_stats = []
    for instance in instances:
        http_request_stats.append({
            "name": instance,
            "data": get_requests_per_minute(instance, start_time, end_time)
        })

    return render_template("ec2_examples/view.html", title="Instance Info",
                           instance=instance,
                           cpu_stats=cpu_stats,
                           http_request_stats=http_request_stats)


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

    return redirect(url_for('main'))


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

    return redirect(url_for('main'))


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

    return redirect(url_for('main'))


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

    return redirect(url_for('main'))


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

    return redirect(url_for('main'))


@webapp.route('/ec2_examples/increase1/', methods=['POST'])
def increase1():
    increase_worker_nodes(1)
    session['msg'] = "Success increase worker pool by 1"
    return redirect(url_for('main'))


@webapp.route('/ec2_examples/decrease1/', methods=['POST'])
def decrease1():
    decrease_worker_nodes(1)
    session['msg'] = "Success decrease worker pool by 1"
    return redirect(url_for('main'))
