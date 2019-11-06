ami_id = 'ami-0df7fa91aa9ef7ed9'  # need change to new ami
EC2_count = 1
EC2_userdata = '''#!/bin/bash
python3 -m pip install --user boto3
sleep 20
cd /home/ubuntu/Desktop/A1_3.0 
python3 ./run.py >& /tmp/message'''
EC2_instance = 't2.micro'
EC2_keyName = 'A1'  # use your config
EC2_security_group_id = ['sg-eb879abb']  # use your config
EC2_monitor = True
EC2_target_key = 'worker'  # value in tag casual
EC2_target_value = 'work'  # value in tag casual

db_config = {'user': 'admin',
             'password': '12345678',
             'host': 'alldata.c3fcxrbhjwar.us-east-1.rds.amazonaws.com',
             'database': 'mydb'}


MANAGER_ID = 'i-04ec52fb3814d9025'  # change
S3_BUCKET_NAME = 'a2homework'
